# 8/27 14:18 runner.py alter 子句提取 fix

## 症状
- 业务 RD 8/27 14:11 在 110 prod 启动 gh-ost task #5 (instance 27 历史库 8.0.22)，报 `Error 1064 (42000): You have an error in your SQL syntax; ... near 'table\n  test\nmodify\n  ...`
- 截图：错误信息显示 gh-ost 把整个用户原始 SQL 当 --alter 参数喂进去，MySQL 解析 ALTER TABLE 时报 1064

## 根因
- `sql/extensions/ddl_gh_ost/services/runner.py` 8/24 fix 改的 alter 提取逻辑（line 65-66）反了：
  ```python
  # 反逻辑: alter if alter.strip().upper().startswith("ALTER") else f"ALTER TABLE {alter}"
  ```
- 这个逻辑的意图是 "传完整 SQL 让 gh-ost 自己解析"，但 gh-ost 1.1.10 期望 --alter 接收**裸子句**（MODIFY / ADD / DROP ...），内部拼成 `ALTER TABLE <ghost_table> <alter_subclause>`
- 业务库 8.0.22 Archery 解析后保留用户原始 SQL 格式（多行+小写+反引号），task.alter_statement 存的是原始 SQL
- 反逻辑保留原值，gh-ost 1.1.10 报 SQL syntax error 1064 near 'table'

## 为什么 8/24 演练 16/16 PASS
- 134 dev 演练用的是 instance 5 (prod core for etc变更 172.20.2.9:6446, MySQL 5.7)
- Archery 5.7 解析 SQL 标准化（大写+单行），存到 task.alter_statement 已经是裸子句
- 8/24 反逻辑走 True 分支保留原值，但 5.7 标准化的 alter 已经是裸子句，所以 gh-ost 接受
- 8/25 实战 3 次（task #70/71/72）也都用 instance 5 (5.7)，继续凑巧 PASS

## 暴露路径
- 8/27 14:04 业务 RD mkq 在 110 prod 启动 task #4 (instance 27 历史库 8.0.22)
- 8/27 14:11 修完 insufficient privileges 后 retry 成功启动 gh-ost
- gh-ost 启动后立即报 SQL syntax 1064，暴露 8.0.22 业务库 Archery 解析保留原始格式这个之前没测过的场景
- 同一时间 task #5 (instance 27 同样库) 也报同样错

## 修法
- `sql/extensions/ddl_gh_ost/services/runner.py` line 65-66 改正则提取子句：
  ```python
  import re
  alter = task.alter_statement or ""
  m = re.match(
      r"^\s*alter\s+table\s+`?\S+`?\s*(.*)$",
      alter.strip(),
      re.IGNORECASE | re.DOTALL,
  )
  alter_arg = m.group(1) if m else alter.strip()
  ```
- 兼容三种格式：
  1. `ALTER TABLE \`test\` MODIFY ...` (5.7 标准化)
  2. `alter table\n  test\nmodify\n  ...` (8.0.22 原始多行)
  3. `MODIFY ...` (已经是裸子句, fallback 原值)
- 正则用 `re.IGNORECASE | re.DOTALL`，不区分大小写 + 让 `.` 匹配换行

## 验证
- **134 dev** (commit 后): scp runner.py → /opt/archery/prod/, kill master 60340 → systemd 拉新 29587
  - 真实 task #1 alter `ALTER TABLE accesscard_account ADD COLUMN alpha_test_col VARCHAR(50)` → `--alter='ADD COLUMN alpha_test_col VARCHAR(50)'` ✓
  - 6 种演练格式全 PASS
  - 5 端点 HTTP 全 OK
- **110 prod**: scp runner.py → /dbdata/archery_v114_c9236a0/, kill master 36746 → nohup 拉新 39672
  - 真实 task #4 alter (复杂多行 modify + add 2 column) → `--alter` 正确去掉 `alter table\n  test\n` 前缀 ✓
  - 真实 task #5 alter (无反引号 test 表名) → `--alter` 正确去掉 `alter table\n  test\n` 前缀 ✓
  - 6 种演练格式全 PASS
  - 5 端点 HTTP 全 OK (302 重定向到 login)

## 业务 RD 后续
- 业务 RD mkq 在浏览器 retry task #5，gh-ost 1.1.10 接受 `--alter='modify ...'` 裸子句
- instance 27 (8.0.22 历史库) 14:11 已加完整权限（SUPER + REPLICATION CLIENT/SLAVE + ALL on hly_doc_model.* + 24 dynamic privs）

## 教训（跨项目可复用）
1. **8.0 业务库 Archery 解析保留原始 SQL 格式** — 5.7 标准化（大写+单行），8.0 保留原始（多行+小写+反引号）。同样 SQL 走不同业务库，task.alter_statement 长得不一样。8/24 fix 漏测 8.0 业务库
2. **演练必做"多业务库 + 多版本 MySQL 覆盖"** — 8/24 演练只跑 instance 5 (5.7) 凑巧 PASS，instance 27 (8.0) 第一次实战就暴露。推 prod 实战必走"5.7 + 8.0 双验"
3. **gh-ost --alter 期望裸子句不是完整 SQL** — 注释说"传完整 SQL 让它自己解析"是错的，gh-ost 1.1.10 内部拼 ALTER TABLE 时会报错
4. **"fix 字段提取"类改动必演 3 种以上真实输入** — 5.7 标准化 / 8.0 原始 / 裸子句 / 多行 / 反引号 / 无反引号，每种都要测到

## 同源 entry
- 8/27 14:11 gh-ost insufficient privileges (instance 27 8.0.22 历史库第一次实战)
- 8/27 13:50 gh-ost 启动按钮缺失 (业务 RD admin 自救改 group)
- 8/24 gh-ost v0.3.0-beta 推 110 + 16/16 演练 PASS (instance 5 5.7 凑巧)
- 8/13 v0.4.0 gh-ost 拍板 (instance 5 5.7 演练)

## 关联 commit
- 8/27 14:18 待 commit
- 8/27 14:30 134 dev 部署 (scp + kill + systemd 拉新)
- 8/27 14:32 110 prod 部署 (scp + kill + nohup 拉新)
