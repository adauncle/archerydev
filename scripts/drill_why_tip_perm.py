"""drill_why_tip_perm.py

业务: 8/13 用户反馈, 点"为什么?"按钮弹窗里"权限组管理"链接对 RD 没用
     (RD 没 admin 后台访问权), 期望对非管理员/dba组用户隐藏。

修法: task_list.html 'gh-ost-scope-tip' 弹窗里去掉"权限组管理"链接
      (弹窗本身只在 RD 视角 {% else %} 块渲染, DBA 视角不渲染弹窗,
       所以直接去掉链接最干净, 不需要 is_admin_or_dba 守卫)。

注意: base.html 侧边栏菜单里有 /admin/auth/group/ "权限组管理" 链接,
     这是给所有用户看的"其他配置管理"菜单项, 不属于本任务修复范围 (本任务只修弹窗里的)。

演练 (134 dev 4 Case + read-only):
  验证: 弹窗 (id="gh-ost-scope-tip") 里没有 "权限组管理" 链接
  A. superuser archery (DBA 视角, 弹窗不渲染) → 弹窗内容里没"权限组管理"
  B. mkq (DBA)              → 同上
  C. oa_tester_1 (RD, 弹窗渲染) → 弹窗内容里没"权限组管理" 链接
  D. gyf (DBA组长)          → DBA 视角, 弹窗不渲染

清理: 演练后 perm 全部还原。
"""
import os
import sys
import re
import django

sys.path.insert(0, '/opt/archery/prod')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archery.settings')
django.setup()

from django.conf import settings as dj_settings
if 'testserver' not in dj_settings.ALLOWED_HOSTS:
    dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver', '127.0.0.1']

from django.contrib.auth.models import Permission
from django.test import Client

from sql.models import Users as User


def grant_perm(user, codename):
    perm = Permission.objects.get(codename=codename, content_type__app_label="ddl_gh_ost")
    user.user_permissions.add(perm)


def revoke_perm(user, codename):
    perm = Permission.objects.get(codename=codename, content_type__app_label="ddl_gh_ost")
    user.user_permissions.remove(perm)


def setup_users():
    return (
        User.objects.get(username="archery"),
        User.objects.get(username="mkq"),
        User.objects.get(username="oa_tester_1"),
        User.objects.get(username="gyf"),
    )


def extract_tip_html(body: str) -> str:
    """从 body 里抓 <div id="gh-ost-scope-tip">...</div> 内容"""
    m = re.search(r'<div\s+id="gh-ost-scope-tip"[^>]*>(.*?)</div>', body, re.DOTALL)
    if m:
        return m.group(1)
    return ""  # 弹窗没渲染


def drill_case(name, user, expect_tip_rendered: bool):
    """演练 admin_list 页面, 验证 '为什么?' 弹窗里没 '权限组管理' 链接"""
    print(f"\n{'='*60}\nCase: {name}  user={user.username}\n{'='*60}")
    c = Client(SERVER_NAME="127.0.0.1")
    c.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    r = c.get("/gh_ost/admin_list/")
    print(f"  [GET /gh_ost/admin_list/] status={r.status_code}")
    body = r.content.decode("utf-8", errors="replace")

    tip_html = extract_tip_html(body)
    has_tip = bool(tip_html)
    print(f"  [为什么?弹窗] 渲染: {has_tip}")

    if expect_tip_rendered:
        # RD 视角: 弹窗应渲染
        assert has_tip, f"{name}: RD 视角应渲染'为什么?'弹窗"
        # 弹窗里不应再有 "权限组管理" 链接/文本
        has_perm_text = "权限组管理" in tip_html
        has_perm_link = 'href="/admin/auth/group/"' in tip_html
        print(f"  [弹窗内 '权限组管理' 文本] 出现: {has_perm_text}")
        print(f"  [弹窗内 '权限组管理' 链接] 渲染: {has_perm_link}")
        assert not has_perm_text, f"{name}: 弹窗内不应有'权限组管理'文本 (RD 没用)"
        assert not has_perm_link, f"{name}: 弹窗内不应有 /admin/auth/group/ 链接"
        print(f"  [PASS] 弹窗渲染但'权限组管理'链接不渲染 ✓")
    else:
        # DBA 视角: 弹窗不渲染 (走 if 分支)
        assert not has_tip, f"{name}: DBA 视角不应渲染'为什么?'弹窗"
        print(f"  [PASS] DBA 视角: 弹窗不渲染 ✓")


def main():
    archery, mkq, oa_tester_1, gyf = setup_users()

    print("\n[1] 准备 view perm (admin_list 页面访问需要)...")
    for u in [mkq, oa_tester_1, gyf]:
        grant_perm(u, "view_ddlghosttask")

    # superuser + DBA + DBA组长: is_admin_or_dba=True → 弹窗不渲染
    # RD (oa_tester_1): is_admin_or_dba=False → 弹窗渲染, 但不应有"权限组管理"链接
    drill_case("A. superuser archery (DBA 视角)", archery, expect_tip_rendered=False)
    drill_case("B. mkq (DBA)", mkq, expect_tip_rendered=False)
    drill_case("C. oa_tester_1 (RD, 弹窗应渲染但无链接)", oa_tester_1, expect_tip_rendered=True)
    drill_case("D. gyf (DBA组长)", gyf, expect_tip_rendered=False)

    print("\n[2] 清理 perm 状态...")
    for u in [mkq, oa_tester_1, gyf]:
        revoke_perm(u, "view_ddlghosttask")

    print("\n[ALL OK] 4 Case 演练完成")


if __name__ == "__main__":
    main()
