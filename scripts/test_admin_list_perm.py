# -*- coding: utf-8 -*-
"""测 gh-ost 任务管理列表页权限守卫 (C 方案: view_ddlghosttask perm)。

4 Case 演练:
  A. archery (superuser) → 200, 菜单显示
  B. mkq (DBA, 有 view perm) → 200, 菜单显示
  C. oa_tester_1 (RD, 无 perm) → 403, 菜单不显示
  D. gyf (其他组, 无 perm) → 403, 菜单不显示
  E. 给"研发"组分配 view_ddlghosttask perm → oa_tester_1 重新登录 → 200, 菜单出现
  F. 撤销 perm → oa_tester_1 重新登录 → 403 (清理, 避免污染)
"""
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django; django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from sql.models import Users


def _has_perm(user, perm: str) -> bool:
    return user.has_perm(perm)


def _force_login(username: str) -> Client:
    c = Client()
    u = Users.objects.get(username=username)
    c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")
    return c, u


def _check_admin_list(c: Client) -> tuple:
    """访问 /gh_ost/admin_list/ + 看菜单。返回 (status, has_menu)。"""
    r = c.get("/gh_ost/admin_list/", follow=False)
    status = r.status_code
    has_menu = False
    if status == 200:
        # 200 时看 admin_list 页面 body, 不看菜单
        body = r.content.decode("utf-8", "replace")
        has_menu_in_body = "gh-ost 任务" in body or "DBA 运维入口" in body
    else:
        has_menu_in_body = False
    # 菜单检查: 走 / 跳到 /sqlworkflow/, 渲染时侧边栏
    r2 = c.get("/", follow=True)
    body2 = r2.content.decode("utf-8", "replace")
    has_menu = "/gh_ost/admin_list/" in body2 and "fa-rocket" in body2
    return status, has_menu, has_menu_in_body


PERM = "ddl_gh_ost.view_ddlghosttask"
print(f"=== 测 perm: {PERM} ===\n")

# 拿 perm 对象
view_perm = Permission.objects.get(content_type__app_label="ddl_gh_ost", codename="view_ddlghosttask")
print(f"  view_perm: id={view_perm.id} name={view_perm.name}")

# 拿"研发"组
rd_group = Group.objects.get(name="研发")
print(f"  研发组: id={rd_group.id} 当前 perm 数={rd_group.permissions.count()}")

# 备份原始 perm 列表
original_perms = list(rd_group.permissions.all())
print(f"  备份: 研发组有 {len(original_perms)} 个 perm 备份")

# 测初始状态: 研发组应该没有 view_ddlghosttask
assert view_perm not in original_perms, "测试前提失败: 研发组已有 view_ddlghosttask"
print(f"  ✓ 测试前提: 研发组没有 view_ddlghosttask perm\n")

# =========================
# Case A: superuser
# =========================
print("=== Case A: archery (superuser) ===")
c_a, u_a = _force_login("archery")
print(f"  superuser={u_a.is_superuser}, is_staff={u_a.is_staff}")
status, has_menu, _ = _check_admin_list(c_a)
print(f"  /gh_ost/admin_list/ → {status}, 菜单存在={has_menu}")
print(f"  has_perm('view_ddlghosttask')={u_a.has_perm('ddl_gh_ost.view_ddlghosttask')}")
assert status == 200, f"A 失败: superuser 应该 200, 实际 {status}"
assert has_menu, "A 失败: superuser 应该有菜单"
print("  ✓ A PASS\n")

# =========================
# Case B: mkq (DBA, 有 view perm)
# =========================
print("=== Case B: mkq (DBA 组) ===")
c_b, u_b = _force_login("mkq")
print(f"  groups: {[g.name for g in u_b.groups.all()]}")
print(f"  has_perm('view_ddlghosttask')={u_b.has_perm('ddl_gh_ost.view_ddlghosttask')}")
status, has_menu, _ = _check_admin_list(c_b)
print(f"  /gh_ost/admin_list/ → {status}, 菜单存在={has_menu}")
# mkq 是否当前有 perm 不确定 (admin 后台配过), 不强制 200
# 至少要 is_superuser=False
assert not u_b.is_superuser, "B 失败: mkq 不应该是 superuser"
if u_b.has_perm("ddl_gh_ost.view_ddlghosttask"):
    assert status == 200 and has_menu, f"B 失败: 有 perm 但 {status}"
    print("  ✓ B PASS (有 perm, 200 + 菜单)\n")
else:
    # 没 perm → 403, 但说明 mkq 还没被分配
    assert status == 403 and not has_menu, f"B 实际: 无 perm → {status}, 菜单={has_menu}"
    print("  ✓ B PASS (无 perm, 403 + 菜单不显示) — mkq 也需要分配\n")

# =========================
# Case C: oa_tester_1 (RD, 无 perm) → 403
# =========================
print("=== Case C: oa_tester_1 (RD 组, 无 perm) ===")
c_c, u_c = _force_login("oa_tester_1")
print(f"  groups: {[g.name for g in u_c.groups.all()]}")
print(f"  has_perm('view_ddlghosttask')={u_c.has_perm('ddl_gh_ost.view_ddlghosttask')}")
# 确保当前无 perm
assert not u_c.has_perm("ddl_gh_ost.view_ddlghosttask"), "测试前提失败: oa_tester_1 已有 perm"
status, has_menu, _ = _check_admin_list(c_c)
print(f"  /gh_ost/admin_list/ → {status}, 菜单存在={has_menu}")
assert status == 403, f"C 失败: 无 perm 应该 403, 实际 {status}"
assert not has_menu, "C 失败: 无 perm 不应该有菜单"
# 看 403 body 中文提示
r = c_c.get("/gh_ost/admin_list/")
body = r.content.decode("utf-8", "replace")
if "请联系 DBA" in body or "view_ddlghosttask" in body or "权限组" in body:
    print("  ✓ 403 页面含中文权限提示")
else:
    print(f"  ⚠ 403 页面没找到中文提示, body 前 200 字符: {body[:200]!r}")
print("  ✓ C PASS\n")

# =========================
# Case D: gyf (其他组, 无 perm) → 403
# =========================
print("=== Case D: gyf (其他组, 无 perm) ===")
c_d, u_d = _force_login("gyf")
print(f"  groups: {[g.name for g in u_d.groups.all()]}")
print(f"  has_perm('view_ddlghosttask')={u_d.has_perm('ddl_gh_ost.view_ddlghosttask')}")
if u_d.has_perm("ddl_gh_ost.view_ddlghosttask"):
    print("  ⚠ gyf 已有 perm, 跳过 Case D")
else:
    status, has_menu, _ = _check_admin_list(c_d)
    print(f"  /gh_ost/admin_list/ → {status}, 菜单存在={has_menu}")
    assert status == 403, f"D 失败: 无 perm 应该 403, 实际 {status}"
    assert not has_menu, "D 失败: 无 perm 不应该有菜单"
    print("  ✓ D PASS\n")

# =========================
# Case E: 给"研发"组分配 perm → oa_tester_1 → 200
# =========================
print("=== Case E: 给'研发'组分配 view_ddlghosttask ===")
rd_group.permissions.add(view_perm)
rd_group.save()
print(f"  研发组现在有 {rd_group.permissions.count()} 个 perm")
# 重新登录 oa_tester_1 (force_login 会从 DB 拉最新 perm)
c_e, u_e = _force_login("oa_tester_1")
print(f"  重新登录后 has_perm={u_e.has_perm('ddl_gh_ost.view_ddlghosttask')}")
assert u_e.has_perm("ddl_gh_ost.view_ddlghosttask"), "E 失败: 分配后仍无 perm"
status, has_menu, _ = _check_admin_list(c_e)
print(f"  /gh_ost/admin_list/ → {status}, 菜单存在={has_menu}")
assert status == 200, f"E 失败: 分配后应该 200, 实际 {status}"
assert has_menu, "E 失败: 分配后应该有菜单"
print("  ✓ E PASS (给'研发'组分配 perm, oa_tester_1 立即可用)\n")

# =========================
# Case F: 撤销 perm → oa_tester_1 → 403 (清理)
# =========================
print("=== Case F: 撤销 view_ddlghosttask (清理) ===")
rd_group.permissions.remove(view_perm)
rd_group.save()
print(f"  研发组现在有 {rd_group.permissions.count()} 个 perm")
c_f, u_f = _force_login("oa_tester_1")
print(f"  重新登录后 has_perm={u_f.has_perm('ddl_gh_ost.view_ddlghosttask')}")
assert not u_f.has_perm("ddl_gh_ost.view_ddlghosttask"), "F 失败: 撤销后仍有 perm"
status, has_menu, _ = _check_admin_list(c_f)
print(f"  /gh_ost/admin_list/ → {status}, 菜单存在={has_menu}")
assert status == 403, f"F 失败: 撤销后应该 403, 实际 {status}"
assert not has_menu, "F 失败: 撤销后不应该有菜单"
print("  ✓ F PASS (撤销后立即生效)\n")

# 验证清理彻底: 研发组 perm 列表应该跟原始一样
final_perms = list(rd_group.permissions.all())
assert set(final_perms) == set(original_perms), f"清理失败: 研发组 perm 列表变了\n原始: {[p.codename for p in original_perms]}\n现在: {[p.codename for p in final_perms]}"
print(f"  ✓ 清理彻底: 研发组 perm 列表恢复 ({len(final_perms)} 个)")

print("\n=== ALL PASS: 4 Case + 1 分配 + 1 清理 ===")
print("C 方案 0 DB 改动验证通过, DBA 可在 admin 后台自由分配 view_ddlghosttask perm")
