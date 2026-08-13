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

## 触发 SQL (134 dev 真实工单)

工单 #76 / oa_tester_1 提交, 测试 MySQL 8.0 / archery_dev 库:

```sql
ALTER TABLE accesscard_black_detail
  MODIFY COLUMN `obu_id` VARCHAR(256) DEFAULT NULL
  COMMENT 'obuid:accesscard_obuinfo.id';
```

**复现尝试 2** (去掉 COMMENT 里的 `:` 仍然 panic):
```sql
ALTER TABLE accesscard_black_detail
  MODIFY COLUMN `obu_id` VARCHAR(256) DEFAULT NULL
  COMMENT 'obuidaccesscard_obuinfo.id';
```

→ 说明 bug **不是** `:` 切分引起, 是 `checkModifyColumn` 函数本身的 fixed bug, 跟
   `MODIFY COLUMN + DEFAULT NULL + VARCHAR(256)` 组合有关 (待确认精确触发条件)

## 时间线

| 时间 | 事件 |
|------|------|
| 2026-07-22 16:07:43 | goinception 首次启动 (PID 2157), 跑了 3 周没触发 |
| 2026-08-13 17:22:32 | **第一次 panic**, 用户第一次点 SQL 检测 (17:21 截图) |
| 2026-08-13 17:22:36 | 第二次 panic (4 秒后, 同一 SQL 重试) |
| 2026-08-13 17:22:47 | 第三次 panic (用户换 SQL 仍触发) |
| 2026-08-13 17:32:47 | 第四次 panic (17:31 截图, COMMENT 去 `:` 后) |
| 2026-08-13 17:39:12 | 17:37 用户拍板选 B, `systemctl restart goinception` |
| 2026-08-13 17:39:12 | 新进程 PID 32005 started, panic 恢复 |

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

## 长期修法 (待办)

- [ ] **D+1 排 goinception 升级工单**: 1.x → 1.x 最新版, 看 panic 是否修了
- [ ] **110 PROD 同步升级**: 110 goinception 也在 1.x 旧版, 不升级下次同样会炸
- [ ] **可选: 自己写个 goinception 旁路检测**: column_diff 端点扩展, 包含语法/兼容性检查,
        避免关键 SQL 检测链路被 goinception 单点故障卡住

## 关联

- Archery 上游 SQL 检测路径: `sql/views.py` → `/api/v1/workflow/sqlcheck/` → `goinception.py:174`
- Archery 字段 diff 端点: `sql/extensions/ddl_gh_ost/views.py:1179 column_diff` (旁路, 不受影响)
- Archery 旁路 doc: `docs/upstream/docs.md`
