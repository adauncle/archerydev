# -*- coding: utf-8 -*-
"""测 gh-ost 任务管理列表页可见性 (DBA 全量 / RD 提交人视角)。

4 Case 演练:
  A. archery (superuser) → 全量 (46 条)
  B. mkq (DBA 组) → 全量 (46 条) — 没被分配 perm 也能看? 不能, 这里是假设 DBA 被分配了
  C. oa_tester_1 (研发组) → 只看自己提交的 N 条 + 头部提示
  D. gyf (DBA组长组) → 全量 (46 条)

预期:
  - mkq / gyf 需有 view_ddlghosttask perm 才能 200, 没 perm → 403 (C 方案守卫)
  - oa_tester_1 需有 view_ddlghosttask perm (演练时手动加 + 清理)
  - 列表数比较: 全量 vs RD 自己提交
  - 头部文案: "(全量)" vs "提交人视角"
  - 表格内"提交人"列出现
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
from sql.extensions.ddl_gh_ost.views import _is_admin_or_dba


def _force_login(username: str) -> tuple:
    c = Client()
    u = Users.objects.get(username=username)
    c.force_login(u, backend="django.contrib.auth.backends.ModelBackend")
    return c, u


def _check_admin_list(c: Client) -> tuple:
    """访问 /gh_ost/admin_list/, 返回 (status, body, task_count_in_body, has_full_label, has_self_label)"""
    r = c.get("/gh_ost/admin_list/")
    body = r.content.decode("utf-8", "replace")
    # task 数量: 找 gh-ost-tasks 表格里 tbody 内的 <tr>, 跳过 thead
    import re
    tbody_match = re.search(r'<tbody>(.*?)</tbody>', body, re.DOTALL)
    if tbody_match:
        tbody_html = tbody_match.group(1)
        # 匹配 <tr class="..."> 或 <tr> (含 is_terminal=False 时的 class="")
        task_count = len(re.findall(r'<tr[^>]*>', tbody_html))
    else:
        task_count = 0
    has_full_label = "(全量)" in body
    has_self_label = "提交人视角" in body or "您自己提交" in body
    has_engineer_col = "<th>提交人</th>" in body
    return r.status_code, body, task_count, has_full_label, has_self_label, has_engineer_col


PERM = "ddl_gh_ost.view_ddlghosttask"
view_perm = Permission.objects.get(content_type__app_label="ddl_gh_ost", codename="view_ddlghosttask")

# 拿各组 (备用, 演练时可能需要临时分配)
rd_group = Group.objects.get(name="研发")
dba_group = Group.objects.get(name="DBA")
dba_lead_group = Group.objects.get(name="DBA组长")

# 备份原始 perm
original_rd = set(rd_group.permissions.all())
original_dba = set(dba_group.permissions.all())
original_dba_lead = set(dba_lead_group.permissions.all())

# 全局数据
print(f"=== 全局 DdlGhostTask 总数: {DdlGhostTask.objects.count()} ===")
print(f"  oa_tester_1 提交的 task: {DdlGhostTask.objects.filter(workflow__engineer='oa_tester_1').count()}")
print(f"  archery 提交的 task: {DdlGhostTask.objects.filter(workflow__engineer='archery').count()}")
print(f"  mkq 提交的 task: {DdlGhostTask.objects.filter(workflow__engineer='mkq').count()}")
print(f"  gyf 提交的 task: {DdlGhostTask.objects.filter(workflow__engineer='gyf').count()}")
print()

# 确保测试用户都有 perm (演练临时分配, 结束清理)
rd_group.permissions.add(view_perm)
dba_group.permissions.add(view_perm)
dba_lead_group.permissions.add(view_perm)
rd_group.save()
dba_group.save()
dba_lead_group.save()
print("=== 临时分配: 给'研发'/'DBA'/'DBA组长' 都加 view_ddlghosttask ===\n")

# =========================
# Case A: superuser
# =========================
print("=== Case A: archery (superuser) ===")
c, u = _force_login("archery")
print(f"  _is_admin_or_dba={_is_admin_or_dba(u)}, is_superuser={u.is_superuser}")
status, body, tc, has_full, has_self, has_eng = _check_admin_list(c)
print(f"  status={status}, task_count={tc}, (全量)文案={has_full}, 提交人视角文案={has_self}, 提交人列={has_eng}")
assert status == 200, f"A 失败: {status}"
assert has_full, "A 失败: superuser 应该有'(全量)'文案"
assert not has_self, "A 失败: superuser 不应该有'提交人视角'文案"
assert has_eng, "A 失败: 应该始终有'提交人'列"
print("  ✓ A PASS\n")

# =========================
# Case B: mkq (DBA 组)
# =========================
print("=== Case B: mkq (DBA 组) ===")
c, u = _force_login("mkq")
print(f"  _is_admin_or_dba={_is_admin_or_dba(u)}, groups={[g.name for g in u.groups.all()]}")
status, body, tc, has_full, has_self, has_eng = _check_admin_list(c)
print(f"  status={status}, task_count={tc}, (全量)文案={has_full}")
assert status == 200, f"B 失败: {status}"
assert has_full, "B 失败: DBA 应该有'(全量)'文案"
assert not has_self, "B 失败: DBA 不应该有'提交人视角'文案"
print("  ✓ B PASS (DBA 全量)\n")

# =========================
# Case C: oa_tester_1 (RD 组, 提交人视角)
# =========================
print("=== Case C: oa_tester_1 (研发组) ===")
c, u = _force_login("oa_tester_1")
oa_own_count = DdlGhostTask.objects.filter(workflow__engineer="oa_tester_1").count()
print(f"  _is_admin_or_dba={_is_admin_or_dba(u)}, groups={[g.name for g in u.groups.all()]}")
print(f"  oa_tester_1 实际提交 task 数: {oa_own_count}")
status, body, tc, has_full, has_self, has_eng = _check_admin_list(c)
print(f"  status={status}, task_count={tc}, (全量)文案={has_full}, 提交人视角文案={has_self}")
assert status == 200, f"C 失败: {status}"
assert not has_full, "C 失败: RD 不应该有'(全量)'文案"
assert has_self, "C 失败: RD 应该有'提交人视角'文案"
assert tc == oa_own_count, f"C 失败: task 数 {tc} != oa_tester_1 提交数 {oa_own_count}"
print(f"  ✓ C PASS (RD 提交人视角, 列表数 {tc} == 自己提交数 {oa_own_count})\n")

# =========================
# Case D: gyf (DBA组长组)
# =========================
print("=== Case D: gyf (DBA组长组) ===")
c, u = _force_login("gyf")
print(f"  _is_admin_or_dba={_is_admin_or_dba(u)}, groups={[g.name for g in u.groups.all()]}")
status, body, tc, has_full, has_self, has_eng = _check_admin_list(c)
print(f"  status={status}, task_count={tc}, (全量)文案={has_full}")
assert status == 200, f"D 失败: {status}"
assert has_full, "D 失败: DBA组长 应该有'(全量)'文案"
assert not has_self, "D 失败: DBA组长 不应该有'提交人视角'文案"
print("  ✓ D PASS (DBA组长 全量)\n")

# =========================
# Case E: 验证 _is_admin_or_dba 各种 edge case
# =========================
print("=== Case E: _is_admin_or_dba 单元测试 ===")
# E.1 匿名用户
from django.contrib.auth.models import AnonymousUser
assert _is_admin_or_dba(AnonymousUser()) == False, "E.1 失败: 匿名应 False"
print("  ✓ E.1 匿名用户 → False")
# E.2 None
assert _is_admin_or_dba(None) == False, "E.2 失败: None 应 False"
print("  ✓ E.2 None → False")
# E.3 普通登录用户
_, u = _force_login("oa_tester_1")
assert _is_admin_or_dba(u) == False, "E.3 失败: RD 应 False"
print("  ✓ E.3 oa_tester_1 (RD) → False")
# E.4 superuser
_, u = _force_login("archery")
assert _is_admin_or_dba(u) == True, "E.4 失败: superuser 应 True"
print("  ✓ E.4 archery (superuser) → True")
# E.5 mkq (DBA)
_, u = _force_login("mkq")
assert _is_admin_or_dba(u) == True, "E.5 失败: DBA 应 True"
print("  ✓ E.5 mkq (DBA) → True\n")

# =========================
# 清理: 还原所有组 perm
# =========================
print("=== 清理: 还原组 perm 到原始状态 ===")
for grp, orig in [(rd_group, original_rd), (dba_group, original_dba), (dba_lead_group, original_dba_lead)]:
    grp.permissions.set(orig)
    grp.save()
    print(f"  {grp.name}: 还原 {len(orig)} 个 perm")

# 验证清理彻底
for grp, orig in [(rd_group, original_rd), (dba_group, original_dba), (dba_lead_group, original_dba_lead)]:
    assert set(grp.permissions.all()) == orig, f"清理失败: {grp.name}"
print("  ✓ 清理彻底")

print("\n=== ALL PASS: 4 Case + 5 单元测试 + 清理 ===")
print("C 方案延伸 (可见性细分) 验证通过")
print("  - DBA / DBA组长 / superuser 看全量 (运维视角)")
print("  - RD 等其他用户只看自己提交的 task (提交人视角)")
print("  - 头部文案 + 提交人列跟随视角切换")
