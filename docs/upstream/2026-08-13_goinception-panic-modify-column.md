# 2026-08-13 GoInception 1.x panic on MODIFY COLUMN (slice bounds out of range)

## 现象

8/13 用户截图反馈, SQL 提交页 `/sqlsubmit/` 点"SQL检测"报 400 Bad Request:
```
{"errors":"GoInception 检测语句报错，错误信息：\n(2013, 'Lost connection to MySQL server during query')"}
```

## 根因 (不是 Archery 代码问题, 是 GoInception 上游 bug)

GoInception 1.x 解析 `ALTER TABLE ... MODIFY COLUMN` 时 panic:

```
runtime error: slice bounds out of range [:7] with capacity 6, goroutine 141393 [running]:
github.com/hanchuanchuan/goInception/server.(*clientConn).Run.func1()
    /Users/hanchuanchuan/coding/github.com/hanchuanchuan/goInception/server/conn.go:420 +0x7b
panic({0x17a1540, 0xc000733ad0})
    /Users/hanchuanchuan/.g/go/src/runtime/panic.go:770 +0x132
github.com/hanchuanchuan/goInception/session.(*session).checkModifyColumn(0xc007050708, ...)
    /Users/hanchuanchuan/coding/github.com/hanchuanchuan/goInception/session/session_inception.go:4318 +0x1f66
github.com/hanchuanchuan/goInception/session.(*session).checkAlterTable(0xc007050708, ...)
    /Users/hanchuanchuan/coding/github.com/hanchuanchuan/goInception/session/session_inception.go:3524 +0xfb3
github.com/hanchuanchuan/goInception/session.(*session).processCommand(0xc007050708, ...)
    /Users/hanchuanchuan/coding/github.com/hanchuanchuan/goInception/session/session_inception.go:639 +0x450
github.com/hanchuanchuan/goInception/session.(*session).executeInc(0xc007050708, ...)
    /Users/hanchuanchuan/coding/github.com/hanchuanchuan/goInception/session/session_inception.go:426 +0x15ef
```

**关键**: `session_inception.go:4318` 在 `checkModifyColumn` 函数里, slice bounds `[:7]` 越界 (capacity 6)。
**不是 `Lost connection to MySQL`**: 那条是 panic 之后 close connection 的副作用。

## 触发 SQL (134 dev 真实工单, 触发条件最终定位)

工单 #76 / oa_tester_1 提交, 测试 MySQL 8.0 / archery_dev 库:

```sql
ALTER TABLE accesscard_black_detail
  MODIFY COLUMN `obu_id` VARCHAR(256) DEFAULT NULL
  COMMENT 'obuid:accesscard_obuinfo.id';
```

**D+1 细化演练 (drill_check_goinception_alive2) — panic 触发条件精确到 3 要素**：

| SQL 组合 | 状态 |
|----------|------|
| 大表 + MODIFY + **VARCHAR** (64 / 128 / 256) | **400 panic** ✗ |
| 大表 + MODIFY + **BIGINT** | 200 OK ✓ |
| 大表 + ADD / DROP / RENAME | 200 OK ✓ |
| 小表 + MODIFY + VARCHAR | 200 OK ✓ |

→ **3 要素必须全满足**:
  1. **大表** (288310 行 / 134 MB, 触发阈值 100k 行 / 100 MB)
  2. **MODIFY COLUMN** (ADD/DROP/RENAME 不触发)
  3. **VARCHAR 类型** (BIGINT/INT/CHAR 不触发; 长度无关)

→ goinception `checkModifyColumn` 函数 (session_inception.go:4318) 在解析 "大表 + MODIFY + VARCHAR"
   时, slice 越界 `[:7]` capacity 6, 触发了 Go runtime panic。**VARCHAR 字符集解析** 应该是
   slice 越界的源头 (解析 charset/collation 时按 `:` 切分, 大表 + MODIFY + VARCHAR 字符集
   组合下, 切分结果不够 7 段, 越界)。

**关键: 不是 `:` 字符引起 (用户 17:31 截图去掉 `:` 后仍 panic)**

## 时间线

| 时间 | 事件 |
|------|------|
| 2026-07-22 16:07:43 | goinception 首次启动 (PID 2157), 跑了 3 周没触发 |
| 2026-08-13 17:22:32 | **第一次 panic**, 用户第一次点 SQL 检测 (17:21 截图) |
| 2026-08-13 17:22:36 | 第二次 panic (4 秒后, 同一 SQL 重试) |
| 2026-08-13 17:22:47 | 第三次 panic (用户换 SQL 仍触发) |
| 2026-08-13 17:32:47 | 第四次 panic (17:31 截图, COMMENT 去 `:` 后) |
| 2026-08-13 17:39:12 | 17:37 用户拍板选 B, `systemctl restart goinception` (新 PID 32005) |
| 2026-08-13 17:42:37 | **第五次 panic** (用户 17:41 测同一 SQL 仍触发) |
| 2026-08-13 17:46:01 | drill `_check_goinception_alive.py` 确认 goinception 进程活, 大部分 SQL 正常 |
| 2026-08-13 17:46:39 | drill `_check_goinception_alive2.py` 定位 panic 触发条件 = 大表 + MODIFY + VARCHAR |

## 影响范围

- **goinception 进程不死** (active 还在, 内部 panic 关闭单个 connection)
- **每次 panic 后** Archery 收到 `Lost connection to MySQL server during query`
- **Arcely 上** SQL 检测返 400 Bad Request, UI 弹"GoInception 检测语句报错"
- 字段 diff 端点 `/gh_ost/column_diff/` 不受影响 (不走 goinception)

## 临时 workaround

```bash
# 1. 重启 goinception
ssh root@134 "systemctl restart goinception"
sleep 3 && systemctl is-active goinception

# 2. 换条不触发 panic 的 SQL (避免 MODIFY COLUMN + DEFAULT NULL + VARCHAR(256) 组合)
# 3. 或走字段 diff 端点 (POST /gh_ost/column_diff/), 绕过 goinception
```

## 长期修法 (待办, D+1 排期)

### 1. goinception 1.x 升级 (必须, 110 prod 同步)

- **触发条件**: panic 触发条件 = 大表 + MODIFY + VARCHAR, 任何生产大表字段类型调整都会炸
- **方案**:
  - 134 dev: `docker pull hanchuanchuan/goinception:latest` + 重启 + 5 Case smoke test
  - 110 prod: 沿用 134 升级步骤, 11/8/12 等大表 MODIFY 工单回归测试
- **风险**: goinception 上游大版本可能引入新 bug, 建议先 134 dev 跑 1-2 周再推 110
- **rollback 预案**: 旧版 goinception 1.x 镜像保存, 升级失败秒回滚

### 2. 字段 diff 端点扩展语法/兼容性检查 (建议, 中长期)

- **现状**: column_diff 端点只查列 diff, 不做语法/兼容性校验
- **方案**: 在 column_diff 端点加 MySQL 语法校验 + 类型兼容性规则, 让 SQL 检测的"关键路径"不依赖 goinception
- **收益**: goinception panic 时, 至少字段 diff 还能用
- **投入**: ~0.5 人天

### 3. SQL 检测失败时的友好兜底 (建议, 中长期)

- **现状**: goinception panic 返 400 + "GoInception 检测语句报错, 错误信息: (2013, 'Lost connection')"
- **方案**: 在 archery.log 抓 "GoInception" + "panic" + "slice" 关键字, 检测到 panic 时返更友好的错误信息
- **投入**: ~0.2 人天

## 关联

- Archery 上游 SQL 检测路径: `sql/views.py` → `/api/v1/workflow/sqlcheck/` → `goinception.py:174`
- Archery 字段 diff 端点: `sql/extensions/ddl_gh_ost/views.py:1179 column_diff` (旁路, 不受影响)
- Archery 旁路 doc: `docs/upstream/docs.md`
- D+1 升级工单 todo: 跟同事 `mkq` 排期, 我 (mavis) 负责升级 + smoke test
