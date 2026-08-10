# 134 dev 验证发现 — detail 视图 / WorkflowAudit 缺失兼容

**日期**: 2026-08-10
**作者**: mavis
**类型**: fix（detail 视图无审批流时 AttributeError + can_review DoesNotExist）

## 背景

上一轮 (`e78f758`) 修了 `detail_content` 视图的 500 错误。DBA 浏览器点开 `/detail/19/` 详情页
（不是 detail_content 那个 AJAX 端点），又触发新的 500：`'NoneType' object has no attribute 'current_audit'`。

## 根因（两层）

### 第一层：get_review_info 没兜底

- `AuditV2.get_audit_info()` 返回类型是 `Optional[WorkflowAudit]`，**注释明确说"可能返回 None"**
- 但 `get_review_info` (workflow_audit.py:581) 第一行 `self.get_audit_info()` 后**没判 None**
- 立即 `int(self.audit.current_audit)` → `None.current_audit` → AttributeError

**触发场景**：wf=14/19 是 v0.4.5-alpha 演练创建的工单，演练时直接走 admin cancel 跳过
WorkflowAudit 创建，status 仍被设成 `workflow_finish`，但库里没 WorkflowAudit 行。

### 第二层：Audit.can_review 裸 objects.get

- views.py:243 `is_can_review = Audit.can_review(...)` 触发 `WorkflowAudit.objects.get(...)` 
- wf=14/19 没 audit → `DoesNotExist: WorkflowAudit matching query does not exist` → 500

（即使第一层修好，第二层仍炸；两处都要修）

## 修复（2 处 CUSTOM-MODIFIED 注释）

### 1. workflow_audit.py `get_review_info` (line 581-589)

```python
def get_review_info(self) -> ReviewInfo:
    self.get_audit_info()
    ## CUSTOM-MODIFIED: 工单无审批流时返回空 ReviewInfo
    if self.audit is None:
        return ReviewInfo()
    review_nodes = []
    ...
```

`ReviewInfo()` 默认 `nodes=[]`, `current_node_index=None`，模板渲染时空 readable_info。

### 2. workflow_audit.py `Audit.can_review` (line 724-728)

```python
@staticmethod
def can_review(user, workflow_id, workflow_type):
    ## CUSTOM-MODIFIED: 工单无审批流时返回 False
    try:
        audit_info = WorkflowAudit.objects.get(
            workflow_id=workflow_id, workflow_type=workflow_type
        )
    except WorkflowAudit.DoesNotExist:
        return False
    ...
```

**为什么改这里而不是改 views.py**：can_review 是 staticmethod，被多处复用（views.py:243 +
可能其他调用方）。在内部兜底让所有调用方都受益。

## 验证（13 个工单 detail 视图全部 200）

| wf_id | 改前 | 改后 | size |
|-------|------|------|------|
| 4 | 200 | 200 ✅ | 72382B |
| 5 | 200 | 200 ✅ | 70542B |
| 6 | 200 | 200 ✅ | 71776B |
| **10 (老, 有 audit)** | 500 (detail_content 之前) | **200 ✅** | 72616B |
| **11 (老, 有 audit)** | 500 (detail_content) | **200 ✅** | 70568B |
| **12 (老, 有 audit)** | 500 (detail_content) | **200 ✅** | 71004B |
| **13 (老, 有 audit)** | 500 (detail_content) | **200 ✅** | 71906B |
| **14 (新, 无 audit)** | 500 (AttributeError) | **200 ✅** | 70875B |
| **15 (新, 无 audit)** | 500 (AttributeError) | **200 ✅** | 70861B |
| **16 (新, 无 audit)** | 500 (AttributeError) | **200 ✅** | 70876B |
| **17 (新, 无 audit)** | 500 (AttributeError) | **200 ✅** | 70871B |
| **18 (新, 无 audit)** | 500 (AttributeError) | **200 ✅** | 70871B |
| **19 (新, 无 audit)** | 500 (AttributeError) | **200 ✅** | 70871B |

## 110 PROD 影响

| 修复 | 推 110？ | 说明 |
|------|----------|------|
| get_review_info 兜底 | ✅ 推 | 上游裸 `self.audit.xxx` bug，110 也有 |
| can_review 兜底 | ✅ 推 | 上游裸 `objects.get` bug，110 也有 |

**110 推 v0.3.0 时一起 tarball 同步这两个文件即可**（`sql/utils/workflow_audit.py`）。

## 134 dev 操作

- [x] scp workflow_audit.py + chown + restart gunicorn
- [x] 13 个工单 detail 视图 200 验证
- [ ] commit + push（待做）

## 相关 commit

- 上一轮 `e78f758` — detail_content 老工单容错 + KeyError 兜底
- **本轮** — workflow_audit.py get_review_info + can_review 兜底
