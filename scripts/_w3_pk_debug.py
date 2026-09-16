"""debug _resolve_insert_pk_values"""
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()

from sql.models import Instance
from sql.utils.pk_conflict_check import _extract_inserts, _resolve_insert_pk_values, _fetch_columns_order

instance = Instance.objects.get(id=2)
db = "archery_dev"
table = "accesscard_account"

# 134 dev cols order
cols = _fetch_columns_order(instance, db, table)
print("cols:", cols)

# 测试 SQL
sql = "INSERT INTO `accesscard_account` VALUES (10000, 'test', 'test')"
inserts = _extract_inserts(sql)
print("inserts:", inserts)

if inserts:
    ins = inserts[0]
    pk_col, pk_values = _resolve_insert_pk_values(ins, instance, db)
    print("pk_col:", pk_col, "pk_values:", pk_values)