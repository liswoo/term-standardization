"""Sample-data lookup for domains flagged 개인정보여부 (is_personal_info).

A metadata catalog's "personal info" flag is meaningless on its own - it only
means something if it points at an actual (here: synthetic) operational
table/column. This module is the read side of that: given a domain code,
find what mockops_* table/column it's mapped to (domain_data_mappings) and
return a small sample of that table's synthetic data.

ALLOWLISTED_MOCKOPS_TABLES is the single source of truth for which tables/
columns this can ever query. table_name/column_name can't be parameterized
as SQL identifiers (only values can be bound with %s), so they're interpolated
via f-string below - safe ONLY because both are checked against this allowlist
first. Never remove that check, and never let a mapping's table_name/column_name
reach sample_rows() unfiltered.
"""
from . import db

ALLOWLISTED_MOCKOPS_TABLES = {
    "mockops_customers": ["name", "resident_number", "phone", "email", "address"],
}

def sample_rows(table_name: str, column_name: str, limit: int = 5) -> dict:
    columns = ALLOWLISTED_MOCKOPS_TABLES.get(table_name)
    if not columns or column_name not in columns:
        return {"ok": False, "error": "UNKNOWN_TABLE_OR_COLUMN"}
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {column_name} FROM {table_name} ORDER BY created_at DESC LIMIT %s",
            (limit,)).fetchall()
    return {"ok": True, "table_name": table_name, "column_name": column_name,
        "sample": [r[column_name] for r in rows]}

def mappings_for_domain(domain_code: str) -> list[dict]:
    with db.connect() as conn:
        return conn.execute("SELECT table_name,column_name FROM domain_data_mappings WHERE domain_code=%s",
            (domain_code,)).fetchall()

def sample_data_for_domain(domain_code: str, limit: int = 5) -> list[dict]:
    results = []
    for mapping in mappings_for_domain(domain_code):
        result = sample_rows(mapping["table_name"], mapping["column_name"], limit)
        if result["ok"]:
            results.append(result)
    return results
