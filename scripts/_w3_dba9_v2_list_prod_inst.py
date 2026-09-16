"""看 110 prod 上有哪些 Instance"""
import os
import sys

sys.path.insert(0, "/dbdata/archery_v114_c9236a0")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
import django

django.setup()

from sql.models import Instance  # noqa: E402

for inst in Instance.objects.all().order_by("id")[:15]:
    print(f"id={inst.id} name={inst.instance_name} host={inst.host}:{inst.port}")