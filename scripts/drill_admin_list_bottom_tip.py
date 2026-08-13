# -*- coding: utf-8 -*-
"""测 gh-ost 任务列表页底部 AJAX 提示 + admin 链接 (DBA 视角专属)。

4 Case 演练:
  A. archery (superuser) → 底部这一行显示 (含 admin 链接)
  B. mkq (DBA 组) → 底部这一行显示
  C. oa_tester_1 (研发组, 提交人视角) → 底部这一行不显示
  D. gyf (DBA组长组) → 底部这一行显示

关键关键字 (要检测的):
  - "操作走 AJAX" — 整段文字
  - "/admin/ddl_gh_ost/ddlghosttask/" — admin 链接 URL
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


def _force_login(username: str) -> tuple:
    c = Client()
    u = Users.objects.get(username=username)
    c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")
    return c, u


def _check_bottom(c: Client) -> tuple:
    """访问 /gh_ost/admin_list/, 返回 (status, has_ajax_tip, has_admin_link)"""
    r = c.get("/gh_ost/admin_list/")
    body = r.content.decode("utf-8", "replace")
    has_ajax_tip = "操作走 AJAX" in body
    has_admin_link = "/admin/ddl_gh_ost/ddlghosttask/" in body
    return r.status_code, has_ajax_tip, has_admin_link


PERM = "ddl_gh_ost.view_ddlghosttask"
view_perm = Permission.objects.get(content_type__app_label="ddl_gh_ost", codename="view_ddlghosttask")

# 临时分配 perm (4 个测试用户)
rd_group = Group.objects.get(name="研发")
dba_group = Group.objects.get(name="DBA")
dba_lead_group = Group.objects.get(name="DBA组长")
original_rd = set(rd_group.permissions.all())
original_dba = set(dba_group.permissions.all())
original_dba_lead = set(dba_lead_group.permissions.all())
rd_group.permissions.add(view_perm)
dba_group.permissions.add(view_perm)
dba_lead_group.permissions.add(view_perm)
rd_group.save()
dba_group.save()
dba_lead_group.save()
print("=== 临时分配 perm 给 3 个组 (演练结束清理) ===\n")

# =========================
# Case A: superuser
# =========================
print("=== Case A: archery (superuser) ===")
c, u = _force_login("archery")
status, has_ajax, has_link = _check_bottom(c)
print(f"  status={status}, 操作走 AJAX 提示={has_ajax}, admin 链接={has_link}")
assert status == 200, f"A 失败: {status}"
assert has_ajax, "A 失败: superuser 应该有'AJAX 提示'"
assert has_link, "A 失败: superuser 应该有 admin 链接"
print("  ✓ A PASS\n")

# =========================
# Case B: mkq (DBA 组)
# =========================
print("=== Case B: mkq (DBA 组) ===")
c, u = _force_login("mkq")
status, has_ajax, has_link = _check_bottom(c)
print(f"  status={status}, 操作走 AJAX 提示={has_ajax}, admin 链接={has_link}")
assert status == 200
assert has_ajax, "B 失败: DBA 应该有'AJAX 提示'"
assert has_link, "B 失败: DBA 应该有 admin 链接"
print("  ✓ B PASS\n")

# =========================
# Case C: oa_tester_1 (RD 组, 提交人视角) → 隐藏
# =========================
print("=== Case C: oa_tester_1 (研发组, 提交人视角) ===")
c, u = _force_login("oa_tester_1")
status, has_ajax, has_link = _check_bottom(c)
print(f"  status={status}, 操作走 AJAX 提示={has_ajax}, admin 链接={has_link}")
assert status == 200
assert not has_ajax, "C 失败: RD 不应该看到'AJAX 提示'"
assert not has_link, "C 失败: RD 不应该看到 admin 链接"
print("  ✓ C PASS (底部隐藏)\n")

# =========================
# Case D: gyf (DBA组长组)
# =========================
print("=== Case D: gyf (DBA组长组) ===")
c, u = _force_login("gyf")
status, has_ajax, has_link = _check_bottom(c)
print(f"  status={status}, 操作走 AJAX 提示={has_ajax}, admin 链接={has_link}")
assert status == 200
assert has_ajax, "D 失败: DBA组长 应该有'AJAX 提示'"
assert has_link, "D 失败: DBA组长 应该有 admin 链接"
print("  ✓ D PASS\n")

# 清理
for grp, orig in [(rd_group, original_rd), (dba_group, original_dba), (dba_lead_group, original_dba_lead)]:
    grp.permissions.set(orig)
    grp.save()
print("=== 清理: 还原 3 组 perm 列表 ===")
for grp, orig in [(rd_group, original_rd), (dba_group, original_dba), (dba_lead_group, original_dba_lead)]:
    assert set(grp.permissions.all()) == orig, f"清理失败: {grp.name}"
print("  ✓ 清理彻底\n")

print("=== ALL PASS: 4 Case ===")
print("底部 AJAX 提示 + admin 链接, 提交人视角隐藏, DBA/管理员视角保留")
