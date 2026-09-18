"""Step 4: check calibration.json against the numbers measured in build-spec §5.4."""
import json
import sys

SPEC = """1:0.59 2:0.69 3:0.65 4:0.82 5:0.78 6:0.66 7:0.80 8:0.80 9:0.89 10:0.78
11:0.91 12:0.95 13:0.88 14:0.81 15:0.89 16:0.86 17:0.84 18:0.94 19:1.06 20:1.05
21:1.00 22:0.71 23:1.15 24:0.94 25:0.87 26:0.86 27:0.94 28:0.90 29:0.93 30:0.91
31:0.83 32:0.80 33:0.86 34:0.92 35:0.75 36:0.93 37:1.00 38:1.24 39:1.31 40:1.34
41:1.34 42:1.32 43:1.32 44:1.39 45:1.72 46:1.76 47:1.72 48:1.75 49:1.40 50:1.29
51:0.86 52:0.28"""
spec = {int(k): float(v) for k, v in (p.split(":") for p in SPEC.split())}

cal = json.load(open(sys.argv[1], encoding="utf-8"))


def check(label, got, want):
    print(f"{'ok  ' if got == want else 'FAIL'} {label}: {got} (spec {want})")


s = cal["sales"]
check("sale lines", s["sale_lines"], 1003214)
check("invoices", s["invoices"], 39516)
w = cal["week_of_year"]
check("orders Dec 2009-Nov 2010", w["orders_december_to_november"]["2009-12 to 2010-11"], 19743)
check("orders Dec 2010-Nov 2011", w["orders_december_to_november"]["2010-12 to 2011-11"], 18957)
print("     weeks without orders:", w["weeks_without_orders"], "| ISO weeks with orders:", len(w["orders_per_iso_week"]))

raw = {int(k): v for k, v in w["index_raw"].items()}
worst = max(abs(raw[k] - v) for k, v in spec.items())
print(f"{'ok  ' if worst <= 0.005 + 1e-9 else 'FAIL'} raw index vs the 2-decimal spec values: largest gap {worst:.4f}")

index = {int(k): v for k, v in w["index"].items()}
mean = sum(index[k] for k in range(1, 53)) / 52
print(f"{'ok  ' if abs(mean - 1) < 0.001 else 'FAIL'} smoothed index mean over weeks 1-52: {mean:.5f}")
print("     week: raw -> smoothed")
for k in (1, 21, 22, 23, 34, 35, 36, 50, 51, 52, 53):
    print(f"     {k:>2}: {raw.get(k, '-')} -> {index[k]}")
ratio = index[45] / raw[45]
print(f"     rescale factor applied to unsmoothed weeks: {ratio:.4f}")

b = cal["basket"]
check("invoices with a customer", b["invoices_with_customer"], 36594)
check("consumer-like invoices", b["consumer_invoices"], 1840)


def quantiles(counts):
    values = sorted((int(k), n) for k, n in counts.items())
    total = sum(n for _, n in values)
    out = []
    for q in (0.25, 0.5, 0.75, 0.9):
        cumulative = 0
        for value, n in values:
            cumulative += n
            if cumulative >= q * total:
                out.append(value)
                break
    return out, total


products, n_orders = quantiles(b["products_per_order"])
units, n_pairs = quantiles(b["units_per_product"])
check("products per order p25/p50/p75/p90", products, [1, 1, 2, 4])
check("units per product p50/p75/p90", units[1:], [2, 4, 10])
check("orders in products_per_order", n_orders, 1840)
print("     products_per_order:", b["products_per_order"])
print("     units_per_product:", b["units_per_product"], "| pairs:", n_pairs)
print("     source:", cal["source"])
