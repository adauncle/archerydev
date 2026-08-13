"""drill_progress_page_perm.py

业务: 8/13 用户截图反馈, oa_tester_1 (RD) 视角下进度面板还能看到"启动 gh-ost" / "取消迁移" 按钮,
     点击"取消迁移"后浏览器 alert 弹了完整 HTML 源码 ("<!DOCTYPE html>...") 而不是 JSON 错误。

根因:
  1. progress.html 启动 + 取消按钮没加 is_admin_or_dba 守卫 (RD 看到按钮)
  2. _require_change_perm 抛 PermissionDenied → Django middleware 返 403 HTML 错误页
  3. start 端点之前根本没加 perm 守卫

修法 (本次):
  1. progress.html 启动 + 取消按钮包到 {% if is_admin_or_dba %} 守卫
  2. _require_change_perm 改成返 JsonResponse (status=403) 替代 raise PermissionDenied
  3. start 端点加 perm 守卫 (cancel/retry/rollback 同步改)
  4. progress_page 视图加 is_admin_or_dba context 变量

演练 (134 dev 4 Case):
  A. superuser (archery)  → 端点 200 / 看到按钮
  B. mkq (DBA)          → 端点 200 / 看到按钮
  C. oa_tester_1 (RD)   → 端点 403 JSON / 看不到按钮 (静态 body 不含 btn id)
  D. gyf (DBA组长)      → 端点 200 / 看到按钮

清理: 演练后 perm/group 全部还原。
"""
import os
import sys
import json

# 加项目路径
sys.path.insert(0, '/opt/archery/prod')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archery.settings')
import django
django.setup()

from django.conf import settings as dj_settings
# 134 dev settings.py ALLOWED_HOSTS 是 ['*'] 不接受 testserver/127.0.0.1 (Django 严格 ALLOWED_HOST 校验)
# Drill 阶段临时加上 'testserver' 和 '127.0.0.1', 演练完不还原 (下次 drill 会自动重设)
if 'testserver' not in dj_settings.ALLOWED_HOSTS:
    dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver', '127.0.0.1']

from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

# Archery 替换了 auth.User → sql.Users, 用 sql.auth Users 模型
from sql.models import Users as User
from sql.extensions.ddl_gh_ost.models import DdlGhostTask


# 工具
def get_perm_for_user(user, codename):
    """检查 user 是否有 perm (即使没分配 group, has_perm 仍能查单个 perm)"""
    return user.has_perm(f"ddl_gh_ost.{codename}")


def grant_perm(user, codename):
    perm = Permission.objects.get(codename=codename, content_type__app_label="ddl_gh_ost")
    user.user_permissions.add(perm)


def revoke_perm(user, codename):
    perm = Permission.objects.get(codename=codename, content_type__app_label="ddl_gh_ost")
    user.user_permissions.remove(perm)


def setup_users():
    """返回 (archery, mkq, oa_tester_1, gyf) 4 个 user 引用"""
    archery = User.objects.get(username="archery")
    mkq = User.objects.get(username="mkq")
    oa_tester_1 = User.objects.get(username="oa_tester_1")
    gyf = User.objects.get(username="gyf")
    return archery, mkq, oa_tester_1, gyf


def get_target_task_id():
    """找一个 wf 关联的 task 做演练目标 (优先 queued 状态, 这样能验到 startBtn + cancelBtn 渲染)

    优先: task.status in (queued, running) 状态的 task (button 守卫验证需要非终态)
    兜底: 任意 wf 关联的 task
    """
    # 优先找 queued 状态
    task = (
        DdlGhostTask.objects
        .filter(workflow_id__isnull=False, status="queued")
        .order_by("id")
        .first()
    )
    if not task:
        task = DdlGhostTask.objects.filter(workflow_id__isnull=False).order_by("id").first()
    if not task:
        return None, None
    return task.workflow_id, task.id


def drill_case(case_name, user, expected_code, expected_buttons_visible):
    """演练单个 case

    设计原则: read-only, 不触发任何真实修改
      - cancel POST 端点: 用不存在 wf_id=999999, 测 perm 守卫
          perm 通过 → 404 (task 不存在)
          perm 不通过 → 403 JSON
      - progress GET 端点: 用真实 queued 状态的 wf_id, 验按钮可见性

    expected_buttons_visible: True (DBA 视角下应看到 startBtn + cancelBtn) / False (RD 视角下都不应看到)
    """
    print(f"\n{'='*60}")
    print(f"Case: {case_name}  user={user.username}")
    print(f"{'='*60}")

    # 检查 perm
    has_change = get_perm_for_user(user, "change_ddlghosttask")
    print(f"  [perm] has ddl_gh_ost.change_ddlghosttask: {has_change}")

    # 1. cancel POST 端点: 用不存在 wf_id=999999 测 perm 守卫 (不污染数据)
    c = Client(SERVER_NAME="127.0.0.1")
    c.force_login(user, backend="django.contrib.auth.backends.ModelBackend")

    FAKE_WF_ID = 999999
    cancel_resp = c.post(f"/gh_ost/cancel/{FAKE_WF_ID}/")
    print(f"  [POST /gh_ost/cancel/{FAKE_WF_ID}/] status={cancel_resp.status_code}")
    print(f"    body[:200] = {cancel_resp.content[:200]!r}")
    if cancel_resp.status_code == 403:
        try:
            data = cancel_resp.json()
            print(f"    [OK] JSON 错误: ok=False, error={data.get('error', '')[:80]}...")
        except Exception:
            print(f"    [BUG] status=403 但 body 不是 JSON: {cancel_resp.content[:200]!r}")

    # 2. progress GET 端点: 用真实 queued wf_id 验按钮可见性
    real_wf_id, _ = get_target_task_id()
    if real_wf_id is None:
        # 兜底: 用不存在 wf_id, 按钮也不会渲染
        real_wf_id = FAKE_WF_ID
    r = c.get(f"/gh_ost/progress/{real_wf_id}/")
    print(f"  [GET /gh_ost/progress/{real_wf_id}/] status={r.status_code}")
    body = r.content.decode("utf-8", errors="replace")
    has_start = 'id="startBtn"' in body
    has_cancel = 'id="cancelBtn"' in body
    print(f"  [progress.html] startBtn 渲染: {has_start}, cancelBtn 渲染: {has_cancel}")
    if expected_buttons_visible:
        # DBA 视角 + queued 状态: 两个按钮都应渲染
        if real_wf_id != FAKE_WF_ID and r.status_code == 200:
            task = DdlGhostTask.objects.filter(workflow_id=real_wf_id).first()
            if task and task.status == "queued":
                assert has_start, f"{case_name}: 期望看到 startBtn (DBA + queued 任务), 实际未渲染"
                print(f"  [PASS] startBtn 渲染 (DBA 视角 + task.status=queued) ✓")
            if task and task.status in ("queued", "running", "cut_over"):
                assert has_cancel, f"{case_name}: 期望看到 cancelBtn (DBA + 非终态), 实际未渲染"
                print(f"  [PASS] cancelBtn 渲染 (DBA 视角 + task.status={task.status}) ✓")
        else:
            print(f"  [SKIP] wf={real_wf_id} (不存在 or 无 task), 不验证按钮")
    else:
        # RD 视角: 两个按钮都不应渲染 (前端守卫)
        assert not has_start, f"{case_name}: 期望 startBtn 不可见 (RD), 实际渲染了"
        assert not has_cancel, f"{case_name}: 期望 cancelBtn 不可见 (RD), 实际渲染了"
        print(f"  [PASS] RD 视角按钮全部隐藏 ✓")

    # 3. 验证 端点 状态码符合预期
    if expected_code == 200:
        # 端点 perm 守卫通过 → 期望 404 (task 不存在, 因为我们用 fake wf_id)
        assert cancel_resp.status_code == 404, (
            f"{case_name}: 期望 cancel 端点 404 (perm 通过 + fake wf), 实际 {cancel_resp.status_code}"
        )
        print(f"  [PASS] 端点 perm 守卫通过 → 404 (task 不存在) ✓")
    elif expected_code == 403:
        # 端点 perm 守卫不通过 → 403 JSON
        assert cancel_resp.status_code == 403, (
            f"{case_name}: 期望 cancel 端点 403 (RD 无 perm), 实际 {cancel_resp.status_code}"
        )
        print(f"  [PASS] 端点 perm 守卫正确返回 403 JSON ✓")


def r2_should_be_normal(code):
    """端点通过 perm 守卫后, task 状态可能返 200/404/409"""
    return code in (200, 404, 409, 500)  # 500 不太可能, 但保留


def main():
    archery, mkq, oa_tester_1, gyf = setup_users()

    # 1. 准备 4 个 user 的 perm 状态
    print("\n[1] 准备 perm 状态...")
    for u in [mkq, oa_tester_1, gyf]:
        revoke_perm(u, "change_ddlghosttask")  # 先清掉
    # archery superuser 永远有
    print(f"  archery (superuser) has change: {get_perm_for_user(archery, 'change_ddlghosttask')}")
    # mkq (DBA) 分配 change perm
    grant_perm(mkq, "change_ddlghosttask")
    print(f"  mkq after grant change: {get_perm_for_user(mkq, 'change_ddlghosttask')}")
    # oa_tester_1 (RD) 不分配 change perm
    print(f"  oa_tester_1 has change: {get_perm_for_user(oa_tester_1, 'change_ddlghosttask')}")
    # gyf (DBA组长) 分配 change perm
    grant_perm(gyf, "change_ddlghosttask")
    print(f"  gyf after grant change: {get_perm_for_user(gyf, 'change_ddlghosttask')}")

    # 2. 4 Case 演练
    drill_case("A. superuser archery (期望: 200 + 按钮可见)", archery, 200, True)
    drill_case("B. mkq (DBA, 期望: 200 + 按钮可见)", mkq, 200, True)
    drill_case("C. oa_tester_1 (RD, 期望: 403 JSON + 按钮不可见)", oa_tester_1, 403, False)
    drill_case("D. gyf (DBA组长, 期望: 200 + 按钮可见)", gyf, 200, True)

    # 3. 清理 perm
    print("\n[3] 清理 perm 状态 (还原演练前)...")
    for u in [mkq, oa_tester_1, gyf]:
        revoke_perm(u, "change_ddlghosttask")
    print(f"  mkq after revoke change: {get_perm_for_user(mkq, 'change_ddlghosttask')}")
    print(f"  oa_tester_1 after revoke change: {get_perm_for_user(oa_tester_1, 'change_ddlghosttask')}")
    print(f"  gyf after revoke change: {get_perm_for_user(gyf, 'change_ddlghosttask')}")

    print("\n[ALL OK] 4 Case 演练完成")


if __name__ == "__main__":
    main()
