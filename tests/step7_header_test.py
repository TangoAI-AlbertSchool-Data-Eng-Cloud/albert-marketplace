"""Step 7: X-Simulated-Time and the warehouse endpoint, with SIMULATION on or off."""
import datetime as dt
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
API, MODE = sys.argv[1], sys.argv[2]
failures = []


def call(method, path, params=None, headers=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def sql(query):
    out = subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "marketplace", "-XAt", "-c", query],
                         cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    return out.stdout.strip()


def check(label, condition, detail=""):
    print(f"{'ok  ' if condition else 'FAIL'} [{MODE}] {label}" + (f"  [{detail}]" if not condition else ""))
    if not condition:
        failures.append(label)


buyer = sql("SELECT b.buyer_id FROM buyer b JOIN customer_payment cp ON cp.c_id = b.buyer_id AND cp.is_default = '1' ORDER BY b.buyer_id OFFSET 7 LIMIT 1")
p_id = sql("SELECT p_id FROM product WHERE qty >= 20 ORDER BY p_id OFFSET 11 LIMIT 1")
cart = call("GET", f"/cart/{buyer}")[1]
for item in cart["items"]:
    call("DELETE", f"/cart/{buyer}/{item['p_id']}")
status, _ = call("POST", f"/cart/{buyer}", {"p_id": p_id, "qty": 1})
check("add to cart", status == 200, status)

if MODE == "off":
    status, body = call("POST", f"/checkout/{buyer}", {"payment_method": "PayPal"}, {"X-Simulated-Time": "2031-02-03T04:05:06Z"})
    check("X-Simulated-Time is refused (400)", status == 400 and "SIMULATION" in str(body), (status, body))
    status, body = call("POST", "/warehouse/advance")
    check("the warehouse endpoint does not exist (404)", status == 404, (status, body))
    status, order = call("POST", f"/checkout/{buyer}", {"payment_method": "PayPal"})
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    check("checkout without the header uses the real date", status == 201 and order["order_date"] == today, (status, order))
else:
    status, body = call("POST", f"/checkout/{buyer}", {"payment_method": "PayPal"}, {"X-Simulated-Time": "not a time"})
    check("a malformed X-Simulated-Time is 400", status == 400, (status, body))
    status, order = call("POST", f"/checkout/{buyer}", {"payment_method": "PayPal"}, {"X-Simulated-Time": "2031-02-03T04:05:06.789Z"})
    check("checkout with the header is 201", status == 201, (status, order))
    if status == 201:
        check("order dated with the simulated time", order["order_date"] == "2031-02-03", order["order_date"])
        check("payment time is the simulated time", order["payment"]["created_at"].startswith("2031-02-03T04:05:06.789"), order["payment"]["created_at"])
        check("shipment estimate is 7 simulated days later", order["shipments"][0]["est_delivery_date"] == "2031-02-10", order["shipments"])
        status, moved = call("POST", "/warehouse/advance", headers={"X-Simulated-Time": "2031-02-15T00:00:00Z"})
        check("warehouse advance is 200 with counts", status == 200 and set(moved) == {"delivered", "in_transit", "restocked"}, (status, moved))
        status, shipments = call("GET", f"/shipments/{order['order_id']}")
        delivered = shipments[0]["actual_delivery_date"]
        check("12 simulated days later the shipment is delivered, 2-9 days after the order",
              shipments[0]["status"] == "delivered" and "2031-02-05" <= delivered <= "2031-02-12", shipments)

sys.exit(1 if failures else 0)
