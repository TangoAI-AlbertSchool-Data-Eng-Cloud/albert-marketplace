"""Step 3: loaded values against the CSVs, column by column, compared by md5.

Each side joins a row's columns with tabs and the rows with newlines, sorted by
the key; empty CSV fields match NULL or '' in the database.
"""
import csv
import hashlib
import subprocess
import sys
from pathlib import Path

csv.field_size_limit(2**31 - 1)
CSV_DIR = sys.argv[1]
REPO = str(Path(__file__).resolve().parents[1])

# table, columns, key, numeric key
TABLES = [
    ("customer", ["c_id", "fname", "lname", "phone", "email", "pwd"], "c_id", False),
    ("shipping_details", ["address_id", "street_address", "city", "state", "zip", "country", "phone"], "address_id", True),
    ("payment_details", ["payment_id", "card_no", "cvv", "expiry_date", "billing_address"], "payment_id", True),
    ("subscription", ["subscription_id", "c_id", "start_date", "end_date"], "subscription_id", True),
    ("seller", ["seller_id", "seller_type"], "seller_id", False),
    ("review", ["review_id", "buyer_id", "r_desc", "title", "rating", "seller_product_flag"], "review_id", True),
    ("product", ["p_id", "p_name", "p_desc", "price", "qty", "category_id"], "p_id", False),
    ("orders", ["order_id", "buyer_id", "discount_id", "payment_id", "order_date"], "order_id", True),
]


def csv_md5(table, cols, key, numeric):
    with open(f"{CSV_DIR}/{table}.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=(lambda r: int(r[key])) if numeric else (lambda r: r[key].encode("utf-8")))
    text = "\n".join("\t".join(r[c] for c in cols) for r in rows)
    return len(rows), hashlib.md5(text.encode("utf-8")).hexdigest()


def db_md5(table, cols, key, numeric):
    row = "concat(" + ", E'\\t', ".join(f"coalesce({c}::text, '')" for c in cols) + ")"
    order = key if numeric else f'{key} COLLATE "C"'
    sql = f"SELECT count(*) || ' ' || md5(coalesce(string_agg({row}, E'\\n' ORDER BY {order}), '')) FROM {table}"
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "marketplace", "-XAt", "-c", sql],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode:
        raise SystemExit(out.stderr)
    n, digest = out.stdout.split()
    return int(n), digest


for table, cols, key, numeric in TABLES:
    c = csv_md5(table, cols, key, numeric)
    d = db_md5(table, cols, key, numeric)
    print(f"{table:17} csv {c[0]:>7} {c[1]}  db {d[0]:>7} {d[1]}  {'identical' if c == d else 'DIFFERENT'}")
