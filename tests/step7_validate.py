"""Step 7: live traffic in the database against its clickstream events."""
import collections
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
EVENTS, BASELINE = sys.argv[1], sys.argv[2]
ACCELERATION, ORDERS_PER_DAY = float(sys.argv[3]), float(sys.argv[4])
LAST_HISTORY_ORDER = 222644
failures = []

COMMON = {"schema_version", "event_id", "event_type", "event_time", "emitted_at", "session_id", "buyer_id"}
EXTRA = {
    "product_viewed": {"p_id", "price"},
    "added_to_cart": {"p_id", "qty", "price"},
    "order_placed": {"order_id", "payment_method", "amount", "currency", "items"},
}


def check(label, condition, detail=""):
    print(f"{'ok  ' if condition else 'FAIL'} {label}" + (f"  [{detail}]" if detail != "" and not condition else ""))
    if not condition:
        failures.append(label)


def sql(query):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "marketplace", "-XAt", "-F", "\t", "-c", query],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode:
        raise SystemExit(out.stderr)
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def moment(text):
    return dt.datetime.fromisoformat(text.replace("Z", "").replace(" ", "T"))


baseline = json.loads(open(BASELINE, encoding="utf-8-sig").read())
latest = moment(baseline["latest"])
index = json.load(open(REPO + r"\generators\history\calibration.json", encoding="utf-8"))["week_of_year"]["index"]

# Events
events, broken = [], 0
with open(EVENTS, encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\r\n")
        if not line:
            continue
        key, _, value = line.partition("|")
        try:
            events.append((key, json.loads(value)))
        except ValueError:
            broken += 1
types = collections.Counter(e["event_type"] for _, e in events)
print(f"events: {len(events)} {dict(types)}")
check("every message is a JSON event", broken == 0 and len(events) > 0, broken)
bad_fields = [e for _, e in events if set(e) != COMMON | EXTRA.get(e["event_type"], set())]
check("every event has exactly its fields", not bad_fields, bad_fields[:1])
check("schema_version is 1 everywhere", all(e["schema_version"] == 1 for _, e in events))
check("the message key is the buyer id", all(k == e["buyer_id"] for k, e in events))
check("event ids are unique", len({e["event_id"] for _, e in events}) == len(events))
event_times = [moment(e["event_time"]) for _, e in events]
emitted = [moment(e["emitted_at"]) for _, e in events]
check("simulated time starts after the history's last payment", min(event_times) >= latest, (min(event_times), latest))
ratio = (max(event_times) - min(event_times)).total_seconds() / (max(emitted) - min(emitted)).total_seconds()
check(f"simulated time runs {ACCELERATION:g} times real time (measured {ratio:.1f})", abs(ratio / ACCELERATION - 1) < 0.05, ratio)
span_days = (max(event_times) - min(event_times)).total_seconds() / 86400
print(f"     simulated {min(event_times)} to {max(event_times)} ({span_days:.2f} days)")

# Orders against order_placed events
rows = sql(f"""SELECT o.order_id, o.buyer_id, o.order_date, o.payment_id, p.amount, p.method, p.created_at
               FROM orders o JOIN payment p USING (order_id) WHERE o.order_id > {LAST_HISTORY_ORDER}""")
orders = {int(r[0]): r for r in rows}
live_orders = int(sql(f"SELECT count(*) FROM orders WHERE order_id > {LAST_HISTORY_ORDER}")[0][0])
placed = [e for _, e in events if e["event_type"] == "order_placed"]
by_order = {e["order_id"]: e for e in placed}
check(f"every live order ({live_orders}) has one order_placed event, and every event its order",
      live_orders == len(orders) == len(placed) == len(by_order) and set(orders) == set(by_order), (live_orders, len(placed)))
common = set(orders) & set(by_order)
check("same buyer", all(orders[i][1] == by_order[i]["buyer_id"] for i in common))
check("event amount = payment amount", all(abs(float(orders[i][4]) - by_order[i]["amount"]) < 0.005 for i in common))
check("event payment method = payment method", all(orders[i][5] == by_order[i]["payment_method"] for i in common))
check("event_time = payment time, to the microsecond", all(moment(orders[i][6]) == moment(by_order[i]["event_time"]) for i in common),
      [(orders[i][6], by_order[i]["event_time"]) for i in list(common)[:1]])
check("order date = the event_time's date", all(orders[i][2] == by_order[i]["event_time"][:10] for i in common))
lines = collections.defaultdict(set)
for order_id, p_id, qty, price in sql(f"SELECT order_id, p_id, qty, price_at_purchase FROM order_items WHERE order_id > {LAST_HISTORY_ORDER}"):
    lines[int(order_id)].add((p_id, int(qty), round(float(price), 2)))
check("event items = order lines", all(lines[i] == {(x["p_id"], x["qty"], round(x["price"], 2)) for x in by_order[i]["items"]} for i in common))
missing_shipments = int(sql(f"""SELECT count(*) FROM order_items oi WHERE oi.order_id > {LAST_HISTORY_ORDER}
                                AND NOT EXISTS (SELECT 1 FROM shipment s WHERE s.order_id = oi.order_id AND s.p_id = oi.p_id)""")[0][0])
check("every live order line has its shipment", missing_shipments == 0, missing_shipments)

# Volumes
expected, day = 0.0, min(event_times)
step = dt.timedelta(hours=1)
while day < max(event_times):
    expected += ORDERS_PER_DAY / 24 * index[str(day.isocalendar()[1])]
    day += step
check(f"orders ({len(orders)}) within 25% of ORDERS_PER_DAY x index over the span ({expected:.0f})", abs(len(orders) / expected - 1) < 0.25)
print("     orders by simulated day:", dict(sorted(collections.Counter(r[2] for r in rows).items())))
sessions = collections.defaultdict(collections.Counter)
for _, e in events:
    sessions[e["session_id"]][e["event_type"]] += 1
views = collections.Counter(s["product_viewed"] for s in sessions.values())
check("every session views 1 to 5 products", set(views) <= {1, 2, 3, 4, 5}, dict(views))
buy_share = len(placed) / len(sessions)
with_adds = sum(1 for s in sessions.values() if s["added_to_cart"])
print(f"     sessions {len(sessions)}, with adds {with_adds} ({with_adds / len(sessions):.1%}), with an order {len(placed)} ({buy_share:.1%}); views per session {dict(sorted(views.items()))}")
check("about a third of sessions buy (20-45%)", 0.20 <= buy_share <= 0.45, buy_share)
new_customers = int(sql("SELECT count(*) FROM customer WHERE c_id LIKE '%-%-%-%-%'")[0][0])
new_methods = dict(sql("SELECT p.method, count(*) FROM payment p JOIN orders o USING (order_id) WHERE o.buyer_id LIKE '%-%-%-%-%' GROUP BY 1"))
print(f"     sign-ups {new_customers} ({new_customers / len(sessions):.1%} of sessions); their payments {new_methods}")
check("sign-ups pay by PayPal only", set(new_methods) <= {"PayPal"}, new_methods)
live_methods = dict(sql(f"SELECT method, count(*) FROM payment WHERE order_id > {LAST_HISTORY_ORDER} GROUP BY 1"))
print(f"     live payment methods {live_methods}; carts left with items: {sql('SELECT count(DISTINCT cart_id), coalesce(sum(qty), 0) FROM cart_items')[0]}")

# Warehouse
today = max(event_times).date().isoformat()
print(f"     shipments at the start of traffic: {baseline['shipments']}")
for live, status, n, min_age, max_age, late, min_days, max_days in sql(f"""
        SELECT o.order_id > {LAST_HISTORY_ORDER}, s.status, count(*),
               min(DATE '{today}' - o.order_date), max(DATE '{today}' - o.order_date),
               count(*) FILTER (WHERE s.actual_delivery_date > DATE '{today}'),
               min(s.actual_delivery_date - o.order_date), max(s.actual_delivery_date - o.order_date)
        FROM shipment s JOIN orders o USING (order_id) GROUP BY 1, 2 ORDER BY 1, 2"""):
    label = "live" if live == "t" else "history"
    print(f"     {label} {status}: {n}, age {min_age}-{max_age} days, delivery {min_days}-{max_days} days")
    if status == "processing":
        check(f"{label} processing shipments are under 4 days old (3 plus a day of slack)", int(max_age) < 4, max_age)
    if status == "in_transit":
        check(f"{label} in-transit shipments are 2 to 11 days old", 2 <= int(min_age) and int(max_age) <= 11, (min_age, max_age))
    if status == "delivered":
        check(f"{label} deliveries are 2 to 9 days after the order, never after today", min_days and 2 <= int(min_days) and int(max_days) <= 9 and late == "0", (min_days, max_days, late))
below = int(sql("SELECT count(*) FROM product WHERE qty < 5")[0][0])
print(f"     products under 5 units: {baseline['products_below_5']} before traffic, {below} now")
check("the warehouse restocked", below < baseline["products_below_5"], (baseline["products_below_5"], below))

print(f"\n{len(failures)} failed" + (f": {failures}" if failures else ""))
sys.exit(1 if failures else 0)
