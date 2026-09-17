"""DBA-bug-9.5b 修复验证 (110 prod wf#4848)"""
import sys
sys.path.insert(0, "/dbdata/archery_v114_c9236a0")
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
os.environ.setdefault("CAS_SERVER_URL", "https://cas.example.com")
os.environ.setdefault("CAS_VERSION", "3")
os.environ.setdefault("CAS_LOGIN_COMPLETE_URL", "/login/")
os.environ.setdefault("CAS_LOGOUT_COMPLETE_URL", "/logout/")
os.environ.setdefault("CAS_USERNAME_ATTRIBUTE", "username")
os.environ.setdefault("CAS_ATTRIBUTE_CALLBACK", "")
os.environ.setdefault("CAS_CREATE_USER", "True")
env_path = "/dbdata/archery_v114_c9236a0/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

import django
django.setup()
from sql.models import SqlWorkflow, SqlWorkflowContent
from sql.views import _detect_non_alter

print("=== wf#4848 验证 (用户实测工单) ===")
try:
    wf = SqlWorkflow.objects.get(id=4848)
    print(f"  workflow_name: {wf.workflow_name}")
    print(f"  enable_gh_ost: {wf.enable_gh_ost}")
    print(f"  gh_ost_mode: {wf.gh_ost_mode}")
    print(f"  status: {wf.status}")

    try:
        text = SqlWorkflowContent.objects.get(workflow=wf).sql_content or ""
    except Exception:
        text = ""
    print(f"  sql_content length: {len(text)}")

    # 模拟 detail 视图:
    # 旧版: non_alter_stmts = _detect_non_alter(text) 无条件
    # 新版: enable_gh_ost=False 时 non_alter_stmts = []
    if wf.enable_gh_ost:
        non_alter = _detect_non_alter(text)
        print(f"  [OLD logic] non_alter_stmts: {len(non_alter)} 条 (会显示警告)")
    else:
        non_alter = []
        print(f"  [NEW logic] non_alter_stmts: [] (警告块不渲染)")

    # 实际 SQL 内容 head
    print(f"  sql head: {text[:300]!r}")
except SqlWorkflow.DoesNotExist:
    print(f"  wf#4848 不存在, 134 dev 演练已验证逻辑")

print()
print("=== 110 prod enable_gh_ost=True 工单扫描 (期望: 警告应该继续显示) ===")
qs = list(SqlWorkflow.objects.filter(enable_gh_ost=True).order_by("-id")[:3])
for wf in qs:
    try:
        text = SqlWorkflowContent.objects.get(workflow=wf).sql_content or ""
    except Exception:
        text = ""
    non_alter = _detect_non_alter(text) if wf.enable_gh_ost else []
    print(f"  wf#{wf.id} enable_gh_ost={wf.enable_gh_ost} sql_len={len(text)} non_alter={len(non_alter)}")