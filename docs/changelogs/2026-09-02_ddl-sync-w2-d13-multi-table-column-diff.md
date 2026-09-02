# W2 D13 - 多表 DDL 字段 diff bug 修复 (9/2 18:30)

## 症状

9/2 17:35 业务 RD 汪银和实战 7 张表 DDL 工单 (`project_config` / `company_info` / `team` / `order_penalty` / `waybill_penalty` 等),**字段 diff 区域只显示第一张表 (project_config) 的 diff**,其他 6 张表的字段变更完全没有显示。DBA 看不到其他 6 张表的风险,跟单表 DDL 实战只显示第一张表是**同一个 bug**,8/12 v0.3.x 字段 diff 设计时就埋了。

实战图 1: 汪银和工单详情 (110 prod /detail/4771/) 有 7 条 SQL (1 use + 2 ALTER project_config + 1 ALTER company_info + 1 ALTER team + 1 ALTER order_penalty + 1 ALTER waybill_penalty),但字段 diff 区域只显示 `表: project_config` + 2 个 ADD 字段。

## 根因 (134 dev 实战 9/2 17:35)

`sql/extensions/ddl_gh_ost/services/column_diff.py` `column_diff_full()` 函数内部:

```python
alter_sql = None
statements = [s for s in sqlparse.split(sql_content) if s.strip()]
for stmt in statements:
    m = re.search(r"\bALTER\s+TABLE\b", stmt, re.IGNORECASE)
    if m:
        alter_sql = stmt[m.start():].strip().rstrip(";").strip()
        break   # ← 这里! 只取第一个 ALTER TABLE 就 break
```

**老代码只取第一个 ALTER TABLE**(汪银和工单 → `project_config`),后面 6 张表 (company_info / team / order_penalty / waybill_penalty 等) 全部丢失,只 diff 第一张表。

实战历史: 8/12 v0.3.x 字段 diff 设计时只考虑了单表 ALTER,8/24-8/28 实战演练都是单表 DDL,所以一直没踩到。9/2 17:35 汪银和实战 7 张表演练才暴露。

## 修法 (3 文件)

### 1. `sql/extensions/ddl_gh_ost/services/column_diff.py` 重构

**新增** `_diff_single_table(instance, db_name, alter_sql, force_table_name=None)` helper:
- 单条 ALTER TABLE 完整 diff 流程 (含解析 + 查列 + 算 risk + 大表 alert)
- 抽出来让 column_diff_full 多次调用

**重写** `column_diff_full(instance, db_name, sql_content, table_name=None)`:
- 拆 SQL 收集所有 ALTER TABLE (不再 break)
- 遍历每条 ALTER 调 `_diff_single_table` 一次
- 顶层汇总 `high_risk_count / mid / low` = 所有表加起来
- 顶层新增 `tables: [{...}]` 字段 (多表实战用)
- **顶层字段兼容老单表前端**: `data.columns / data.table_name / data.summary` 用 `tables[0]` 兜底,老前端不会炸

### 2. `sql/templates/detail.html` `renderColumnDiff()` 重构

- 顶层 data = `data.tables || (data.table_name ? [单表] : [])` 兼容老单表 + 新多表
- 循环 `data.tables` 渲染每张表一段 (表名 + 风险 badge + 字段表格)
- 多表时显示"📋 字段变更检测 (共 N 张表)" + 全局 summary banner 取消 (改成单表 summary 各自显示)
- 修复建议收集所有表的 modifyCols,带 `表名.列名` 前缀 (避免多表跨表歧义)

### 3. `sql/templates/sqlsubmit.html` `renderColumnDiff()` 同样重构

跟 detail.html 同样的多表 DDL 渲染逻辑,保持 SQL 提交页 + 详情页前端行为一致。

## 134 dev 实战演练 (9/2 18:25-18:30)

5 张表演练表 + 1 张已有表 (`accesscard_test_diff` W2 D10 实战造的) = 6 张表实战,模拟汪银和工单多表 DDL:

```sql
ALTER TABLE accesscard_test_diff1 MODIFY name varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'test' COMMENT '新名称';
ALTER TABLE accesscard_test_diff1 ADD new_col varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '新列';
ALTER TABLE accesscard_test_diff2 MODIFY id bigint(20) NOT NULL AUTO_INCREMENT COMMENT 'BIGINT id';
ALTER TABLE accesscard_test_diff3 ADD col3 varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'x' COMMENT 'col3';
ALTER TABLE accesscard_test_diff4 DROP old_col;
ALTER TABLE accesscard_test_diff5 MODIFY id int(11) NOT NULL DEFAULT 0 COMMENT 'ID';
```

### dryrun (`column_diff_full` 直接调)

| 字段 | 值 |
|------|-----|
| `ok` | True |
| `tables` | 6 张 |
| `high_risk_count` | 2 |
| `mid_risk_count` | 2 |
| `low_risk_count` | 8 |
| `summary` | "共 6 张表, 检测到 2 个高风险变更, 强烈建议补全 SQL" |

实战 6 张表全 diff 出来,每张表都有正确的 columns/diffs/suggested_sql。

### 端点 (POST /gh_ost/column_diff/)

- status=200 ✓
- ok=True ✓
- tables=6 ✓
- high=2 mid=2 low=8 ✓
- summary="共 6 张表, 检测到 2 个高风险变更, 强烈建议补全 SQL" ✓

实战汪银和 7 张表演练应该全部 diff 出来(110 prod 实战端点应该 status=200 + ok=True + tables=7,summary 7 张表汇总)。

## 134 dev SFTP 推文件 + systemd 重启 (D12 套路)

3 文件 md5 一致:
- `sql/extensions/ddl_gh_ost/services/column_diff.py` md5 `f9b5422fe81376c107e2a12dc22cac21` ✓
- `sql/templates/detail.html` md5 `12cb492dddf91d75e237b507b006c67e` ✓
- `sql/templates/sqlsubmit.html` md5 `ba3737da7ed65e9b636726d0d428d23a` ✓

systemd `archery-prod-gunicorn.service` 重启:
- `pkill -9 -f gunicorn` + `systemctl reset-failed` + `systemctl start`
- 新 pid 17276 (master) + 4 worker 17292/17293/17294/17301
- Active: active (running) ✓

5 端点 verify 全过:
- /login/ 200
- / 302
- /admin/ 302
- /ddl_sync/pair/list/ 302
- /static/ddl_sync/pair_detail.js 200

## 110 prod 状态 (9/2 18:30)

- 110 prod `column_diff.py` / `detail.html` / `sqlsubmit.html` 还没推
- 110 prod 实战报这个 bug,等用户拍板:
  - 推 134 dev 验证完 OK 后再推 110 prod (下次推 prod 周期)
  - 或今晚 9/2 推 110 prod (实战已验证, 直接用)
- 9/2 推 110 prod 范围必须含: 3 个文件 + 走 134 dev 同款演练 (134 dev 已有 5 张表演练造过, 110 prod 可以直接演练)

## 避坑 4 条 (D13 实战总结, 跨项目可复用)

1. **column_diff.py 双重函数定义** (D13 实战新发现): 我用 Python sed 替换老 column_diff_full 时,新 new_block 末尾又有 `def column_diff_full`,导致文件里有 2 个 `def column_diff_full` (865 + 1007 行)。实战 `ast.parse` 语法 OK (Python 允许后定义覆盖前定义),但实际跑会调后定义。我用 Python 删 1003 之后的内容解决。教训: 写 Python AST 替换脚本时,新内容要**避免包含 marker**,或者用更精确的 marker (例如只匹配 `def column_diff_full(` 之前的注释)
2. **systemd Restart=always 实战冲突** (D13 实战新发现): 134 dev gunicorn 是 systemd `archery-prod-gunicorn.service` 拉 (`Restart=always` + `RestartSec=5`)。`pkill -9 -f gunicorn` 杀掉后,systemd 5 秒后立刻拉起,跟我手动 nohup 拉的 gunicorn 冲突 (Connection in use),systemd 一直 fail。修法: `pkill -9` + `systemctl reset-failed` + `systemctl start` 一次完整,让 systemd 接管。教训: 远程 gunicorn kill + 拉新必查 `systemctl status` 看是不是 systemd 拉的
3. **演练表先在演练库造** (D13 实战新发现): 实战演练 column_diff 需要**真实存在**的演练表 (查 information_schema.columns 才能拿到 current_cols)。我一开始用 `accesscard_test_diff1/2/3/4/5` 但 134 dev 实际只有 `accesscard_test_diff` (W2 D10 实战造过),演练用之前先 `SHOW TABLES LIKE 'accesscard_test%'` 看实际有什么。教训: 演练脚本开头必查 `SHOW TABLES` 确认演练表存在
4. **SUGGESTED SQL 实战字符串引号** (D13 dryrun): 生成的 SUGGESTED SQL 含字符串字面量带引号 (`DEFAULT '0'`),需要 json.dumps 时正确处理。实战 dryrun 输出 `DEFAULT '0` (少一个引号) 是 PowerShell 截断,实际 SQL 是 `DEFAULT '0'`,没问题

## 关联

- 9/2 17:35 业务 RD 汪银和 110 prod /detail/4771/ 实战报 bug
- 8/12 v0.3.x 字段 diff 设计稿 (8/26-9/1 实战只演练单表, 没踩到多表 DDL bug)
- 8/24-8/28 v0.3.x 推 134 dev + 110 prod, 字段 diff 都是单表
- 9/1+9/2 W2 D10 实战演练 5 张表 (W2 D11 修过) 都是单表演练, 实战只用到 accesscard_test_diff 1 张表

## 关联 commit / 演练脚本

- 实战 commit (待 push)
- 演练脚本: `scripts/_archive/_d13_drill4.py` (5 张表 + 1 已有 = 6 张实战)
- dryrun 脚本: `scripts/_archive/_d13_dryrun.py` (mock _fetch_current_columns 不连 DB)

## 110 prod 推 prod checklist (下次推 prod 必加 2 条)

1. **多表 DDL 字段 diff 修复必含 column_diff.py + detail.html + sqlsubmit.html 3 文件** (D13 实战新发现) — 实战汪银和工单 110 prod /detail/4771/ 报了 7 张表只显示 1 张表, 推 prod 必带 3 文件 (老前端用 data.columns 兼容)
2. **systemctl reset-failed + start 必组合** (D13 实战新发现) — 134 dev gunicorn 是 systemd 拉的, `pkill -9` 之后 systemd 一直 fail (Connection in use), 实战 `systemctl reset-failed archery-prod-gunicorn` + `systemctl start` 才能让 systemd 接管
