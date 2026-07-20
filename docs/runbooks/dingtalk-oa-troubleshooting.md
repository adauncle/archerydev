# 钉钉 OA 故障排查手册

> **目标读者**：DBA / 运维 / 二次开发同事
> **关联设计**：[钉钉 OA v0.7](../designs/2026-07-20_dingtalk-oa-workflow.md)
> **关联代码**：`sql/extensions/dingtalk_oa/`

本文档按"症状 → 排查 → 修复"组织。**先看症状**找到对应章节。

---

## 目录

- [1. 服务起不来 / 启动报错](#1-服务起不来--启动报错)
- [2. 钉钉回调 4xx 错误码](#2-钉钉回调-4xx-错误码)
- [3. 钉钉 OA 启动失败（fallback）](#3-钉钉-oa-启动失败fallback)
- [4. 回调延迟/丢失（对账任务）](#4-回调延迟丢失对账任务)
- [5. 误封禁 IP / 解封](#5-误封禁-ip--解封)
- [6. 密钥轮换](#6-密钥轮换)
- [7. 钉钉 API 限流（429）](#7-钉钉-api-限流429)
- [8. 对账任务没跑](#8-对账任务没跑)
- [9. UI 上看不到「重试钉钉 OA」按钮](#9-ui-上看不到重试钉钉-oa-按钮)
- [10. 工单状态卡住](#10-工单状态卡住)

---

## 0. 工具与日志速查

| 工具 | 路径 / 命令 | 说明 |
|------|------------|------|
| 钉钉回调日志 | `grep dingtalk logs/archery.log` | 应用日志 |
| 回调事件流水 | Django admin → 钉钉 OA 事件流水 | `event_type / event_id / processed / error` |
| 外部 OA 关联 | Django admin → 工单外部 OA 关联 | `external_status / oa_failure_reason` |
| 工单降级原因 | Django admin → SQL 工单 → `audit_fallback_reason` | 字段非空即降级过 |
| Cache 调试 | `python manage.py shell -c "from django.core.cache import cache; cache.keys('dingtalk_*')"` | Redis 里的 `dingtalk_*` keys |
| 对账任务是否在跑 | Django admin → django_q → Schedule | 找 `dingtalk_oa_reconcile` |
| 钉钉后台 | <https://oa.dingtalk.com> → 应用 → 事件订阅 | 回调 URL / 模板编码 |

---

## 1. 服务起不来 / 启动报错

### 1.1 `ModuleNotFoundError: No module named 'Crypto'`

**症状**：`python manage.py runserver` 启动时报 `Crypto` 找不到。

**排查**：

```bash
pip show pycryptodome
```

**修复**：`pycryptodome` 必须装（v0.7 §10.5.1 依赖）：

```bash
pip install pycryptodome==3.19.1
# 或在 requirements.txt 已锁版本的情况下：
pip install -r requirements.txt
```

### 1.2 `django.core.exceptions.ImproperlyConfigured: ... DingtalkOaConfig`

**症状**：开启 `CUSTOM_DINGTALK_OA_ENABLED=True` 但 `INSTALLED_APPS` 找不到 `DingtalkOaConfig`。

**原因**：`archery/urls.py` 没 include `sql.extensions.dingtalk_oa.urls`，**或** `.env` 改了但 gunicorn 没重启。

**修复**：

1. 确认 `archery/urls.py` 末尾有（参考 `sql/extensions/dingtalk_oa/urls.py` 顶部注释）：

    ```python
    if getattr(settings, "CUSTOM_DINGTALK_OA_ENABLED", False):
        from django.conf import settings
        urlpatterns += [
            path(
                "dingtalk/oa/",
                include(("sql.extensions.dingtalk_oa.urls", "dingtalk_oa")),
            ),
        ]
    ```

2. 重启 gunicorn：

    ```bash
    systemctl restart archery-gunicorn
    ```

### 1.3 `DINGTALK_OA_CALLBACK_AES_KEY must be 43 chars`

**症状**：启动时 `get_oa_access_token()` 报密钥长度错。

**排查**：

```python
python manage.py shell -c "from django.conf import settings; print(len(settings.DINGTALK_OA_CALLBACK_AES_KEY))"
```

**修复**：从钉钉后台「事件订阅」重新生成 AES Key（必须是 43 字符 base64 不含 `=`），更新 `.env` 后重启。

---

## 2. 钉钉回调 4xx 错误码

### 2.1 400 invalid timestamp

**症状**：钉钉后台「事件订阅」测试回调报 400。

**原因**：

- 服务器时间不对（差 > 5 分钟）
- URL 参数 `timestamp` 是毫秒（13 位），不是秒（10 位）

**修复**：

```bash
# 1) 校时
sudo ntpdate ntp.aliyun.com

# 2) 确认 callback 实现用的是毫秒（v0.7 §10.5.1 已用）：
grep "TIMESTAMP_TOLERANCE_MS" sql/extensions/dingtalk_oa/callback.py
# 应该看到 5 * 60 * 1000
```

### 2.2 403 signature invalid

**症状**：钉钉回调 403，event log 写 `signature_failed` 告警。

**原因**：

- `DINGTALK_OA_CALLBACK_TOKEN` 和钉钉后台配置不一致
- 签名算法版本错（v2 vs v3）
- 多次失败后 IP 已被自动封禁

**排查**：

```python
# 1) 确认 token 一致
python manage.py shell -c "from django.conf import settings; print(settings.DINGTALK_OA_CALLBACK_TOKEN)"
# 对照钉钉后台 → 应用 → 事件订阅 → Token

# 2) 确认 IP 是否被封
python manage.py shell -c "
from django.core.cache import cache
print('banned:', cache.get('dingtalk_banned:<你的服务器出口 IP>'))
print('failures:', cache.get('dingtalk_sig_fail:<你的服务器出口 IP>'))
"
```

**修复**：

- 同步 token 后**重启服务**（settings 不会自动重读）
- 如果 IP 被误封，见 §5 解封

### 2.3 400 decrypt failed

**症状**：回调 400，日志 `decrypt failed`。

**原因**：

- `DINGTALK_OA_CALLBACK_AES_KEY` 和钉钉后台不一致
- `DINGTALK_OA_CALLBACK_RECEIVEID`（corp_id）错
- 密文在传输中被反代 / nginx 改了编码

**排查**：

```python
# 1) aes_key 长度必须是 43
python manage.py shell -c "from django.conf import settings; print(len(settings.DINGTALK_OA_CALLBACK_AES_KEY))"

# 2) receiveid
python manage.py shell -c "from django.conf import settings; print(settings.DINGTALK_OA_CALLBACK_RECEIVEID)"
```

**修复**：

- 重新从钉钉后台复制 AES Key（注意：钉钉后台可能有"显示"和"加密"两套，**必须用加密套**）
- 修正 receiveid（= corp_id）

### 2.4 500 internal error

**症状**：回调 500，DingtalkOaEventLog 记 `processed=False` + error 堆栈。

**原因**：业务处理抛异常（最常见是 _handle_event 里 SQL 错误）。

**排查**：

1. Django admin → 钉钉 OA 事件流水 → 找 `processed=False` 的最新一条 → 看 `error` 字段
2. 复制堆栈到搜索引擎 / GitHub issue

**修复**：根据堆栈对应修代码。

---

## 3. 钉钉 OA 启动失败（fallback）

### 3.1 工单详情页看到「⚠️ 钉钉 OA 启动失败，已降级到本地审批」

**症状**：`workflow.audit_fallback_reason` 非空，`WorkflowAuditExternal.external_status='FALLBACK'`。

**正常行为**：v0.7 §10.4 设计 — 业务优先，自动回退到本地 Group 审批，不阻塞业务。

**排查**：

1. 看降级原因：

    ```python
    python manage.py shell -c "
    from sql.models import SqlWorkflow
    w = SqlWorkflow.objects.get(pk=<workflow_id>)
    print('fallback_reason:', w.audit_fallback_reason)
    "
    ```

2. 看事件流水：

    ```python
    from sql.extensions.dingtalk_oa.models import DingtalkOaEventLog
    DingtalkOaEventLog.objects.filter(
        event_type='FALLBACK_AT_START'
    ).order_by('-created_at')[:5].values('created_at', 'error', 'payload')
    ```

3. 看 `DINGTALK_NOTIFY_WEBHOOK` 群里有没有对应告警。

**修复**：

- **如果是钉钉侧偶发**（errcode=88 限流 / errcode=404 模板失效）：等 1 小时后新工单自动恢复；当前工单走本地审批。
- **如果是配置错**（errcode=300001 应用未授权 / errcode=40001 access_token 失效）：见下方
- **如果是网络层**（超时）：先排查钉钉后台 → 网络 → ping/curl

### 3.2 errcode=88 / 限流

**症状**：driver 日志 `dingtalk OA start attempt N/3 failed: ... errcode=88`。

**修复**：

- 短期：自动重试会重试 3 次（已实现），如仍失败则 fallback
- 中期：减少并发提交（前端节流）
- 长期：申请钉钉侧扩容

### 3.3 errcode=40001 access_token 失效

**症状**：所有钉钉 API 调用都返 40001。

**修复**：

```python
# 清掉缓存的 access_token，下次调用自动刷新
python manage.py shell -c "
from django.core.cache import cache
cache.delete('dingtalk_oa_access_token')
"
```

如果还失败 → 查 `DINGTALK_OA_APP_KEY/SECRET` 是否在钉钉后台被禁用。

### 3.4 想关掉降级（高一致性模式）

**场景**：钉钉失败就阻塞业务，不允许走本地 Group 审批。

**修复**（`.env`）：

```ini
CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=False
```

重启 gunicorn。后续 start() 失败会抛 `DingtalkApiError`，工单卡在创建。

---

## 4. 回调延迟/丢失（对账任务）

### 4.1 工单 RUNNING 状态超过 30 分钟没推进

**症状**：`WorkflowAuditExternal.external_status='RUNNING'` 且 `last_synced_at` 老了。

**排查**：

1. 确认对账 schedule 在跑：

    ```python
    python manage.py shell -c "
    from django_q.models import Schedule
    Schedule.objects.filter(name='dingtalk_oa_reconcile').values('name', 'next_run', 'repeats')
    "
    ```

    如果没结果 → 见 §8 重新注册。

2. 看对账任务最近一次跑的结果：

    ```bash
    grep "dingtalk OA reconcile scanned" logs/qcluster.log | tail -10
    ```

3. 手动跑一次：

    ```python
    python manage.py shell -c "
    from sql.extensions.dingtalk_oa.tasks import reconcile_pending_oa_workflows
    print('scanned:', reconcile_pending_oa_workflows())
    "
    ```

**修复**：

- 如果对账**单次** `get_status` 失败 → 看 dingtalk 侧 API 状态
- 如果连续 3 次失败 → `_force_fallback` 已自动触发（看 `FALLBACK_AT_RECONCILE` 事件）

### 4.2 钉钉回调一直没到

**症状**：工单已发起，钉钉后台能看到流程，但 Archery 这边 `last_synced_at` 一直是空。

**排查**：

1. 钉钉后台 → 应用 → 事件订阅 → 回调 URL 是不是 200

2. curl 测试回调连通性：

    ```bash
    curl -i -X POST "https://archery.example.com/dingtalk/oa/callback?timestamp=1700000000000&nonce=x&signature=00$(printf '%040d' 0)"
    # 期望 400 invalid timestamp（没真签名）或 400 invalid timestamp
    ```

3. Nginx 反代有没有 `client_max_body_size` 限制（钉钉 body 可能 1KB+，默认 1M 一般 OK）

4. 反代有没有改 body 编码（utf-8 别动）

**修复**：

- URL 配错：在钉钉后台改回正确 URL
- 反代问题：调整 nginx 配置

---

## 5. 误封禁 IP / 解封

### 5.1 IP 已被自动封禁

**症状**：日志里 `dingtalk signature failures reached threshold for ip=X, banned`，钉钉后续回调都 403。

**原因**：

- 10 次签名失败（v0.7 §10.5.7，1 小时封禁）
- 常见：测试时改 secret 没同步

**解封**：

```python
python manage.py shell -c "
from django.core.cache import cache
cache.delete('dingtalk_banned:<IP>')
cache.delete('dingtalk_sig_fail:<IP>')
print('unbanned <IP>')
"
```

**预防**：

- 改 secret 前先在测试环境验证
- 调试时临时把 `guard.SIGNATURE_FAIL_THRESHOLD` 调高（**仅 debug**，生产改回）

### 5.2 整个办公室出口 IP 都被封

**场景**：多人在用同一个 IP 调试，触发了阈值。

**修复**：见 5.1，同时**临时**调高阈值（仅 debug）：

```python
# sql/extensions/dingtalk_oa/security/guard.py
SIGNATURE_FAIL_THRESHOLD = 100  # 临时调高
```

---

## 6. 密钥轮换

### 6.1 钉钉回调 Token / AES Key 轮换

**周期**：生产环境 90 天至少一次（v0.7 §10.5.6）。

**流程**：

1. 钉钉后台 → 应用 → 事件订阅 → 修改 Token / AES Key
2. **新密钥先不删除旧密钥**（双密钥并行 5 分钟）
3. 更新 `.env`：

    ```ini
    DINGTALK_OA_CALLBACK_TOKEN=<new_token>
    DINGTALK_OA_CALLBACK_AES_KEY=<new_aes_key>
    ```

4. 重启 gunicorn：

    ```bash
    systemctl restart archery-gunicorn
    ```

5. 验证：用钉钉后台「事件订阅 → 测试回调」测试一次成功

6. 钉钉后台删除旧密钥

### 6.2 钉钉 OA 应用 AppKey / AppSecret 轮换

**流程**：

1. 钉钉后台 → 应用详情 → 重置 AppSecret
2. 更新 `.env` 中的 `DINGTALK_OA_APP_KEY` / `DINGTALK_OA_APP_SECRET`
3. 清缓存的 access_token（不然还会用旧 key 拉 token 失败）：

    ```python
    python manage.py shell -c "from django.core.cache import cache; cache.delete('dingtalk_oa_access_token')"
    ```

4. 重启 gunicorn
5. 验证：发一个新工单，钉钉后台能收到 OA 流程

---

## 7. 钉钉 API 限流（429）

**症状**：driver 日志 `errcode=88` 或 HTTP 429。

**修复**：

- 短期：driver.start() 已自动重试 3 次
- 中期：错峰提交（早 9-10 避开）
- 长期：申请钉钉侧 qps 扩容

---

## 8. 对账任务没跑

### 8.1 找不到 `dingtalk_oa_reconcile` schedule

**症状**：Django admin → django_q → Schedule 没这条记录。

**修复**：手动注册一次：

```python
python manage.py shell -c "
from sql.extensions.dingtalk_oa.tasks import add_reconcile_schedule
add_reconcile_schedule()
print('reconcile schedule registered')
"
```

部署文档应当包含这一步（**一次性**）。

### 8.2 django_q cluster 没跑

**症状**：admin 里 schedule 有但 `next_run` 一直不变。

**修复**：

```bash
systemctl status archery-qcluster
systemctl restart archery-qcluster
```

---

## 9. UI 上看不到「重试钉钉 OA」按钮

**症状**：工单详情页 `audit_fallback_reason` 非空，但没看到「重试」按钮。

**原因**：

- 当前用户没 `sql.audit_user` 权限
- 模板没改（**第二阶段不涉及模板修改**，留待阶段 8 "UI 增强"）

**临时方案**：直接调 view：

```python
# 调 view 不走 UI
python manage.py shell -c "
from django.test import Client
from django.contrib.auth import get_user_model
c = Client()
c.force_login(get_user_model().objects.get(username='<admin>'))
r = c.post('/dingtalk/oa/retry/<workflow_id>/')
print(r.status_code, r.url)
"
```

**正式修复**：阶段 8 在 `templates/sqlworkflow.html` 加按钮（参考 v0.7 §10.4.5 模板代码）。

---

## 10. 工单状态卡住

### 10.1 钉钉流程已结束，本地还卡在 WAITING

**症状**：钉钉后台流程已通过/拒绝，但 Archery 还在等下一节点。

**排查**：

1. 看 `DingtalkOaEventLog` 是否有 `bpms_instance_change / finish` 事件：

    ```python
    from sql.extensions.dingtalk_oa.models import DingtalkOaEventLog
    DingtalkOaEventLog.objects.filter(
        event_type='bpms_instance_change'
    ).order_by('-created_at')[:5].values('event_id', 'processed', 'created_at')
    ```

2. 如果有但 `processed=False` → 看 error 字段
3. 如果没有 → 钉钉侧没回调到，先看 §4

**修复**：

- `processed=False` 有堆栈 → 修代码
- 没有回调 → 重启服务 + 手动触发对账

### 10.2 强制把工单从 OA 切回本地

**临时**：

```python
python manage.py shell -c "
from sql.models import SqlWorkflow
w = SqlWorkflow.objects.get(pk=<workflow_id>)
w.audit_driver = 'archery'
w.audit_fallback_reason = '人工切回本地'
w.save(update_fields=['audit_driver', 'audit_fallback_reason'])
"
```

---

## 附录 A：关键 SQL 速查

```sql
-- 最近 24h 降级工单
SELECT sw.id, sw.audit_driver, sw.audit_fallback_reason, sw.create_time
FROM sql_workflow sw
WHERE sw.audit_fallback_reason != ''
  AND sw.create_time > NOW() - INTERVAL 1 DAY
ORDER BY sw.create_time DESC;

-- 最近 100 条钉钉回调
SELECT id, event_type, event_id, processed, error, created_at
FROM ext_dingtalk_oa_event_log
ORDER BY created_at DESC
LIMIT 100;

-- 当前 RUNNING 超时的 OA
SELECT id, audit_id, external_process_instance_id, last_synced_at, reconcile_failed_count
FROM ext_workflow_audit_external
WHERE external_status = 'RUNNING'
  AND (last_synced_at < NOW() - INTERVAL 30 MINUTE OR last_synced_at IS NULL);

-- FALLBACK 状态记录
SELECT id, audit_id, oa_failure_reason, fallback_at
FROM ext_workflow_audit_external
WHERE external_status = 'FALLBACK'
ORDER BY fallback_at DESC
LIMIT 50;
```

---

## 附录 B：紧急回滚

**30 秒关掉**（env 关闭 → 完全回到上游 AuditV2）：

```bash
# 1) 改 .env
CUSTOM_DINGTALK_OA_ENABLED=False

# 2) 重启
systemctl restart archery-gunicorn archery-celery-worker
```

**效果**：

- `ConfigurableAuditor._feature_enabled() = False` → 走父类 AuditV2
- 新工单：完全走本地 Group 审批
- 老工单：`workflow.audit_driver` 保持原值（如 `dingtalk_oa`）继续走 OA；
  如需强制本地，§10.2 手动切。

**彻底回滚**（不推荐）：

```bash
# 1) 改 .env
CUSTOM_DINGTALK_OA_ENABLED=False

# 2) 还原 3 个核心代码
git revert <本 changelog 对应 commit>

# 3) 数据迁移：保留新字段无所谓，老代码读 default='archery' 即可
```

---

**最后更新**：2026-07-20
**维护者**：DBA 团队 + 二次开发 owner
