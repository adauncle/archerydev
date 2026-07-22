"""
setup_test_group.py - 新建一个 "测试组" 资源组，把 测试 MySQL 8.0 加进去
"""
import os
import sys
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django
django.setup()

from sql.models import ResourceGroup, Instance, Users

print("=" * 60)
print("1) 看下 archery 用户的资源组关联")
print("=" * 60)
admin_user = Users.objects.get(username="archery")
print(f"  archery user id={admin_user.id}, is_superuser={admin_user.is_superuser}")
if admin_user.is_superuser:
    print(f"  → 超级用户：可以看到所有 ResourceGroup（不过实例列表还是按 resource_group__in 关联筛选的）")

print()
print("=" * 60)
print("2) 新建 '测试组' ResourceGroup")
print("=" * 60)
test_group, created = ResourceGroup.objects.get_or_create(
    group_name="测试组",
    defaults={
        "group_parent_id": 0,
        "group_sort": 999,
        "group_level": 1,
        "ding_webhook": "",
        "feishu_webhook": "",
        "qywx_webhook": "",
        "is_deleted": 0,
    },
)
print(f"  ResourceGroup: {test_group.group_name} (group_id={test_group.group_id}, created={created})")

print()
print("=" * 60)
print("3) 把 archery 用户加进测试组（这样 archery 用户能看到这个组）")
print("=" * 60)
admin_user.resource_group.add(test_group)
print(f"  archery -> 测试组 (关联已建)")

print()
print("=" * 60)
print("4) 把 '测试 MySQL 8.0' 实例加进测试组")
print("=" * 60)
test_inst = Instance.objects.get(instance_name="测试 MySQL 8.0")
test_inst.resource_group.add(test_group)
print(f"  测试 MySQL 8.0 (id={test_inst.id}) -> 测试组")

print()
print("=" * 60)
print("5) 最终状态")
print("=" * 60)
print(f"  ResourceGroup 数: {ResourceGroup.objects.filter(is_deleted=0).count()}")
for g in ResourceGroup.objects.filter(is_deleted=0).order_by("group_sort"):
    n_inst = g.instance_set.count() if hasattr(g, "instance_set") else 0
    n_user = g.users.count()
    marker = " ← NEW" if g.group_name == "测试组" else ""
    print(f"    - group_id={g.group_id:2d} {g.group_name!r:30s} (instances={n_inst}, users={n_user}){marker}")
print()
print(f"  Instance 数: {Instance.objects.count()}")
for x in Instance.objects.all():
    rg_names = [g.group_name for g in x.resource_group.all()]
    print(f"    - id={x.id} {x.instance_name!r:25s} type={x.db_type} groups={rg_names}")
print()
print("DONE - 刷新 /submitsql/ 应该能看到 '测试组' 下拉选项")
