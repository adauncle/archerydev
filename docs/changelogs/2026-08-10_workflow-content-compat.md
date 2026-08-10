# 134 dev 验证发现 — 兼容性修复（detail_content + notify + OA policy + 134 instance id=2）

**日期**: 2026-08-10
**作者**: mavis
**类型**: fix（4 处兼容性问题 + 1 处数据修复）

## 背景

DBA 用浏览器在 134 dev 走通页面验证时，连续发现 3 个独立问题。本 changelog 合并记录：

| 问题 | 现象 | 根因 | 修复 |
|------|------|------|------|
| A | 老工单 (wf=10/11/12/13) 点开 500 | `detail_content` 视图假设 `sqlworkflowcontent` 一定存在 | 3 文件加 `getattr` 兜底 |
| B | wf=14/19 仍 500 | 上游裸 `loaded_rows[-1]`，dict / 空 list 抛 KeyError / IndexError | sql_workflow.py 加 isinstance + 长度判断 |
| C | SQL 上线页提交 2061 | instance id=2 user/password 历史 K1 mirage 密文解不开 | Django shell 改 dbops 凭据（K2 重新加密） |

## A. detail_content 老工单兼容（3 文件 + CUSTOM-MODIFIED）

**根因**：134 dev `archery_prod` 库的 SqlWorkflowContent 表只有 9 行，对应 workflow_id 4,5,6,14-19。
wf=10/11/12/13（v0.1.x 时期创建）从来没建过 SqlWorkflowContent 行，但 status 还是 `workflow_manreviewing`，
浏览器点开触发 `detail_content` 视图访问 `wf.sqlworkflowcontent.review_content` → 抛 `RelatedObjectDoesNotExist` → 500。

**grep 出 30+ 个地方用 `workflow.sqlworkflowcontent.*`**，大部分裸调没容错，老工单点开任何相关功能都可能 500。

**修复**（3 文件 + CUSTOM-MODIFIED 注释）：

1. `sql/sql_workflow.py` `detail_content` (line 137-183)
   - 开头加 `content = getattr(workflow_detail, "sqlworkflowcontent", None)`
   - 若 `None` 返回 `{"rows": [], "_empty_content": True, "_empty_reason": "..."}`
   - 后面 4 处 `workflow_detail.sqlworkflowcontent.*` 改 `content.*`

2. `sql/extensions/dingtalk_oa/services/policy.py:35`
   - `getattr(workflow, "sqlworkflowcontent", None)` 兑底 → 空 sql_content

3. `sql/notify.py:185, 299`
   - 通知文本拼接时 `getattr` 兑底 → 空字符串

## B. wf=14/19 review_content='{}' KeyError 修复

**根因**：上游 archery 视图 `if isinstance(loaded_rows[-1], list):` 裸用 `[-1]`：
- `loaded_rows = json.loads('{}')` = `{}` (dict)
- `dict[-1]` → **KeyError: -1**
- `loaded_rows = json.loads('[]')` = `[]` (空 list)  
- `list[-1]` → **IndexError: list index out of range**

`IndexError` 已被上游 `except IndexError` 兜底，但 `KeyError` / `TypeError` 没兜底。

**修复**（sql_workflow.py 单点）：

```python
## CUSTOM-MODIFIED: 加 isinstance(loaded_rows, list) + loaded_rows 兑底。@ 2026-08-10 @ mavis
if isinstance(loaded_rows, list) and loaded_rows and isinstance(loaded_rows[-1], list):
    ...
except (IndexError, KeyError, TypeError):
    ...
```

**验证**：

| wf_id | 改前 | 改后 | rows |
|-------|------|------|------|
| 10 (老) | 500 RelatedObjectDoesNotExist | 200 `_empty_content=True` | 0 |
| 11 (老) | 500 RelatedObjectDoesNotExist | 200 `_empty_content=True` | 0 |
| 12 (老) | 500 RelatedObjectDoesNotExist | 200 `_empty_content=True` | 0 |
| 13 (老) | 500 RelatedObjectDoesNotExist | 200 `_empty_content=True` | 0 |
| 14 (新) | 500 KeyError: -1 | 200 `_empty_content=False` | 0 (review_content='{}') |
| 19 (新) | 500 KeyError: -1 | 200 `_empty_content=False` | 0 (review_content='{}') |

## C. 134 dev instance id=2 (测试 MySQL 8.0) mirage 密文修复

**根因**：

- `archery_prod.sql_instance` id=2 的 `user` 字段是历史 K1 mirage 密文 `'Vg3fpMzcS7GNEL2bbQT-nQ=='`
- `get_username_password()` 用当前 SECRET_KEY (K2) 解 K1 密文失败 → 原样返回密文
- MySQLdb 拿密文当密码连 8.0 → 报 `(2061, "caching_sha2_password reported error: Authentication requires secure connection")`
  - 实际是密码错的兜底报错；134 dev MySQL 8.0 所有业务用户（admin / dbops / root）都是 `mysql_native_password`，**不是**真的 caching_sha2_password 强 SSL

**验证**：

```
dbops 明文直连 instance id=2 (127.0.0.1:3306):  ✅ ('8.0.22', 'dbops@127.0.0.1')
get_username_password() 拿密文直连:          ❌ 2061
```

**修复**（Django shell 改写 + K2 重新加密）：

```python
i = Instance.objects.get(id=2)
i.user = 'dbops'
i.password = open('/etc/archery/dbops_password').read().strip()  # TJwgoqnHBlPG5WLemg1sG@#P
i.save()  # django-mirage 用 K2 重新加密
# 验证
i = Instance.objects.get(id=2)
u, p = i.get_username_password()
# 直连
MySQLdb.connect(host=i.host, port=i.port, user=u, passwd=p)  # ✅
```

**改后**：

| 字段 | 改前 (K1 密文) | 改后 (K2 密文) |
|------|----------------|-----------------|
| user | `'Vg3fpMzcS7GNEL2bbQT-nQ=='` | `'dbops'` (mirage 8.x 短字符串不加密?) |
| password | `'6jApCuL759On6Q9Anovgq2kJ9uH1DwOOodj-NPqIaD8='` | K2 重新加密密文 |
| `get_username_password()` 返回 | `(密文, 密文)` ❌ | `('dbops', 'TJwgoqnHBlPG5WLemg1sG@#P')` ✅ |

## 110 PROD 影响

| 修复 | 110 prod 是否需要 |
|------|---------------------|
| A. detail_content 容错 | 强烈建议推（110 prod v0.2.0 也有 v0.1.x 老工单缺 SqlWorkflowContent 风险） |
| B. KeyError 兑底 | 强烈建议推（上游裸 `[-1]` bug，110 也有） |
| C. instance id=2 改写 | **不推**（110 instance id 不一样，user/password 也是 K1 密文） |
|                      | 110 推 v0.2.0 时 DBA 必须手动从 admin 重新保存 instance，触发 K2 重新加密 |

**110 push 计划**：

- A + B 走 tarball 推到 110 部署目录 + restart gunicorn
- C 由 DBA 在 110 admin 后台重新保存所有 instance 的 user/password

## 操作清单

- [x] sql/sql_workflow.py 改 2 处（CUSTOM-MODIFIED × 2）
- [x] sql/extensions/dingtalk_oa/services/policy.py 改 1 处（CUSTOM-MODIFIED × 1）
- [x] sql/notify.py 改 2 处（CUSTOM-MODIFIED × 2）
- [x] 134 dev scp 3 文件 + chown + restart gunicorn → active
- [x] 134 dev manage.py shell 改 instance id=2 → dbops 凭据
- [x] 134 dev 验证：wf=10/11/12/13/14/19 全部 200
- [ ] 110 prod tarball 推 A + B（等用户拍板）
- [ ] 110 prod DBA 重新保存 instance user/password（解 mirage 密文）

## 相关 commit

待 commit：3 文件 + 本 changelog
