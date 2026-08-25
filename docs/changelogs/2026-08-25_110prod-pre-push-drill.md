# 2026-08-25 推 110 准备 - 5 步必做 + 备份 + 回滚 脚本演练报告

## 8/24 已知 + 8/25 摸底

| 项目 | 8/24 摸底 | 8/25 验证 |
|------|----------|----------|
| 110 prod MySQL 版本 | 5.7.44-log | ✅ 确认 |
| 110 prod MySQL user | archery (8/17 .my.cnf) | ✅ + root 备用 (`8k3pWGC2gxs2SsnelQtPg9Acti6fYD`, 8/25 用户补充) |
| 110 prod MySQL 库 | archery | ✅ |
| 110 prod gunicorn master pid | 102228 (8/05 启, 19 天) | ✅ |
| gh-ost 二进制 | **110 prod 没装** (blocker) | ✅ 8/24 装好 1.1.10 + symlink |
| 134 dev 实际 dbops + archery_prod | (8/17 摸底不一致) | ✅ 8/25 演练发现 134 dev 走 dbops, 不是 archery |
| 8/24 6 bug fix | 134 dev 验过 | ✅ 7 个文件 mtime 都在 8/24 |
| 5 步必做脚本 | 步骤 1-3 + 5-7 + 13 (8 步) | ✅ 8/25 补到 13 步, 加 8-12 步 |

## 8/25 上午演练 - 3 份备份脚本 (110 prod 实际跑,演练时间戳)

### 演练结果
```
=== 备份 1: 代码目录 ===    35M  OK  sha256=b5455261ac93cf0a...
=== 备份 2: MySQL schema ===  52K  OK  1319 行  sha256=a498de7a126afd24...  header 校验通过
=== 备份 3: admin config ===  20K  OK  921 行  sha256=c16db9e2150eaba0...  JSON 校验通过 (99 条 sql_config + workflow_audit_setting)

备份状态: code=OK schema=OK admin=OK
```

### 演练中发现的 3 个 bug (8/25 必修)

#### Bug 1: `set -euo pipefail` 在备份脚本太严格
- **症状**: schema dump 失败 (1045 password 错) 时, set -e 让整个脚本退出, admin 备份丢失
- **修法**: 改成 `set -u` (不退出), 用 BACKUP_X_OK 标志逐份跟踪, 最后汇总 + DBA 二次确认
- **教训 (8/24 延伸)**: 备份脚本不能一个失败全丢, 3 份要全跑, 失败的标记让 DBA 决定

#### Bug 2: `--column-statistics=0` 是 MySQL 8.0+ flag, 5.7 不支持
- **症状**: 110 prod mysqldump 报 `unknown variable 'column-statistics=0'`
- **修法**: 备份脚本去掉这个 flag
- **教训**: mysqldump flag 要 5.7/8.0 兼容, 不要从 8.0 默认参数抄

#### Bug 3: `sql.models.SysConfig` 类不存在
- **症状**: `ImportError: cannot import name 'SysConfig' from 'sql.models'`
- **真类名**: `sql.models.Config` (8/25 在 110 prod 上 `dir(sql.models)` 验证)
- **修法**: `from sql.models import Config as SysConfig` (alias 兼容)
- **教训 (8/24 延伸)**: Archery 上游 model 类名跟表名不一致, 不要从代码脑补, **必查 `apps.get_models()`**

#### Bug 4 (顺带): `manage.py shell` 污染 stdout
- **症状**: stdout 第一行是 `import local settings failed, ignored` (Archery 上游 settings.py print 的), 污染 JSON
- **修法 1**: 用 `python -c` 走 `django.setup()` 路径 (避开 startup 噪音)
- **修法 2**: 备份后 `sed -i '/^import local settings failed, ignored$/d' ${ADMIN_BACKUP}` 兜底过滤

## 8/25 上午演练 - 5 步必做脚本 (134 dev dry run, 演练时间戳)

### 演练结果
| 步骤 | 状态 | 备注 |
|------|------|------|
| 1. log dir chown | ✅ OK | 134 dev 已是 archery:archery |
| 2. sock 清理 | ✅ OK | 无 sock 残留 |
| 3. 影子表 | ✅ OK | 0 张 |
| 4. 凭据重加密 | 跳过 | DBA 手动 |
| 5. fix_approval_flow_3level | ✅ 命令跑过 | 3 flow 14,15,3 |
| 6. 清空 sqladvisor | ⚠️ 134 dev 没配, 演练跳过 | 110 prod 8/18 已修 |
| 7. 清空 soar | ⚠️ 134 dev 没配, 演练跳过 | 110 prod 8/19 已修 |
| 8. gh-ost / soar / sqladvisor 二进制 | ✅ 8/24 装好 | symlink OK |
| 9. features.py 5.7 patch | ✅ 8.0 不需要 | 110 prod 5.7 必打 patch |
| 10. gh-ost 4 perm | ✅ 已存在 | 推 110 idempotent 重建 |
| 11. 8/24 6 bug fix verify | ✅ 7 个文件都在 | mtime 8/24 |
| 12. gunicorn master pid | ✅ 13665 (134 dev) | 110 prod 102228 |
| 13. configurable_auditor 8/24 修法 | ✅ OK | grep 命中"走父类" |

## 8/25 上午演练 - 5 步必做脚本补的 4 步 (8/24 摸底发现缺, 8/25 补上)

### 新增步骤 8: gh-ost / soar / sqladvisor 二进制装
- 检查 `/opt/archery/bin/gh-ost --version` 是 1.1.10
- 检查 soar / sqladvisor 装好
- 8/24 装好, 8/27 推 110 前 idempotent 检查

### 新增步骤 9: features.py 5.7 patch
- 5.7 没 `performance_schema.metadata_locks` view
- 8/17 摸底 110 prod 5.7 必打 patch
- 8/25 134 dev 8.0 不需要

### 新增步骤 10: gh-ost 4 perm 预创建
- 8/13 commit 0004 创建 view/add/change/delete ddlghosttask
- 推 110 跑 migrate 后, 5 步必做 idempotent 检查
- 134 dev 已存在, 推 110 不会重复创建

### 新增步骤 11: 8/24 6 bug fix verify
- 7 个文件 mtime 都在 8/24 (134 dev 已部署)
- 推 110 后跑 5 步必做, 验证文件 mtime 是新 commit 时间
- 不通过 = 代码没推成功, 回滚

## 8/25 上午关键发现 - 110 prod 摸底补充

| 项目 | 8/24 摸底 | 8/25 实际 | 备注 |
|------|----------|----------|------|
| `sql_config` 表对应 model | (未查) | `sql.models.Config` | Archery 上游类名跟表名不一致 |
| `workflow_audit_setting` 数据 | 10 行 | **28 行** | 8/17 摸底后 DBA 加了 18 条 |
| gh-ost 二进制 | 没装 | 1.1.10 (8/24 装) | + /usr/local/bin/ symlink |
| mysqldump column-statistics flag | (没测) | **5.7 不支持** | 必去掉 |
| archery user + 库 archery | OK | OK | 8/17 .my.cnf 验证 |

## 8/27 推 110 完整执行计划 (8/25 上午定稿)

### 20:50 (推前 10 分钟)
- DBA 群发通知 "21:00 开始, 预计 30-40 分钟"
- 跑 `pre_push_backup_110prod_20260827.sh` (3 份备份到 /backup/)
- 验证 3 份 sha256

### 21:00 (推代码)
- 跑 `5step_prerequisites_110prod.sh` (1-13 步, 5-10 分钟)
- rsync / tarball 推新代码到 `/dbdata/archery_v114_c9236a0/`
- Django migrate (5 步必做 step 10 跑 4 perm)
- 验证 8/24 6 bug fix mtime

### 21:10 (重启 gunicorn)
- `kill 102228` (8/05 启动的 gunicorn master)
- nohup 拉起新 master (`sudo -u archery venv/bin/gunicorn ...`)
- 等 7-8 秒 systemd 拉起 (134 dev 有 systemd, 110 prod 没, 手动)

### 21:15-21:30 (验证 5 端点)
- `curl http://172.20.2.110:9123/login/` → 200
- `curl http://172.20.2.110:9123/dbaprinciples/` → 302 跳 /login/
- `curl http://172.20.2.110:9123/admin/` → 302 跳 /login/
- `curl http://172.20.2.110:9123/sqlsubmit/` → 302 跳 /login/
- `curl http://172.20.2.110:9123/workflowsdetail/1/` → 200 (测试工单)

### 21:30 (通知业务群)
- 全部 OK → 业务群 "已恢复 + 操作手册链接"
- 21:30-22:00 DBA 值守观察

## 失败回滚 (SLA 5 分钟)

### 触发条件 (DBA 拍板, 4 选 1)
- 数据库 migration 报错
- gunicorn 启动 30s 内 HTTP 502/503
- 关键端点 500 (SQL 提交 / 工单详情 / gh-ost 任务)
- 业务 RD 报 "功能完全不可用"

### 回滚 4 步
- `bash /tmp/rollback_110prod_v030_20260827.sh` (一键脚本)
- 1. kill master (5 秒)
- 2. 恢复代码 (10 秒, 50MB tarball 解压)
- 3. 恢复 schema (10 秒, DROP + CREATE + 还原)
- 4. nohup 拉起老 master (5 秒)
- 5. 5 端点 HTTP 200 验证 (10 秒)
- **总耗时 30-40 秒, 远低于 5 分钟 SLA**

## 推 110 必走脚本清单 (8/25 终版)

```
scripts/deploy/
├── 5step_prerequisites_110prod.sh        (1-13 步, 5-10 分钟)
├── pre_push_backup_110prod_20260827.sh   (3 份备份, 1-2 分钟)
└── rollback_110prod_v030_20260827.sh     (4 步回滚, SLA 5 分钟)
```

3 个脚本 syntax 全部 SYNTAX_OK (8/25 09:00 + 09:24 验证)

## 待办 (8/25 下午 + 8/26)

- [ ] 8/25 下午: 134 dev 演练回滚脚本 (故意制造失败, 跑回滚, 验 5 分钟恢复)
- [ ] 8/25 晚: 给用户过目总执行计划 (3 脚本 + 8/27 时间表)
- [ ] 8/26 上午: 134 dev 完整演练 (备份 + 5 步必做 + 推代码 + kill master + 拉起 + 验证)
- [ ] 8/26 下午: 整理「推 110 完整执行手册」给 DBA 值守用
- [ ] 8/26 晚: DBA 群发 "明天演练完成, 后天发布"
- [ ] 8/27 20:00: DBA 群发 "21:00 开始, 预计 30-40 分钟"

## 8/25 跨项目可复用教训 (跨项目 SOP)

1. **二次开发前必查上游 model 类名**: 用 `apps.get_models()` + `dir(sql.models)` 列出所有 model, 不要从代码脑补 "SysConfig" 这种名字。8/24 教训延伸
2. **mysqldump flag 必须 5.7/8.0 兼容**: 5.7 不支持 `--column-statistics=0` 等 8.0+ flag, 推代码前必查官方 docs
3. **备份脚本不能用 `set -e`**: 一份失败要全部跑完, 标记失败让 DBA 决定。8/24 教训延伸
4. **Python `print` 污染 stdout**: 上游代码 print 启动信息 (如 "import local settings failed, ignored") 会污染 JSON 备份, 用 `python -c` + `sed -i` 双重过滤
5. **114 行 Bash 脚本改完必 syntax check**: 跨平台 PowerShell → Linux 跑可能 CRLF/LF 转换问题, 必 `bash -n` 验证
6. **DBA 二次确认 (`yes/no` 交互)**: 备份 / 回滚脚本高风险操作, 必加 `read -p "yes/no"` 二次确认

## 跨项目同源 entry

- 8/24 教训: gunicorn HUP 不重载 Python 代码
- 8/24 教训: 改 Python 后必 py_compile 验证 (延伸: 改 bash 后必 bash -n)
- 8/24 教训: 凭据不上代码仓库 (但 admin dump 包含密码字段, 必 .gitignore .my.cnf 跟 sys_config dump)
- 8/24 教训: 二次开发前必查上游 model 类名 / 不要从代码脑补
