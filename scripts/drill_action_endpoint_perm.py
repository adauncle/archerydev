# -*- coding: utf-8 -*-
"""测 gh-ost 任务运维操作端点 perm 守卫 (A 方案: change_ddlghosttask) + 前端按钮按视角隐藏。

4 Case 演练:
  A. archery (superuser) -> 端点 404 (有 perm, task 不存在) + 前端按钮全部显示
  B. mkq (DBA 组) -> 端点 404 + 前端按钮全部显示
  C. oa_tester_1 (RD 组, 有 view 无 change) -> 端点 403 + 前端只显示 view
  D. gyf (DBA组长组) -> 端点 404 + 前端按钮全部显示

演练策略:
  用不存在 task_id (99999) 避免污染数据。perm 守卫在 task 查询之前:
    - 无 perm -> 403 (perm 守卫先抛, 不会查 task)
    - 有 perm -> 404 (进 task 查询, task 不存在)
  这样能干净区分 perm 守卫工作是否正常, 不会真改 status 污染生产数据。
"""
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django; django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from django.contrib.auth.models import Group, Permission
from django.test import Client
from sql.models import Users
from sql.extensions.ddl_gh_ost.models import DdlGhostTask


def _force_login(username: str) -> tuple:
    c = Client()
    u = Users.objects.get(username=username)
    c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")
    return c, u


def _call_endpoint(c: Client, action: str, workflow_id: int) -> int:
    """POST /gh_ost/<action>/<wf_id>/, 返回 status code"""
    r = c.post(f"/gh_ost/{action}/{workflow_id}/")
    return r.status_code


NONEXIST_WF = 99999  # 演练用不存在 task_id, 避免污染生产数据
print("=" * 60)
print("演练策略: 用不存在 task_id=99999 避免污染数据")
print("perm 守卫顺序: 1. perm 守卫 -> 2. task 查询 -> 3. 业务逻辑")
print("期望: 无 perm -> 403, 有 perm -> 404 (task 不存在)")
print("=" * 60)
print()

# 拿 perm 对象
view_perm = Permission.objects.get(content_type__app_label="ddl_gh_ost", codename="view_ddlghosttask")
change_perm = Permission.objects.get(content_type__app_label="ddl_gh_ost", codename="change_ddlghosttask")
print(f"view_perm: {view_perm.name} (id={view_perm.id})")
print(f"change_perm: {change_perm.name} (id={change_perm.id})")
print()

# 拿各组 + 备份原始 perm 列表
rd_group = Group.objects.get(name="研发")
dba_group = Group.objects.get(name="DBA")
dba_lead_group = Group.objects.get(name="DBA组长")
original_rd = set(rd_group.permissions.all())
original_dba = set(dba_group.permissions.all())
original_dba_lead = set(dba_lead_group.permissions.all())
print("=== 备份 3 组原始 perm 列表 (演练结束清理) ===")
print()


def setup_perms(dba_view=True, dba_change=True, dba_lead_view=True, dba_lead_change=True, rd_view=True, rd_change=True):
    """配置 perm 分配 (演练用, 结束清理)"""
    if dba_view: dba_group.permissions.add(view_perm)
    if dba_change: dba_group.permissions.add(change_perm)
    if dba_lead_view: dba_lead_group.permissions.add(view_perm)
    if dba_lead_change: dba_lead_group.permissions.add(change_perm)
    if rd_view: rd_group.permissions.add(view_perm)
    if rd_change: rd_group.permissions.add(change_perm)
    dba_group.save()
    dba_lead_group.save()
    rd_group.save()


def cleanup_perms():
    for grp, orig in [(rd_group, original_rd), (dba_group, original_dba), (dba_lead_group, original_dba_lead)]:
        grp.permissions.set(orig)
        grp.save()


def check_buttons_in_body(body: str) -> dict:
    """数 body 里 cancel / retry / rollback 按钮渲染数 (admin_list 页面)"""
    import re
    tbody_match = re.search(r'<tbody>(.*?)</tbody>', body, re.DOTALL)
    if not tbody_match:
        return {"cancel": 0, "retry": 0, "rollback": 0}
    tbody = tbody_match.group(1)
    return {
        "cancel": len(re.findall(r'data-act="cancel"', tbody)),
        "retry": len(re.findall(r'data-act="retry"', tbody)),
        "rollback": len(re.findall(r'data-act="rollback"', tbody)),
    }


# 默认所有组都加 view + change
setup_perms(dba_change=True, rd_change=True, dba_lead_change=True)


# =========================
# Case A: superuser
# =========================
print("=== Case A: archery (superuser) ===")
c, u = _force_login("archery")
print(f"  has_perm view={u.has_perm('ddl_gh_ost.view_ddlghosttask')}, "
      f"change={u.has_perm('ddl_gh_ost.change_ddlghosttask')}")

code_cancel = _call_endpoint(c, "cancel", NONEXIST_WF)
code_retry = _call_endpoint(c, "retry", NONEXIST_WF)
code_rollback = _call_endpoint(c, "rollback", NONEXIST_WF)
print(f"  cancel/{NONEXIST_WF} -> {code_cancel} (期望 404 有 perm, task 不存在)")
print(f"  retry/{NONEXIST_WF} -> {code_retry} (期望 404)")
print(f"  rollback/{NONEXIST_WF} -> {code_rollback} (期望 404)")
assert code_cancel == 404, f"A 失败: cancel 应 404 实际 {code_cancel}"
assert code_retry == 404, f"A 失败: retry 应 404 实际 {code_retry}"
assert code_rollback == 404, f"A 失败: rollback 应 404 实际 {code_rollback}"

r = c.get("/gh_ost/admin_list/")
body = r.content.decode("utf-8", "replace")
btn = check_buttons_in_body(body)
print(f"  前端按钮: cancel={btn['cancel']} retry={btn['retry']} rollback={btn['rollback']}")
assert btn["cancel"] > 0, f"A 失败: superuser 应看到 cancel 按钮"
assert btn["retry"] > 0, f"A 失败: superuser 应看到 retry 按钮"
assert btn["rollback"] > 0, f"A 失败: superuser 应看到 rollback 按钮"
print("  PASS A (superuser: 端点 404 + 按钮全显示)")
print()


# =========================
# Case B: mkq (DBA 组)
# =========================
print("=== Case B: mkq (DBA 组) ===")
c, u = _force_login("mkq")
print(f"  has_perm view={u.has_perm('ddl_gh_ost.view_ddlghosttask')}, "
      f"change={u.has_perm('ddl_gh_ost.change_ddlghosttask')}")

code_cancel = _call_endpoint(c, "cancel", NONEXIST_WF)
code_retry = _call_endpoint(c, "retry", NONEXIST_WF)
code_rollback = _call_endpoint(c, "rollback", NONEXIST_WF)
print(f"  cancel/{NONEXIST_WF} -> {code_cancel} (期望 404)")
print(f"  retry/{NONEXIST_WF} -> {code_retry} (期望 404)")
print(f"  rollback/{NONEXIST_WF} -> {code_rollback} (期望 404)")
assert code_cancel == 404
assert code_retry == 404
assert code_rollback == 404

r = c.get("/gh_ost/admin_list/")
body = r.content.decode("utf-8", "replace")
btn = check_buttons_in_body(body)
print(f"  前端按钮: cancel={btn['cancel']} retry={btn['retry']} rollback={btn['rollback']}")
assert btn["cancel"] > 0 and btn["retry"] > 0 and btn["rollback"] > 0
print("  PASS B (DBA: 端点 404 + 按钮全显示)")
print()


# =========================
# Case C: oa_tester_1 (RD 组) -> 撤销 change perm -> 端点 403
# =========================
print("=== Case C: oa_tester_1 (RD 组, 有 view 无 change) ===")
rd_group.permissions.remove(change_perm)
rd_group.save()
print("  撤销'研发'组 change_ddlghosttask perm")

c, u = _force_login("oa_tester_1")
print(f"  has_perm view={u.has_perm('ddl_gh_ost.view_ddlghosttask')}, "
      f"change={u.has_perm('ddl_gh_ost.change_ddlghosttask')}")

code_cancel = _call_endpoint(c, "cancel", NONEXIST_WF)
code_retry = _call_endpoint(c, "retry", NONEXIST_WF)
code_rollback = _call_endpoint(c, "rollback", NONEXIST_WF)
print(f"  cancel/{NONEXIST_WF} -> {code_cancel} (期望 403 无 perm)")
print(f"  retry/{NONEXIST_WF} -> {code_retry} (期望 403)")
print(f"  rollback/{NONEXIST_WF} -> {code_rollback} (期望 403)")
assert code_cancel == 403, f"C 失败: cancel 应 403 实际 {code_cancel}"
assert code_retry == 403, f"C 失败: retry 应 403 实际 {code_retry}"
assert code_rollback == 403, f"C 失败: rollback 应 403 实际 {code_rollback}"

r = c.get("/gh_ost/admin_list/")
body = r.content.decode("utf-8", "replace")
btn = check_buttons_in_body(body)
print(f"  前端按钮: cancel={btn['cancel']} retry={btn['retry']} rollback={btn['rollback']} (期望全 0)")
assert btn["cancel"] == 0, f"C 失败: RD 不应看到 cancel 按钮, 实际 {btn['cancel']}"
assert btn["retry"] == 0, f"C 失败: RD 不应看到 retry 按钮, 实际 {btn['retry']}"
assert btn["rollback"] == 0, f"C 失败: RD 不应看到 rollback 按钮, 实际 {btn['rollback']}"
print("  PASS C (RD: 端点全 403 + 按钮全 0)")
print()

# 恢复'研发'组 change perm
rd_group.permissions.add(change_perm)
rd_group.save()


# =========================
# Case D: gyf (DBA组长组)
# =========================
print("=== Case D: gyf (DBA组长组) ===")
c, u = _force_login("gyf")
print(f"  has_perm view={u.has_perm('ddl_gh_ost.view_ddlghosttask')}, "
      f"change={u.has_perm('ddl_gh_ost.change_ddlghosttask')}")

code_cancel = _call_endpoint(c, "cancel", NONEXIST_WF)
code_retry = _call_endpoint(c, "retry", NONEXIST_WF)
code_rollback = _call_endpoint(c, "rollback", NONEXIST_WF)
print(f"  cancel/{NONEXIST_WF} -> {code_cancel} (期望 404)")
print(f"  retry/{NONEXIST_WF} -> {code_retry} (期望 404)")
print(f"  rollback/{NONEXIST_WF} -> {code_rollback} (期望 404)")
assert code_cancel == 404
assert code_retry == 404
assert code_rollback == 404

r = c.get("/gh_ost/admin_list/")
body = r.content.decode("utf-8", "replace")
btn = check_buttons_in_body(body)
print(f"  前端按钮: cancel={btn['cancel']} retry={btn['retry']} rollback={btn['rollback']}")
assert btn["cancel"] > 0 and btn["retry"] > 0 and btn["rollback"] > 0
print("  PASS D (DBA组长: 端点 404 + 按钮全显示)")
print()


# =========================
# Case E: _require_change_perm 单元测试
# =========================
print("=== Case E: _require_change_perm 单元测试 ===")
from sql.extensions.ddl_gh_ost.views import _require_change_perm
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser

rf = RequestFactory()

# E.1 匿名用户 -> 403
req = rf.post("/gh_ost/cancel/1/")
req.user = AnonymousUser()
try:
    _require_change_perm(req, "test")
    assert False, "E.1 失败: 匿名应抛 403"
except PermissionDenied:
    print("  PASS E.1 匿名用户 -> PermissionDenied")

# E.2 RD (有 view 无 change) -> 403
rd_group.permissions.remove(change_perm); rd_group.save()
u_rd = Users.objects.get(username="oa_tester_1")
req = rf.post("/gh_ost/cancel/1/")
req.user = u_rd
try:
    _require_change_perm(req, "test")
    assert False, "E.2 失败: 无 change 应抛 403"
except PermissionDenied:
    print("  PASS E.2 RD (无 change perm) -> PermissionDenied")

# E.3 mkq (DBA, 有 change) -> 通过
rd_group.permissions.add(change_perm); rd_group.save()
u_dba = Users.objects.get(username="mkq")
req = rf.post("/gh_ost/cancel/1/")
req.user = u_dba
_require_change_perm(req, "test")
print("  PASS E.3 mkq (DBA, 有 change perm) -> 通过")
print()


# =========================
# 清理
# =========================
print("=== 清理: 还原 3 组 perm 列表 ===")
cleanup_perms()
for grp, orig in [(rd_group, original_rd), (dba_group, original_dba), (dba_lead_group, original_dba_lead)]:
    assert set(grp.permissions.all()) == orig, f"清理失败: {grp.name}"
print("  PASS 清理彻底")
print()

print("=" * 60)
print("ALL PASS: 4 Case + 3 单元测试 + 清理")
print("A 方案 (change_ddlghosttask perm 守卫) 验证通过")
print("  - 后端硬墙: RD 调端点全部 403, 不依赖前端")
print("  - 前端按钮: 跟后端守卫对齐, 视角外不渲染")
print("  - DBA / superuser 视角端点 404 (有 perm, task 不存在), 按钮全显示")
print("=" * 60)
