"""debug: 看正则匹配 column 名"""
import re

# 1. 现有 verbose 模式
m = re.match(
    r"""
    (?:MODIFY|CHANGE)\s+(?:COLUMN\s+)?
    `?(?P<name>[^`\s(]+)`?
    (?P<definition>
        (?:[^,]+?)\s+
        (?:CHARACTER\s+SET\s+\S+\s+)?
        (?:COLLATE\s+\S+\s+)?
        (?:NOT\s+NULL\s+)?
        (?:NULL\s+)?
        (?:DEFAULT\s+\S+(?:\s*\([^)]*\))?\s*)?
        (?:COMMENT\s+'(?:[^']|'')*'\s*)?
    )
    """,
    "MODIFY COLUMN status VARCHAR(50)",
    re.IGNORECASE | re.VERBOSE,
)
if m:
    print(f"verbose OK: name=[{m.group('name')}] (len={len(m.group('name'))})")
    print(f"  def=[{m.group('definition')}]")
else:
    print("verbose: NO MATCH")

# 2. 不用 verbose
m2 = re.match(
    r"(?:MODIFY|CHANGE)\s+(?:COLUMN\s+)?`?(?P<name>[^`\s(]+)`?\s+(?P<definition>(?:[^,]+))",
    "MODIFY COLUMN status VARCHAR(50)",
    re.IGNORECASE,
)
if m2:
    print(f"non-verbose: name=[{m2.group('name')}] (len={len(m2.group('name'))})")
    print(f"  def=[{m2.group('definition')}]")

# 3. 测 "id BIGINT"
m3 = re.match(
    r"""
    (?:MODIFY|CHANGE)\s+(?:COLUMN\s+)?
    `?(?P<name>[^`\s(]+)`?
    (?P<definition>
        (?:[^,]+?)\s+
    )
    """,
    "MODIFY COLUMN id BIGINT",
    re.IGNORECASE | re.VERBOSE,
)
if m3:
    print(f"\nid case verbose: name=[{m3.group('name')}]")
    print(f"  def=[{m3.group('definition')}]")
