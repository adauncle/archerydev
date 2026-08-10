# 134 dev 验证发现 — SQL 检测 mirage 密文修复（sql_config + instance id=1）

**日期**: 2026-08-10
**作者**: mavis
**类型**: fix（mirage 密文兼容，同 2026-08-10 instance id=2 那次问题）

## 背景

DBA 浏览器走 SQL 上线页 → 选 instance `archery` (id=1) + `测试 MySQL 8.0` (id=2) + 输入 SQL → 点
"检测中..." 按钮 → 报 `GoInception检测语句报错... 'invalid literal for int() with base 10: 'OizTMdz92a1b_D6-Qot5Jw==''`，
POST `/api/v1/workflow/sqlcheck/` 返回 400 Bad Request。

## 根因（两层叠加）

### 第一层：sql_config 表 inception_remote_backup_* 4 个字段是 K1 mirage 密文

```
goinception.py:55  backup_port = int(archer_config.get("inception_remote_backup_port", 3306))
```

134 dev `sql_config` 表当前 4 个字段值（**全部 K1 密文**，K2 SECRET_KEY 解不开）：

| item | DB 密文 | 真实明文（应该是） |
|------|---------|-------------------|
| `inception_remote_backup_host` | `FWVnkF9EFJYnrD1t1R5UAA==` | `127.0.0.1` |
| `inception_remote_backup_port` | `Niocj7sEVLmWchB006r3FQ==` | `3306` |
| `inception_remote_backup_user` | `9kw2JyqOCUOERr58JL3SUw==` | `dbops` |
| `inception_remote_backup_password` | `FWVnkF9EFJYnrD1t1R5UAA==` | `TJwgoqnHBlPG5WLemg1sG@#P` |

`int('Niocj7sEVLmWchB006r3FQ==')` → `ValueError: invalid literal for int() with base 10`，
被 `ExecuteCheck.post` (sql_api/api_workflow.py:73) 兜底成 `serializers.ValidationError({"errors": f"{e}"})` → 400。

### 第二层：instance id=1 user/password 也是 K1 mirage 密文

第一层修了之后，`get_backup_connection()` ✅ 通。但 goinception 接着要 `remote_instance_conn(instance)` 拿
`(host, port, user, password)` 拼 SQL：
```
sql = f"""/*--user='{user}';--password='{password}';--host='{host}';--port={port};--check=1;..."""
```

instance id=1 (`archery` master @ 172.20.2.134:3306) 的 user 字段 `pn-OvgZNQs-v8A0VEmL_AA==` (K1 密文)
被当 username 拼进去，goinception 拿 `pn-OvgZNQs-v8A0VEmL_AA==@172.20.2.134` 连 MySQL → 1045 Access denied。

## 修复

### 1. sql_config 4 个字段改明文（ORM save，K2 重新加密）

```python
from sql.models import Config
fixes = {
    'inception_remote_backup_host': '127.0.0.1',
    'inception_remote_backup_port': '3306',
    'inception_remote_backup_user': 'dbops',
    'inception_remote_backup_password': 'TJwgoqnHBlPG5WLemg1sG@#P',
}
for item, new_value in fixes.items():
    c = Config.objects.get(item=item)
    c.value = new_value
    c.save()  # mirage K2 重新加密
```

**验证**：
- `SysConfig.get('inception_remote_backup_port')` = `'3306'` ✅
- `GoInceptionEngine.get_backup_connection()` ✅ 连上 127.0.0.1:3306

### 2. instance id=1 (archery master) 改 dbops 凭据

```python
i = Instance.objects.get(id=1)
i.user = 'dbops'
i.password = 'TJwgoqnHBlPG5WLemg1sG@#P'
i.save()
```

**验证**：`get_username_password()` 返回 `('dbops', 'TJwgoqnHBlPG5WLemg1sG@#P')`，MySQLdb 直连 172.20.2.134:3306 8.0.22 ✅

## 完整链路验证

`/api/v1/workflow/sqlcheck/` POST 测试 SQL `ALTER TABLE accesscard_account ADD COLUMN smoke_v1_col VARCHAR(50) DEFAULT NULL`：

| instance_id | 改前 | 改后 |
|-------------|------|------|
| 1 (archery master) | 400 Bad Request (int 错或 1045) | **200 + error_count=0 + Audit Completed** ✅ |
| 2 (测试 MySQL 8.0) | 200 但 error_count=1 (1045 拿密文当 username) | **200 + error_count=0 + Audit Completed** ✅ |

## 备注：未改的 sql_config 密文

`sql_config` 表里还有 **1 个 K1 密文 key**：`ding_to_person` = `TUf0VdGLGbMwo9wX2Wqwqg==`
（钉钉 OA 1对1 通知相关，v0.2.0 部署时配置的）。

**这次没改** —— 因为：
1. 用户没要求 OA 链路修复
2. v0.2.1~v0.2.3 OA 还在 DRAFT（待用户去 oa.dingtalk.com 建模板）
3. 等 OA 真上线时再统一处理

如果需要现在就修，manage.py shell 跑：
```python
from sql.models import Config
c = Config.objects.get(item='ding_to_person')
c.value = ''  # 清空，等 v0.2.1 OA 模板建好后再配
c.save()
```

## 134 dev 操作

- [x] manage.py shell 改 4 个 inception_remote_backup_* + instance id=1
- [x] 验证：2 个 instance 走 sqlcheck 全部 200 + error_count=0
- [ ] 写 changelog（本文件）

## 110 PROD 影响

| 修复 | 推 110？ |
|------|----------|
| instance id=1 改 dbops 凭据 | ❌ **不推**（110 prod DBA 必须手动从 admin 重新保存所有 instance） |
| sql_config 4 个 key 改明文 | ❌ **不推**（110 prod 配置是当时部署时设的，可能就是明文 / 可能是 K1 密文，要看 110 实际值） |

**110 推 v0.3.0 时**：
- 由 DBA 在 110 admin 重新保存所有 instance 的 user/password，触发 K2 重新加密
- DBA 在 110 admin 重新保存所有 SysConfig（"系统配置"页），触发 K2 重新加密

## 相关 commit

无 commit（数据修复不上 git）

## 相关 changelog

- `2026-08-10_workflow-content-compat.md` — instance id=2 改 dbops 凭据（同类问题）
- `2026-08-10_dev-sync-static-fix.md` — 134 dev sync 漏 common/static/ 修复
- `2026-08-10_detail-view-audit-missing.md` — detail 视图无审批流兜底
- `2026-08-10_detail-html-bootstrap-table-autoinit.md` — detail.html data-toggle 自动初始化冲突
- `2026-08-10_workflow-content-compat.md` — detail_content rows dict 兼容
- **本文件** — sql_config inception_remote_backup_* + instance id=1 改 dbops
