"""Step 5: the generated history against calibration.json and the measured twin gaps."""
import collections
import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
END = dt.date.fromisoformat(sys.argv[1])
CAL = json.load(open(REPO + r"\generators\history\calibration.json", encoding="utf-8"))


def query(sql):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "marketplace", "-XAt", "-F", "\t", "-c", sql],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode:
        raise SystemExit(out.stderr)
    return [line.split("\t") for line in out.stdout.splitlines() if line]


# Week of year: expected share of each ISO week number over the window's days
start = END.replace(year=END.year - 3)
index = CAL["week_of_year"]["index"]
expected = collections.Counter()
day = start
while day < END:
    week = day.isocalendar()[1]
    expected[week] += index[str(week)]
    day += dt.timedelta(days=1)
total = sum(expected.values())
observed = {int(w): int(c) for w, c in query("SELECT extract(week FROM order_date)::int, count(*) FROM orders WHERE order_id <= 111322 GROUP BY 1")}
n = sum(observed.values())
if n == 0:
    raise SystemExit("FAILED: no generated orders")
z = {}
for week, weight in expected.items():
    share = weight / total
    z[week] = (observed.get(week, 0) - n * share) / math.sqrt(n * share * (1 - share))
chi2 = sum(v * v for v in z.values())
worst = sorted(z.items(), key=lambda kv: abs(kv[1]), reverse=True)[:4]
print(f"week of year (originals, n={n}): {len(expected)} week numbers, chi-square {chi2:.1f} on {len(expected) - 1} df, "
      f"largest |z| {[(w, round(v, 2)) for w, v in worst]}, weeks outside the index: {sorted(set(observed) - set(expected))}")
for week in (22, 35, 46, 50, 51, 52, 53, 1):
    if week in expected:
        print(f"   week {week:>2}: expected {n * expected[week] / total:8.1f}  observed {observed.get(week, 0):6}")


def compare(label, reference, rows):
    ref_total = sum(reference.values())
    obs = {int(k): int(v) for k, v in rows}
    obs_total = sum(obs.values())
    keys = sorted(set(int(k) for k in reference) | set(obs))
    tvd = 0.5 * sum(abs(obs.get(k, 0) / obs_total - reference.get(str(k), 0) / ref_total) for k in keys)
    shares = ", ".join(f"{k}: {reference.get(str(k), 0) / ref_total:.3f}/{obs.get(k, 0) / obs_total:.3f}" for k in keys)
    print(f"{label} (n={obs_total}): total variation distance {tvd:.4f}\n   reference/generated shares {shares}")


compare("products per order", CAL["basket"]["products_per_order"],
        query("SELECT k, count(*) FROM (SELECT count(*) AS k FROM order_items WHERE order_id <= 111322 GROUP BY order_id) g GROUP BY k"))
compare("units per line", CAL["basket"]["units_per_product"],
        query("SELECT qty, count(*) FROM order_items WHERE order_id <= 111322 GROUP BY qty"))
compare("twin gap days", {"0": 22146, "1": 35602, "2": 26792, "3": 17841, "4": 8941},
        query("SELECT t.order_date - o.order_date, count(*) FROM orders o JOIN orders t ON t.order_id = o.order_id + 111322 GROUP BY 1"))
