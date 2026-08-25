# 2026-08-25 134 dev 回滚演练报告 + 事故修复

## 8/25 上午: 5 步必做 + 备份脚本演练 (commit `7c2003c` 已 push)

3 份备份脚本 110 prod 演练全部通过 (3 份 OK + JSON 99 条记录校验通过)
详情: docs/changelogs/2026-08-25_110prod-pre-push-drill.md

## 8/25 下午 13:00-13:50: 134 dev 回滚演练 (DRY_RUN=1 旧版)

### 演练流程
1. 跑 3 份备份 (134 dev dry run, 演练时间戳 20260825_rollback_drill)
2. 故意制造失败: 改 /opt/archery/prod/sql/views.py 引入 syntax error (追加 4 行)
3. 跑回滚脚本 DRY_RUN=1 (旧版只 skip kill master, 没 skip mv + tar -xzf)
4. 验证 views.py md5 跟原始一致 ✅
5. HTTP 200 验证 ✅
6. 回滚脚本总耗时 1.4 秒 (SLA 5 分钟 = 300 秒)

### 演练真实事故 (8/25 重大发现)

**症状**: 演练后 134 dev `/opt/archery/prod/venv` 目录消失, 但 gunicorn 13665 还在跑

**根因**:
- 旧版回滚脚本 DRY_RUN=1 只 skip 了 `kill master` 和 `nohup 拉起` 两步
- 但 `mv ${PROD_PATH} ${PROD_PATH}.rollback_$(date +%H%M%S).bak` 这一步**真改了文件系统**
- mv 后, `/opt/archery/prod/` 变成新解压出来的目录, **但 venv 目录被 mv 走了** (备份 tarball --exclude='venv')
- gunicorn 13665 进程的 cwd 跟着自动跟到 `/opt/archery/prod.rollback_093942.bak/` (linux 进程 cwd 跟踪 mv)
- gunicorn 启动时 venv 已 import 完, worker 进程不依赖 venv 目录, 所以**还能响应 200** (侥幸)
- 但**任何 reload 都会失败** (找不到 venv/bin/python3.11)

**影响**:
- 134 dev 业务没中断 (gunicorn 还在跑)
- 但 134 dev 处于"易碎"状态, 一旦 gunicorn worker 异常需要重启就 crash
- 134 dev 真实的演练备份目录 `/opt/archery/prod.rollback_093942.bak` (790MB) 留着, 占磁盘

**修复** (8/25 13:46 完成):
1. `cp -a /opt/archery/prod.rollback_093942.bak/venv /opt/archery/prod/venv` (2.5 秒, 652MB)
2. `chown -R archery:archery /opt/archery/prod/venv`
3. 验证 `/opt/archery/prod/venv/bin/python3.11` 软链 OK
4. 验证 venv python ast.parse OK (PARSE_OK)
5. 验证 HTTP /login/ 200
6. **保留** `/opt/archery/prod.rollback_093942.bak` (作为保险)

### 8/25 教训 (跨项目可复用, 高优先级)

1. **【致命教训】演练脚本要 DRY_RUN=1 模式 + 跳过所有破坏性操作**:
   - 不能只 skip `kill master`, 还要 skip `mv` / `tar -xzf` / `DROP TABLE` 等
   - 演练模式只验证逻辑 (前置检查 + 备份完整性), **不真改文件系统 / 数据库**
2. **【备份脚本 mv 设计的隐患】**: 备份脚本用 `mv` 移动当前目录再解压新的, mv 期间 gunicorn cwd 跟踪会跟着走, venv 路径变化造成隐患
3. **【演练模式设计原则】**: DRY_RUN 模式 = 演练所有"判断 + 验证"逻辑, 跳过所有"破坏性写入"操作
4. **【gunicorn 启动后不依赖 venv】**: gunicorn worker 进程启动时 import 完所有模块, 之后不依赖 venv 目录存在 (venv 主要是包安装路径, 启动时 load)
5. **【演练后必恢复现场】**: 演练脚本演练完应该自动恢复原始状态, 不要留"易碎"环境

## 8/25 下午 13:50-14:10: 134 dev 回滚演练 v2 (DRY_RUN=1 新版, 不真改文件)

### 演练结果

| 阶段 | 状态 | 备注 |
|------|------|------|
| 1. scp 修好的脚本 | ✅ OK | syntax OK |
| 2. 跑 3 份备份 (演练时间戳 20260825_dryrun_v2) | ✅ OK | code + admin OK, schema 134 dev 限制 |
| 3. 故意制造失败 (views.py syntax error) | ✅ OK | 4 行追加 |
| 4. 跑回滚 DRY_RUN=1 (新版, 跳过 mv + tar -xzf) | ✅ OK | 2.4 秒, SLA 余 298 秒 |
| 5. 验证 views.py 没真改 | ✅ OK | md5 跟 broken 一致 (DRY_RUN=1 验证通过) |
| 6. HTTP 200 验证 | ✅ OK | gunicorn 不受影响 |
| 7. 恢复 views.py 到原始 | ✅ OK | md5 跟原始一致 |
| 8. 清理 | ✅ OK | |

### 演练脚本改进 (回滚脚本 commit)

DRY_RUN=1 模式现在跳过:
- `kill master` (步骤 1) — 防止真杀 gunicorn
- `mv ${PROD_PATH}` + `tar -xzf` (步骤 2) — **8/25 教训, 防止演练时破坏文件系统**
- `mysql DROP DATABASE + CREATE + 还原` (步骤 3) — 防止演练时破坏数据库
- `nohup 拉起` (步骤 4) — 防止演练时拉起新 gunicorn

DRY_RUN=1 模式只跑:
- 前置检查 (3 份备份存在)
- 备份完整性 (tarball valid, mysqldump header)
- 二次确认 (DBA yes/no)
- 脚本总耗时演练 (验证逻辑跑得通)

## 8/25 跨项目可复用教训 (更新 8/24 教训)

### 8/24 教训回顾
- 改 Python 后必 py_compile 验证
- 改 Bash 后必 bash -n syntax check
- 凭据不上代码仓库
- 二次开发前必查上游 model 类名

### 8/25 新增教训
- **【新】演练脚本必加 DRY_RUN=1 模式, 跳过所有破坏性操作** (mv / tar -xzf / DROP / nohup)
- **【新】mv 代码目录会破坏 gunicorn cwd 跟踪**, 备份脚本设计要避免 mv, 用 cp -a 复制代替
- **【新】gunicorn 启动后不依赖 venv 目录** (启动时已 import 完), 但 reload 会失败
- **【新】演练后必自动恢复现场** (或者保留演练备份), 不要留易碎环境
- **【新】my.cnf 凭据不能在命令行明文**, 必用 `--defaults-file` 走 .my.cnf 文件
- **【新】Archery settings.py print "import local settings failed, ignored" 污染 stdout**, 备份脚本后必 sed 过滤
- **【新】mysqldump 5.7/8.0 flag 兼容** (--column-statistics=0 仅 8.0 支持)

## 8/25 关键 git commit

- `7c2003c` (上午) chore(deploy): 5 步必做补到 13 步 + 备份脚本修 4 bug + 演练报告
- `TBD` (下午) chore(deploy): 8/25 回滚演练 v2 修法 + DRY_RUN=1 跳过 mv + 演练报告

## 8/27 推 110 完整执行清单

### 20:50 推前 10 分钟
- DBA 群发 "21:00 开始, 预计 30-40 分钟"
- 跑 `pre_push_backup_110prod_20260827.sh` (3 份备份到 /backup/)
- 验证 3 份 sha256 + JSON 校验通过

### 21:00 推代码
- 跑 `5step_prerequisites_110prod.sh` (1-13 步, 5-10 分钟)
- rsync / tarball 推新代码到 `/dbdata/archery_v114_c9236a0/`
- Django migrate (5 步必做 step 10 跑 4 perm)
- 验证 8/24 6 bug fix mtime

### 21:10 重启 gunicorn
- `kill 102228` (8/05 启动的 gunicorn master)
- nohup 拉起新 master (用跟之前一样的命令)
- 等 7-8 秒 systemd 拉起 (134 dev 有 systemd, 110 prod 没, 手动 nohup)

### 21:15-21:30 验证 5 端点
- `curl http://172.20.2.110:9123/login/` → 200
- `curl http://172.20.2.110:9123/dbaprinciples/` → 302 跳 /login/
- `curl http://172.20.2.110:9123/admin/` → 302 跳 /login/
- `curl http://172.20.2.110:9123/sqlsubmit/` → 302 跳 /login/
- `curl http://172.20.2.110:9123/workflowsdetail/1/` → 200 (测试工单)

### 21:30 通知业务群
- 全部 OK → 业务群 "已恢复 + 操作手册链接"
- 21:30-22:00 DBA 值守观察

## 失败回滚 (SLA 5 分钟)

### 触发条件 (DBA 拍板, 4 选 1)
- 数据库 migration 报错
- gunicorn 启动 30s 内 HTTP 502/503
- 关键端点 500 (SQL 提交 / 工单详情 / gh-ost 任务)
- 业务 RD 报 "功能完全不可用"

### 回滚 4 步 (真实跑, 不用 DRY_RUN)
- `bash /tmp/rollback_110prod_v030_20260827.sh` (一键脚本)
- 1. kill master (5 秒)
- 2. mv 当前目录 + tar -xzf 恢复 (10 秒, 50MB tarball 解压)
- 3. DROP + CREATE + 还原 schema (10 秒, 134 dev 演练 2.4 秒跳过 schema)
- 4. nohup 拉起老 master (5 秒)
- 5. 5 端点 HTTP 200 验证 (10 秒)
- **总耗时 30-40 秒, 远低于 5 分钟 SLA**

## 待办 (8/25 下午 + 8/26)

- [x] 8/25 下午: 134 dev 演练回滚脚本 (2 次, 含 1 次事故修复)
- [ ] 8/25 晚 18:00: 给用户过目 3 脚本 + 8/27 时间表
- [ ] 8/26 上午: 134 dev 完整演练 (备份 + 5 步必做 + 推代码 + kill master + 拉起 + 验证)
- [ ] 8/26 下午: 整理推 110 完整执行手册给 DBA 值守用
- [ ] 8/26 晚: DBA 群发 明天演练完成, 后天发布
- [ ] 8/27 20:00: DBA 群发 21:00 开始, 预计 30-40 分钟
- [ ] 8/27 20:50: 3 份备份
- [ ] 8/27 21:00: 部署新代码 + migration
- [ ] 8/27 21:10: 重启 gunicorn
- [ ] 8/27 21:15-21:30: HTTP 验证
- [ ] 8/27 21:30: 通知业务群
- [ ] 8/27 21:30-22:00: DBA 值守观察
