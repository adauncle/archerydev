# D38 续 8: workflow_audit.get_review_info() 引用已删除 Group 报 500 (2026-09-09 17:30)

## 业务方反馈 (9/9 17:29 截图)
- 8/27 及之前的老工单点详情页报 HTTP 500
- 错误: `DoesNotExist at /detail/4741/`
- 异常: `Group matching query does not exist`
- 异常位置: `/dbdata/archery_v114/venv/lib/python3.9/site-packages/django/db/models/query.py line 639, in get`
- 异常来源: `sql.views.detail` line 322 → `audit_handler.get_review_info()` → `workflow_audit.py:628` `Group.objects.get(id=g)`
- 9/2 之后新工单正常 (因为新工单 audit_auth_groups 引用 Group 都还在)

## 根因
- `sql/utils/workflow_audit.py:628` `group_in_db = Group.objects.get(id=g)` 没 try/except 兜底
- 老工单 (8/27 之前) 的 `audit_auth_groups` 字段保存了已被 DBA 删除的 Group ID (e.g. wf#4741 `audit_auth_groups=6,3,15,16`, Group 16 已不存在)
- 同一个文件 line 181-182 / 523-526 都有 try/except 兜底, line 628 漏了 (上游 Archery bug)

## wf#4741 实测 (D38 续 8 16:42 ssh 端 force_login 诊断)
```
wf4741 group_id= 6 group_name= prod core for etc 变更
audit_auth_groups= 6,3,15,16
audit: 4795 audit_auth_groups= 6,3,15,16 current_audit= -1
group 6 -> 研发组长
group 3 -> DBA
group 15 -> 研发
group 16 ERROR: Group matching query does not exist.
```

## 修法
改 `sql/utils/workflow_audit.py:628` 加 try/except 兜底 (跟 line 181-182 / 523-526 同样的 pattern):
```python
try:
    group_in_db = Group.objects.get(id=g)
except Group.DoesNotExist:
    group_in_db = None  # 上游 Archery bug: Group 被删时 review_info 应优雅降级
```

## 演练 PASS 计划
1. 134 dev force_login mkq 看 wf#4741 (8/27 老工单) 详情页应正常显示 (不再 500)
2. 110 prod scp 推 + 重启后同样验证
3. 顺手验证 9/2 之后新工单 (wf#4791/wf#4792) 仍正常 (没破坏现有功能)

## 改动 1 个文件
1. `sql/utils/workflow_audit.py` (line 628) - 加 try/except 兜底

## 部署清单
- 1 文件 scp 推 110 prod
- 1 文件 scp 推 134 dev
- 110 prod gunicorn pkill + setsid nohup 重启
- 演练 4 组合 (2 工单 × 1 用户 mkq, 134 dev + 110 prod)

## 实战新发现 (跨项目可复用, 2 条)
1. **Archery 上游 bug: workflow_audit.get_review_info() 没 Group.DoesNotExist 兜底** (D38 续 8 实战新发现) - 老工单 group 被删后, 详情页会 500. 跨项目用 Archery 1.14.0 + 有老工单 (1 年前) 的环境必查这个, 修法是给 line 628 加 try/except
2. **D38 续 7 推 views.py 后老工单才暴露 500** (D38 续 8 实战新发现) - 老版本 (8/26 2a04a12) views.py line 322 走的是 audit_handler.review_info property (line 169), 新版本 (9/3 a4abf01) 走的是 get_review_info() 方法 (line 592), 后者会触发 line 628 bug. 跨项目 D35 push 这种大版本推 110 prod 必演练**老工单**, 不只演练新工单

## 下次推 prod checklist 必加 1 条
**推 110 prod 必演练老工单 (1 年前) + 新工单两边验证** — 跨项目推生产版本时, 不只演练刚改的 wf#4791, 必选 1-2 个老工单 (e.g. 1 年前的) 走详情页, 防止上游 bug 借我们推的代码被触发

## W2 状态
D6 → ... → D37 → D38 → D38 补充 → D38 续 → D38 续 2 → D38 续 3 → D38 续 4 → D38 续 5 → D38 续 6 → D38 续 7 → **D38 续 8 (workflow_audit.get_review_info() 老工单 Group.DoesNotExist 兜底修复, 进行中)**
