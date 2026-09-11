#!/bin/bash
# 在 134 dev 用 Django 4.2 模板引擎测试 {# #} 注释处理
set -e
cd /opt/archery/prod
export DJANGO_SETTINGS_MODULE=archery.settings
sudo -u archery /opt/archery/prod/venv/bin/python <<'PYEOF'
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()
from django.template import Template, Context

# Test 1: 多行 {# #} 注释
tpl_str = '''{# multi
line
comment #}
<script>
function foo() {
    return 1;
}
</script>'''
print("Test 1 (multi-line hash comment):")
print(repr(Template(tpl_str).render(Context())))
print()

# Test 2: 注释里包含 } 字符
tpl_str2 = '''{# comment with } brace #}
<script>
function foo() {
    return 1;
}
</script>'''
print("Test 2 (comment with } brace):")
print(repr(Template(tpl_str2).render(Context())))
print()

# Test 3: 模仿实际业务 - {# #} 包裹多行中文 + 含 ) 字符
tpl_str3 = '''{# CUSTOM-MODIFIED: 9/11 DBA-bug-3 大表 alert 渲染 helper
 业务: ok=False 但 big_table_alert 不为 None 时 (ADD INDEX/DROP INDEX/RENAME 等非字段变更),
       单独渲染大表 alert 到 modal (没字段 diff) + 主页面 banner
 关联: docs/changelogs/2026-09-11_dba-bug-3-big-table-alert-add-index-drop-index.md #}
<script>
function foo() {
    return 1;
}
</script>'''
print("Test 3 (multiline Chinese comment):")
result = Template(tpl_str3).render(Context())
print(repr(result[:200]))
hash_count = result.count(chr(123) + chr(35))
print(f"  DOUBLE_HASH count: {hash_count}")
PYEOF
