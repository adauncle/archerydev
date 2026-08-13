# D+1 待办：goinception 1.x 升级 (134 dev + 110 prod 同步)

## 业务背景

8/13 用户截图反馈 SQL 检测 400 Bad Request, 根因是 GoInception 1.x 上游 panic:
- `session_inception.go:4318 checkModifyColumn` 函数 slice bounds out of range `[:7]` capacity 6
- **触发条件** (drill 精确到 3 要素):
  1. **大表** (288310 行 / 134 MB, 触发阈值 100k 行 / 100 MB)
  2. **MODIFY COLUMN** (ADD/DROP/RENAME 不触发)
  3. **VARCHAR 类型** (BIGINT/INT/CHAR 不触发; 长度无关)
- **表现**: 每次新 connection 接收触发 SQL 都 panic, goinception 进程不死, Archery 收
  "Lost connection" 错误 (panic 副作用, 不是 MySQL 真挂)

完整现场: `docs/upstream/2026-08-13_goinception-panic-modify-column.md`

## 待办清单 (D+1 排期)

### 工单 1: 134 dev goinception 升级到 1.x 最新版

- **负责人**: mavis (升级 + smoke test) / mkq (排期确认)
- **投入**: 1-2 小时
- **步骤**:
  1. [ ] 备份当前 goinception 二进制 + 配置 (`/opt/goinception/`)
  2. [ ] 查 goinception 最新版 (GitHub releases: hanchuanchuan/goInception)
  3. [ ] 134 dev 升级 + 启动验证
  4. [ ] smoke test 5 case (确认大表 MODIFY VARCHAR 不再 panic)
  5. [ ] 跑 drill `scripts/_check_goinception_alive2.py` 全过
- **验收**: 5 case 0 panic, 进程稳定跑 24 小时
- **rollback**: 旧版二进制 + 配置 restore, `systemctl restart goinception`

### 工单 2: 110 prod goinception 同步升级

- **前置**: 工单 1 跑通 + 134 dev 稳定 1-2 周
- **负责人**: mavis (升级 + 110 smoke test) / mkq (110 排期审批)
- **投入**: 30 分钟
- **步骤**:
  1. [ ] 跟用户/团队确认 110 升级窗口 (DBA 业务低峰)
  2. [ ] 110 ssh 备份当前 goinception 容器/裸机
  3. [ ] 110 升级 (沿用 134 升级步骤, 适配容器/裸机)
  4. [ ] smoke test 5 case (134 dev 同样的 SQL 在 110 上测)
  5. [ ] 监控 24 小时无 panic
- **验收**: 110 prod 走大表 MODIFY VARCHAR 工单 0 报错
- **rollback**: 110 旧版秒回滚 (DBA 现场盯)

### 工单 3 (可选, 中长期): column_diff 端点扩展语法/兼容性

- **负责人**: mavis
- **投入**: 0.5 人天
- **目标**: 让字段 diff 端点能作为 SQL 检测的"关键路径"旁路, goinception panic 不影响字段 diff
- **范围**: 加 MySQL 语法校验 + 类型兼容性规则 (8.0/5.7 各一套)

## 风险

- **goinception 上游大版本可能引入新 bug**: 建议工单 1 跑 1-2 周再推工单 2
- **134 dev 上 goinception 是裸机 systemd, 110 prod 是容器 redis + 容器 goinception**: 升级步骤不同, 110 工单独立排
- **业务影响**: 大表 MODIFY VARCHAR 是常见变更, 升级前 DBA 应避免提交这类工单

## 关联

- 8/13 commit `01de7db` docs(upstream): 记录 GoInception panic bug 现场
- memory: "GoInception 1.x panic on MODIFY COLUMN (slice bounds out of range)"
- drill: `scripts/_check_goinception_alive.py` / `_check_goinception_alive2.py` (134 dev 验证用)
