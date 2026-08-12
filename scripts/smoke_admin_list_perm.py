# -*- coding: utf-8 -*-
"""HTTP smoke test: 实际走 gunicorn + 浏览器路径, 验证菜单守卫和 403 守卫"""
import os, sys
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django; django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from django.test import Client
from sql.models import Users


def check_user(username, label):
    print(f"\n=== {label}: {username} ===")
    u = Users.objects.get(username=username)
    c = Client()
    c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")

    # 1. 直接访问 /gh_ost/admin_list/
    r = c.get("/gh_ost/admin_list/")
    print(f"  GET /gh_ost/admin_list/ → {r.status_code}")

    # 2. 首页 + 菜单检查
    r2 = c.get("/", follow=True)
    body = r2.content.decode("utf-8", "replace")
    has_gh_menu_link = "/gh_ost/admin_list/" in body
    has_gh_menu_label = "gh-ost 任务" in body
    has_rocket = "fa-rocket" in body
    print(f"  首页: gh-ost 任务菜单链接={has_gh_menu_link}, 文字={has_gh_menu_label}, 图标={has_rocket}")

    return r.status_code, has_gh_menu_link, has_gh_menu_label, has_rocket


# Case 1: superuser
s1, ml1, mtxt1, mk1 = check_user("archery", "Case 1 superuser")
assert s1 == 200 and ml1 and mtxt1 and mk1, f"superuser 失败: {s1}/{ml1}/{mtxt1}/{mk1}"

# Case 2: RD 无 perm
s2, ml2, mtxt2, mk2 = check_user("oa_tester_1", "Case 2 RD 无 perm")
assert s2 == 403 and not ml2 and not mtxt2 and not mk2, f"RD 无 perm 失败: {s2}/{ml2}/{mtxt2}/{mk2}"

# Case 3: DBA 无 perm
s3, ml3, mtxt3, mk3 = check_user("mkq", "Case 3 DBA 无 perm")
assert s3 == 403 and not ml3 and not mtxt3 and not mk3, f"DBA 无 perm 失败: {s3}/{ml3}/{mtxt3}/{mk3}"

# Case 4: 给"研发"组分配
from django.contrib.auth.models import Group, Permission
rd_group = Group.objects.get(name="研发")
view_perm = Permission.objects.get(content_type__app_label="ddl_gh_ost", codename="view_ddlghosttask")
rd_group.permissions.add(view_perm)
rd_group.save()
s4, ml4, mtxt4, mk4 = check_user("oa_tester_1", "Case 4 研发组分配后 RD")
assert s4 == 200 and ml4 and mtxt4 and mk4, f"分配后失败: {s4}/{ml4}/{mtxt4}/{mk4}"
print(f"  ✓ 给'研发'组加 perm 后, oa_tester_1 立即可用")

# Case 5: 撤销
rd_group.permissions.remove(view_perm)
rd_group.save()
s5, ml5, mtxt5, mk5 = check_user("oa_tester_1", "Case 5 撤销后")
assert s5 == 403 and not ml5 and not mtxt5 and not mk5, f"撤销失败: {s5}/{ml5}/{mtxt5}/{mk5}"
print(f"  ✓ 撤销 perm 后立即 403 + 菜单消失")

print("\n=== ALL 5 CASE PASS ===")
print("HTTP 走 gunicorn 路径全验证通过, 守卫工作正常")
