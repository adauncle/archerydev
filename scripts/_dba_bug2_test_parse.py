import re
sqls = [
    # 图1 consume_flow SQL (反引号 schema + table + 多行)
    "ALTER TABLE `hly_billing`.`consume_flow`\nADD INDEX `idx_create_time` (`create_time`)",
    # 图2 modify column SQL
    "ALTER TABLE `hly_billing`.`consume_flow`\nmodify column `vehicle_plate` varchar(128) DEFAULT NULL COMMENT '车牌'",
    # 普通有反引号
    "ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX `idx_x` (`y`)",
    # 老的已经修过的
    "alter table waybill_union_carrier drop index idx_way_bill_id",
    # 老的 use + ALTER
    "use hly_platform;\nalter table waybill_union_carrier drop index idx_way_bill_id",
]
pat = r"^\s*ALTER\s+TABLE\s+(?:(?P<schema>[^`\s.()]+)\.)?`?(?P<table>[^`\s(]+)`?"

# 走完整 _parse_first_alter 逻辑(加 use/注释/空行预处理)
def _parse_first_alter(sql):
    if not sql:
        return None
    cleaned_lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if re.match(r"^\s*use\s+", stripped, re.IGNORECASE):
            continue
        cleaned_lines.append(stripped)
    cleaned = "\n".join(cleaned_lines).strip()
    m = re.match(pat, cleaned, re.IGNORECASE)
    if not m:
        return None
    schema = (m.group("schema") or "").strip("`")
    table = (m.group("table") or "").strip("`")
    return {"db": schema or None, "table": table or None, "full": m.group(0)}

for sql in sqls:
    p = _parse_first_alter(sql)
    print(f"SQL: {sql[:80]!r}")
    print(f"  parsed: {p}")
    print()
