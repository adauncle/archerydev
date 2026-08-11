# -*- coding: utf-8 -*-
"""
2026-08-11 本周（v0.3.0-beta 完整周期）一次性追加 17 条到 v3 Excel:
- 10 条新功能 (gh-ost / 钉钉 OA / 平台基础)
- 7 条 bug 修复 (归纳在“提测阶段”分组)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from record_feature import append_row_to_xlsx

REPO_ROOT = Path(__file__).resolve().parent.parent
XLSX = REPO_ROOT / "docs" / "reports" / "2026-08-06_功能开发计划_v3_172831.xlsx"

TODAY = "2026-08-11"

# 注意: 描述里的英文双引号 " 全部用单引号 ' 替代, 避免 Python 字符串嵌套错误
NEW_ENTRIES = [
    # gh-ost 无锁 DDL 分组 (7 条)
    (
        "gh-ost 无锁 DDL",
        "v0.3.0-beta 前段 UI 集成 4 件 (启用按钮 + iframe 进度 + admin 按钮)",
        TODAY, 1.0, "已发布", "6c44926→2129221, 853bf6a, 461152d, 281fbeb",
        "中", "mavis", 0.5,
        "commit 4 件 + X-Frame-Options exempt + admin URL 用 app_label + superuser 守卫",
        "【场景】RD 走 gh-ost 流程要在详情页看到启动入口和实时进度；【使用】详情页'启用 gh-ost'按钮 → 预检 5s → 启动 → 进度面板 iframe 轮询 3s。admin 按钮仅 superuser 可见，跳新窗口绕开 X-Frame-Options。"
    ),
    (
        "gh-ost 无锁 DDL",
        "v0.3.0-beta 端到端真跑成功 (wf=20 task=33 cut-over 5s)",
        TODAY, 1.0, "已发布", "cd2ce88",
        "中", "mavis", 0.3,
        "端到端首跑 wf#20 task#33",
        "【场景】v0.3.0-beta 在 134 dev 真表演练首次跑通；【使用】admin 启用 → precheck 5/5 → 启动 pid=47284 → 5s 内 cut-over success + progress=100 + current_stage=done，wf.status 自动切 workflow_finish。"
    ),
    (
        "gh-ost 无锁 DDL",
        "v0.3.0-beta 提交页'启用 gh-ost'勾选联动",
        TODAY, 1.0, "已发布", "70fcf47",
        "中", "mavis", 0.3,
        "submit_sql + api_workflow 联动",
        "【场景】RD 提交工单时能直接勾选'启用 gh-ost'；【使用】sqlsubmit.html 蓝色 checkbox → submit 端点调 _enable_ghost_for_workflow → 审批通过时 task 已在。3 路径验证：勾+ALTER 自动 / 不勾走原路径 / 勾+非 ALTER 主流程成功错误塞 response。"
    ),
    (
        "gh-ost 无锁 DDL",
        "v0.3.0-beta 状态机三件套 (避免双 ALTER + wf 状态同步)",
        TODAY, 1.0, "已发布", "04ae0aa",
        "中", "mavis", 0.4,
        "is_can_execute 守卫 + poller._sync_workflow_status + 终态 UI",
        "【场景】启用 gh-ost 后不能再点'立即执行'避免锁等待；【使用】active task (queued/running/cut_over/precheck_failed) 时 is_can_execute=False；poller 终态 success→workflow_finish / failed→workflow_exception / cancelled 不动；详情页 active 走 iframe / terminal 走摘要表。"
    ),
    (
        "gh-ost 无锁 DDL",
        "v0.3.0-beta zombie socket 双层防御",
        TODAY, 1.0, "已发布", "8ddc59a",
        "中", "mavis", 0.3,
        "runner 启动前清 + poller 终态清",
        "【场景】上次 cut-over 失败 / SIGTERM 残留 Unix socket 路径，新 gh-ost bind 失败；【使用】runner._cleanup_stale_socket 启动前探测（进程死 unlink + WARNING, 进程活 RuntimeError 防双跑）；poller SIGTERM 后 2s 探测 SIGKILL 兜底 + 主动 unlink /tmp/gh-ost.*.sock。"
    ),
    (
        "gh-ost 无锁 DDL",
        "v0.3.0-beta 审批守卫 (启用前必须审批通过)",
        TODAY, 1.0, "已发布", "664058c",
        "中", "mavis", 0.4,
        "SqlWorkflow.enable_gh_ost + lazy auto-enable + cancel 清理",
        "【场景】修真 bug：提交勾 gh-ost 后审批前能点启用按钮；【使用】submit 端点只存标记 wf.enable_gh_ost=True；审批通过时 detail 视图 lazy auto-enable 调 _enable_ghost_for_workflow；拒绝/撤回走 /cancel/ 时清理非终态 DdlGhostTask，标记保留。"
    ),
    (
        "gh-ost 无锁 DDL",
        "v0.3.0-beta DBA 兜底 + 大表 DDL 防呆",
        TODAY, 1.0, "已发布", "f87e875",
        "高", "mavis", 0.6,
        "can_enable_ghost 放宽 + 大表 alert 三按钮 + 5 Case 演练",
        "【场景】修真生产风险：RD 没勾 gh-ost → 3 级审批通过 → DBA 走原路径'立即执行' → 大表锁表；【使用】can_enable_ghost 加 has_perm('sql.sql_review') 替代 is_dba_group；阈值 10w 行 / 100MB 触发红色 alert + 三按钮（启用 gh-ost 兜底 / 立即执行 confirm / 终止工单）。5 Case 端到端演练全过。"
    ),
    # 钉钉 OA 集成 (1 条)
    (
        "钉钉 OA 集成",
        "v0.2.0 钉钉 OA 3 级审批配置生效修复",
        TODAY, 1.0, "已发布", "d5f88d1",
        "中", "mavis", 0.3,
        "ext_approval_flow + fix_approval_flow_3level 命令",
        "【场景】修真 bug：wf#57 走单级 DBA 审批但用户配置 3 级；【使用】134 dev UPDATE ext_approval_flow audit_auth_groups='14,15,3'；新增 fix_approval_flow_3level management command (idempotent, 110 prod 推时跑)；init_fallback_flow 占位 1,2 → 14,15,3。"
    ),
    # 平台基础 (2 条)
    (
        "平台基础",
        "'bug 必记'原则固化 (AGENTS.md + troubleshooting.md 8KB 速查表)",
        TODAY, 1.0, "已发布", "ba32ba5",
        "低", "mavis", 0.2,
        "4 层文档分工 + 按现象速查 8 类 + 14 个 changelog 索引",
        "【场景】用户提的工程纪律：修 bug 必须先写 changelog 再写代码，踩坑写进 memory；【使用】AGENTS.md 二次开发硬规则第 7 条固化 + docs/troubleshooting.md 8KB 速查表（gh-ost / 审批 / 老工单兼容 / 凭据加密 / 134 dev 部署 / Django 视图 / 演练脚本 / Windows 工具链 8 类），遇到问题先看它。"
    ),
    (
        "平台基础",
        "HTML 项目进度汇报稿 (2026-08-11 6 大块 Report 模式)",
        TODAY, 1.0, "已发布", "07dedd1",
        "低", "mavis", 0.2,
        "docs/reports/2026-08-11_project-progress-report.html 20KB",
        "【场景】领导要 8/11 汇报项目进度；【使用】HTML Report 模式（cream 背景 + DM Serif + Outfit），6 大块：当前状态 / 关键数据 / 关键里程碑 / 本周亮点 / 风险 + 应对 / 下周计划。"
    ),
]

# 7 条 bug 修复（归纳'提测阶段'）
BUG_ENTRIES = [
    (
        "提测阶段",
        "134 dev common/static 目录缺失修复",
        TODAY, 1.0, "已发布", "be4d6fb",
        "高", "mavis", 0.2,
        "tarball sync 漏 common/static/ 整个目录",
        "【症状】134 dev 页面裸 HTML 无 CSS/JS；【根因】tarball 打包漏 common/static/（gunicorn 一直 active 但页面静态资源 404）；【修法】cp -r upstream common/static/ + collectstatic --noinput + chown archery:archery + restart gunicorn。"
    ),
    (
        "提测阶段",
        "detail_content 老工单 SqlWorkflowContent 缺失兼容",
        TODAY, 1.0, "已发布", "e78f758",
        "中", "mavis", 0.3,
        "sql_workflow.py + policy.py + notify.py 加 getattr 兜底",
        "【症状】老工单无 sqlworkflowcontent 行 → AttributeError 500；【根因】detail_content 直接 .sqlworkflowcontent.xxx；【修法】3 个文件加 getattr + SqlWorkflowContent.DoesNotExist 兜底，老工单显示空 rows + _empty_content=True 不阻塞页面。"
    ),
    (
        "提测阶段",
        "workflow_audit None/DoesNotExist 兜底",
        TODAY, 1.0, "已发布", "b8c0e6d",
        "中", "mavis", 0.2,
        "get_review_info + Audit.can_review 兜底",
        "【症状】用户报 500 在 audit_handler.get_review_info / Audit.can_review；【根因】老工单无对应 audit 行；【修法】get_review_info 加 if self.audit is None: return ReviewInfo()；can_review 加 try/except WorkflowAudit.DoesNotExist: return False。"
    ),
    (
        "提测阶段",
        "detail.html data-toggle for...of undefined 报错",
        TODAY, 1.0, "已发布", "d44632f→2129221",
        "中", "mavis", 0.2,
        "去掉 4 处 data-toggle='table'",
        "【症状】详情页 console 报 for...of undefined 错；【根因】Bootstrap-table data-toggle 在空数组上调用 for...of 抛错；【修法】去掉 4 处 data-toggle='table'（静态表 / tb-detail / tb-logs / osc_percent_list），改成普通 table + 静态渲染。"
    ),
    (
        "提测阶段",
        "detail_content rows 兼容 list (非 dict 类型)",
        TODAY, 1.0, "已发布", "853cb71",
        "低", "mavis", 0.2,
        "json.loads 兜底 + isinstance 判 list",
        "【症状】review_content='{}' 时 rows 不是 list，drill 断言失败；【根因】老工单 review_content 是空 dict 不是 list；【修法】detail_content 解析 rows 时 if not isinstance(parsed, list): parsed = []，保证后续处理都是 list。"
    ),
    (
        "提测阶段",
        "sql_config inception_remote_backup_* 4 字段 K2 重加密",
        TODAY, 1.0, "已发布", "b429f28",
        "高", "mavis", 0.2,
        "Mirage K1≠K2 密文解不开, 4 字段改明文",
        "【症状】134 dev 凭据解不开 → gh-ost precheck 失败 / inception 备份失败；【根因】sql_config 表 4 个 inception_remote_backup_* 字段历史 mirage K1 密文，K2 密钥不匹配；【修法】admin 后台改明文（host=127.0.0.1 / port=3306 / user=dbops / password=...），让 K2 重新加密。instance id=1 / id=2 user/password 同处理。"
    ),
    (
        "提测阶段",
        "134 dev /var/log/archery/gh_ost/ 目录 chown 修复",
        TODAY, 1.0, "已发布", "042dee3",
        "中", "mavis", 0.2,
        "root 创建目录 + /tmp/gh-ost.*.sock 残留",
        "【症状】134 dev gh-ost 进程写日志失败 / cut-over 后 zombie socket 残留端口冲突；【根因】历史 v0.3.0-beta 演练时 root 跑 gh-ost 创建了 root:root 目录 + sock 文件；【修法】deploy_v030b.sh 加 chown -R archery:archery /var/log/archery/gh_ost + rm -f /tmp/gh-ost.*.sock + drop 影子表。"
    ),
]


def main():
    all_entries = NEW_ENTRIES + BUG_ENTRIES
    print(f"[batch] 准备追加 {len(all_entries)} 条 (新功能 {len(NEW_ENTRIES)} + bug 修复 {len(BUG_ENTRIES)}) 到 {XLSX.name}")
    for i, (group, name, when, pct, status, commit, risk, owner, days, note, desc) in enumerate(all_entries, 1):
        append_row_to_xlsx(
            xlsx_path=XLSX,
            group=group, name=name, when=when, pct=pct, status=status,
            commit=commit, note=note, risk=risk, owner=owner,
            days=days, desc=desc,
        )
        print(f"  [{i:>2}/{len(all_entries)}] + {group[:6]} | {name[:40]}")
    print(f"\n[batch] 全部追加完成: {XLSX}")


if __name__ == "__main__":
    main()
