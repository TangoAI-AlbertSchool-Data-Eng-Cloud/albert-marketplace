"""Step 6: the storefront API against the generated database, one check per §10.2 failure and rule."""
import datetime as dt
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
API = sys.argv[1]
failures = []


def call(method, path, params=None, body=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw.decode("utf-8", "replace")


def sql(query):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "marketplace", "-XAt", "-F", "\t", "-c", query],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode:
        raise SystemExit(out.stderr)
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def check(label, condition, detail=""):
    print(f"{'ok  ' if condition else 'FAIL'} {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def cents(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


today = dt.datetime.now(dt.timezone.utc).date().isoformat()

status, body = call("GET", "/health")
check("GET /health is 200", status == 200, body)

# A generated buyer with a saved card, and two products in stock whose prices have float noise
buyer, card = sql("""SELECT b.buyer_id, cp.payment_id FROM buyer b
                     JOIN customer_payment cp ON cp.c_id = b.buyer_id AND cp.is_default = '1'
                     ORDER BY b.buyer_id LIMIT 1""")[0]
(p1, qty1, price1), (p2, qty2, price2) = sql("SELECT p_id, qty, price FROM product WHERE qty >= 5 AND scale(price) > 2 ORDER BY p_id LIMIT 2")
qty1 = int(qty1)
print(f"     buyer {buyer}, card {card}; products {p1} (stock {qty1}, price {price1}) and {p2} (price {price2})")

# §10.2 row 5: order history of a generated buyer
status, orders = call("GET", f"/orders/{buyer}")
check("GET /orders for a generated buyer is 200 (was 500)", status == 200, orders)
if status == 200:
    check("  every order has its payment", all(o["payment"] is not None for o in orders))
    check("  every order lists one shipment per line (was one shipment)", all(len(o["shipments"]) == len(o["items"]) for o in orders))

# Cart: totals in cents, stock limit, bad input, removal
status, cart = call("POST", f"/cart/{buyer}", {"p_id": p1, "qty": 2})
check("add 2 units is 200", status == 200, cart)
status, cart = call("POST", f"/cart/{buyer}", {"p_id": p2, "qty": 1})
expected_total = float(cents(price1) * 2 + cents(price2))
check("cart total is in cents (was float noise)", status == 200 and cart["total_price"] == expected_total, (cart, expected_total))
status, body = call("POST", f"/cart/{buyer}", {"p_id": p1, "qty": qty1})
check("adding beyond stock is 409 (was accepted)", status == 409, (status, body))
for qty in (0, -3):
    status, body = call("POST", f"/cart/{buyer}", {"p_id": p1, "qty": qty})
    check(f"quantity {qty} is 422 (was 500)", status == 422, (status, body))
status, body = call("POST", f"/cart/{buyer}", {"p_id": "NOPE000000", "qty": 1})
check("unknown product is 404 (was 500)", status == 404, (status, body))
status, body = call("GET", "/cart/not-a-buyer")
check("cart of an unknown buyer is 404 (was 500)", status == 404, (status, body))
status, cart = call("DELETE", f"/cart/{buyer}/{p2}")
check("remove a line is 200 and totals follow", status == 200 and [i["p_id"] for i in cart["items"]] == [p1] and cart["total_price"] == float(cents(price1) * 2), cart)
status, body = call("DELETE", f"/cart/{buyer}/{p2}")
check("removing a line not in the cart is 404", status == 404, (status, body))

# Checkout by card
status, body = call("POST", f"/checkout/{buyer}", {"payment_method": "Anything"})
check("unknown payment method is 422 (was accepted)", status == 422, (status, body))
stock_before = int(sql(f"SELECT qty FROM product WHERE p_id = '{p1}'")[0][0])
status, order = call("POST", f"/checkout/{buyer}", {"payment_method": "Credit Card"})
check("checkout by card is 201", status == 201, order)
if status == 201:
    order_id = order["order_id"]
    check("  order id continues the sequence", order_id > 222644, order_id)
    check("  order and payment use the buyer's default card", order["payment_id"] == int(card) and order["payment"]["payment_id"] == int(card), order)
    check("  payment amount is the lines' total", order["payment"]["amount"] == float(cents(price1) * 2), order["payment"])
    check("  line price is the product price in cents", order["items"] == [{"p_id": p1, "qty": 2, "price_at_purchase": float(cents(price1))}], order["items"])
    check("  one shipment, with a carrier", len(order["shipments"]) == 1 and order["shipments"][0]["carrier_id"] in (1, 2, 3, 4), order["shipments"])
    check("  order dated today (UTC)", order["order_date"] == today, order["order_date"])
    stock_after = int(sql(f"SELECT qty FROM product WHERE p_id = '{p1}'")[0][0])
    check("  the stock trigger took 2 units", stock_after == stock_before - 2, (stock_before, stock_after))
    rows = sql(f"SELECT (SELECT count(*) FROM order_items WHERE order_id = {order_id}), (SELECT count(*) FROM shipment WHERE order_id = {order_id}), (SELECT count(*) FROM payment WHERE order_id = {order_id})")[0]
    check("  database has 1 line, 1 shipment, 1 payment", rows == ["1", "1", "1"], rows)
    status, shipments = call("GET", f"/shipments/{order_id}")
    check("  GET /shipments is 200", status == 200 and len(shipments) == 1, (status, shipments))
    status, cart = call("GET", f"/cart/{buyer}")
    check("  cart is empty afterwards", cart["items"] == [] and cart["total_qty"] == 0 and cart["total_price"] == 0, cart)
status, body = call("POST", f"/checkout/{buyer}", {"payment_method": "PayPal"})
check("checkout of an empty cart is 400", status == 400, (status, body))
status, body = call("GET", "/shipments/999999999")
check("shipments of an unknown order are 404", status == 404, (status, body))

# §10.2 row 9: stock taken in the meantime; the trigger's refusal is a 409 and the cart survives
call("POST", f"/cart/{buyer}", {"p_id": p1, "qty": 1})
saved_stock = sql(f"SELECT qty FROM product WHERE p_id = '{p1}'")[0][0]
sql(f"UPDATE product SET qty = 0 WHERE p_id = '{p1}'")
status, body = call("POST", f"/checkout/{buyer}", {"payment_method": "PayPal"})
check("checkout when stock ran out is 409 (was 500)", status == 409 and "Not enough stock" in str(body), (status, body))
status, cart = call("GET", f"/cart/{buyer}")
check("  the cart keeps its line", [i["p_id"] for i in cart["items"]] == [p1], cart)
sql(f"UPDATE product SET qty = {saved_stock} WHERE p_id = '{p1}'")
status, cart = call("DELETE", f"/cart/{buyer}/{p1}")
check("  and the buyer can remove it (was stuck)", status == 200 and cart["items"] == [], (status, cart))

# §10.2 rows 3 and 4: sign-up, then shopping
suffix = dt.datetime.now().strftime("%H%M%S%f")
signup = {"fname": "Nina", "lname": "Test", "phone": "06" + suffix[-8:], "email": f"nina.{suffix}@example.com", "pwd": "correct-horse"}
status, customer = call("POST", "/customers/", body=signup)
check("sign-up is 201 (was 500)", status == 201, (status, customer))
if status == 201:
    new_id = customer["c_id"]
    pwd, is_buyer = sql(f"SELECT c.pwd, (SELECT count(*) FROM buyer WHERE buyer_id = c.c_id) FROM customer c WHERE c.c_id = '{new_id}'")[0]
    check("  password stored as bcrypt", pwd.startswith("$2b$") and len(pwd) == 60, pwd[:7])
    check("  the new customer is a buyer (was customer only)", is_buyer == "1", is_buyer)
    status, body = call("POST", "/customers/", body={**signup, "phone": "07" + suffix[-8:]})
    check("  same email again is 409", status == 409, (status, body))
    status, body = call("POST", "/customers/", body={**signup, "email": f"other.{suffix}@example.com"})
    check("  same phone again is 409", status == 409, (status, body))
    status, cart = call("POST", f"/cart/{new_id}", {"p_id": p1, "qty": 1})
    check("  the new buyer can fill a cart (was 500)", status == 200, (status, cart))
    status, body = call("POST", f"/checkout/{new_id}", {"payment_method": "Credit Card"})
    check("  card checkout without a saved card is 400", status == 400 and "saved card" in str(body), (status, body))
    status, order = call("POST", f"/checkout/{new_id}", {"payment_method": "PayPal"})
    check("  PayPal checkout is 201, with no card", status == 201 and order["payment"]["payment_id"] is None and order["payment"]["method"] == "PayPal", (status, order))
for label, change in (
    ("a 73-byte password", {"pwd": "x" * 73}),
    ("a 7-character password", {"pwd": "x" * 7}),
    ("a 31-character last name", {"lname": "x" * 31}),
    ("a phone with letters", {"phone": "06ABCDEFGH"}),
    ("a 16-digit phone", {"phone": "0" * 16}),
    ("an email on a reserved domain", {"email": "someone@example.test"}),
):
    status, body = call("POST", "/customers/", body={**signup, "email": f"x{suffix}@example.com", "phone": "04" + suffix[-8:], **change})
    check(f"sign-up with {label} is 422", status == 422, (status, body))

# Products and images
status, products = call("GET", "/products/", {"limit": 5})
check("products come by product ID", status == 200 and [p["p_id"] for p in products] == sorted(p["p_id"] for p in products) and len(products) == 5, products)
status, body = call("GET", "/products/", {"limit": 101})
check("more than 100 products at once is 422", status == 422, status)
with_images = sql("SELECT p_id FROM product_images ORDER BY p_id LIMIT 1")[0][0]
without_images = sql("SELECT p_id FROM product p WHERE NOT EXISTS (SELECT 1 FROM product_images i WHERE i.p_id = p.p_id) ORDER BY p_id LIMIT 1")[0][0]
status, urls = call("GET", f"/products/{with_images}/images")
check("images of a product are URLs", status == 200 and urls and all(u.startswith("http") for u in urls), (status, urls))
status, urls = call("GET", f"/products/{without_images}/images")
check("a product without images gives [] (was 404)", status == 200 and urls == [], (status, urls))
status, body = call("GET", "/products/NOPE000000/images")
check("images of an unknown product are 404", status == 404, (status, body))

print(f"\n{len(failures)} failed" + (f": {failures}" if failures else ""))
sys.exit(1 if failures else 0)
