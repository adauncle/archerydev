import re
sql = "ALTER TABLE `hly_billing`.`consume_flow`\nADD INDEX `idx_create_time` (`create_time`)"
print("SQL:", repr(sql))

# column_diff.py 的 regex (line 402-405)
m1 = re.match(
    r"^\s*ALTER\s+TABLE\s+"
    r"(?:(?P<schema>`?[^`\s.()]+`?)\.)?`?(?P<table>[^`\s(]+)`?",
    sql.strip(),
    re.IGNORECASE,
)
print("column_diff.py regex:", m1.group("schema") if m1 else None, "/", m1.group("table") if m1 else None)

# views.py 的 regex (line 258)
m2 = re.match(
    r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
    sql.strip(),
    re.IGNORECASE,
)
print("views.py regex (line 258, DBA-bug-1 修了 use/注释 但没改 regex):", m2.group("schema") if m2 else None, "/", m2.group("table") if m2 else None)

# views.py 加上 use/注释预处理后
def _parse_first_alter(sql_content):
    if not sql_content:
        return None
    cleaned_lines = []
    for line in sql_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if re.match(r"^\s*use\s+", stripped, re.IGNORECASE):
            continue
        cleaned_lines.append(stripped)
    cleaned = "\n".join(cleaned_lines).strip()
    m = re.match(
        r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?",
        cleaned,
        re.IGNORECASE,
    )
    if not m:
        return None
    schema = (m.group("schema") or "").strip("`")
    table = (m.group("table") or "").strip("`")
    return {"db": schema or None, "table": table or None, "full": m.group(0)}

print()
print("views.py _parse_first_alter (DBA-bug-1 修后):", _parse_first_alter(sql))
