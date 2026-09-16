"""debug case H"""
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()

from sql.models import Instance
from sql.utils.pk_conflict_check import _extract_inserts, _resolve_insert_pk_values

instance = Instance.objects.get(id=2)
db = "archery_dev"
table = "accesscard_account"

sql_h = "INSERT INTO `accesscard_account` VALUES (10000, 'test'), (-1, 'test')"
print("sql_h:", repr(sql_h))
inserts = _extract_inserts(sql_h)
print("inserts[0]:", inserts[0])
ins = inserts[0]
pk_col, pk_values = _resolve_insert_pk_values(ins, instance, db)
print("pk_col:", repr(pk_col))
print("pk_values:", repr(pk_values))
print("types:", [type(v).__name__ for v in pk_values])