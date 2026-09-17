"""Live traffic: shopping sessions through the storefront API, clickstream events to Kafka.

A simulated clock starts where the data ends (the latest payment in the
database) and runs CLOCK_ACCELERATION times faster than real time
(docs/build-spec.md §5.5, §9.17). Sessions arrive at random, ORDERS_PER_DAY
per simulated day on average, shaped by the week-of-year index:
- 2% are new customers, who sign up first
- each session views 1 to 5 products (product_viewed)
- a third add products to their cart (added_to_cart) and pay (order_placed);
  a quarter of the others leave items in their cart
Orders are written only through the API, which dates them with the simulated
time. Every simulated hour the warehouse endpoint moves shipments along and
restocks.

The choices are seeded (TRAFFIC_SEED), but what happens also depends on live
stock and timing, so runs are not reproducible the way the history is.
"""

import datetime as dt
import itertools
import json
import os
import random
import re
import signal
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

import psycopg
import requests
from confluent_kafka import Producer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from europe import COUNTRIES, MOBILE_NUMBERS  # noqa: E402

CALIBRATION = Path(__file__).resolve().parents[1] / "history" / "calibration.json"
SCHEMA_VERSION = 1

API_URL = os.environ.get("API_URL", "http://storefront-api:8000")
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "clickstream")
ACCELERATION = float(os.environ.get("CLOCK_ACCELERATION", "15"))
ORDERS_PER_DAY = float(os.environ.get("ORDERS_PER_DAY", "200"))
SEED = int(os.environ.get("TRAFFIC_SEED", "20260915"))

# Sessions (build-spec §9.17)
BUY_SHARE = 1 / 3
LEAVE_ITEMS_SHARE = 0.25  # of the sessions that do not buy
SIGNUP_SHARE = 0.02
VIEWS = (1, 5)
WAREHOUSE_EVERY = dt.timedelta(hours=1)
LOG_EVERY = dt.timedelta(hours=6)

rng = random.Random(SEED)


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def iso(moment):
    return moment.isoformat(timespec="microseconds") + "Z"


class Clock:
    """Simulated time: starts at `start` and runs `acceleration` times faster than real time."""

    def __init__(self, start, acceleration):
        self.start, self.acceleration, self.origin = start, acceleration, time.monotonic()

    def now(self):
        return self.start + dt.timedelta(seconds=(time.monotonic() - self.origin) * self.acceleration)

    def sleep_until(self, moment):
        wait = (moment - self.now()).total_seconds() / self.acceleration
        if wait > 0:
            time.sleep(wait)


def read_catalogue():
    """Read-only: where the data ends, buyers, products that can be sold, and names for sign-ups."""
    with psycopg.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT max(created_at) FROM payment")
        latest = cur.fetchone()[0]
        cur.execute(
            """
            SELECT b.buyer_id, EXISTS (
                SELECT 1 FROM customer_payment cp WHERE cp.c_id = b.buyer_id AND cp.is_default = '1')
            FROM buyer b
            ORDER BY b.buyer_id COLLATE "C"
            """
        )
        buyers = cur.fetchall()
        # Weighted by review count and never priced 0.00, as in the history (§5.4, §9.4)
        cur.execute(
            """
            SELECT p.p_id, round(p.price, 2), count(*)
            FROM product p JOIN product_reviews pr USING (p_id)
            GROUP BY p.p_id
            HAVING round(p.price, 2) > 0
            ORDER BY p.p_id COLLATE "C"
            """
        )
        products = cur.fetchall()
        cur.execute('SELECT fname, lname FROM customer ORDER BY c_id COLLATE "C" LIMIT 5000')
        names = cur.fetchall()
    return latest, buyers, products, names


class Traffic:
    def __init__(self, clock, buyers, products, names, calibration):
        self.clock = clock
        self.buyers = buyers
        self.products = [(p_id, float(price)) for p_id, price, _ in products]
        self.product_weights = list(itertools.accumulate(n for _, _, n in products))
        self.names = names
        basket = calibration["basket"]
        self.sizes = ([int(k) for k in basket["products_per_order"]], list(basket["products_per_order"].values()))
        self.quantities = ([int(k) for k in basket["units_per_product"]], list(basket["units_per_product"].values()))
        self.index = calibration["week_of_year"]["index"]
        self.http = requests.Session()
        self.producer = Producer(
            {"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS, "enable.idempotence": True, "linger.ms": 100}
        )
        self.stats = Counter()
        self.next_session = clock.now()

    def new_id(self):
        return str(uuid.UUID(int=rng.getrandbits(128), version=4))

    def api(self, method, path, at=None, **kwargs):
        headers = {"X-Simulated-Time": iso(at)} if at else {}
        response = self.http.request(method, API_URL + path, headers=headers, timeout=30, **kwargs)
        if response.status_code >= 500:
            self.stats["api 5xx"] += 1
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, None

    def delivered(self, error, message):
        if error is not None:
            self.stats["event delivery errors"] += 1

    def emit(self, event_type, context, at, **fields):
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": self.new_id(),
            "event_type": event_type,
            "event_time": iso(at),
            "emitted_at": iso(utc_now()),
            **context,
            **fields,
        }
        self.producer.produce(
            KAFKA_TOPIC,
            key=context["buyer_id"].encode("utf-8"),
            value=json.dumps(event).encode("utf-8"),
            on_delivery=self.delivered,
        )
        self.producer.poll(0)
        self.stats[event_type] += 1

    def pick_products(self, k, exclude=()):
        chosen, seen = [], set(exclude)
        while len(chosen) < k:
            p_id, price = rng.choices(self.products, cum_weights=self.product_weights)[0]
            if p_id not in seen:
                seen.add(p_id)
                chosen.append((p_id, price))
        return chosen

    def sign_up(self):
        fname, lname = rng.choice(self.names)
        country = rng.choices(list(COUNTRIES), weights=[population for _, population in COUNTRIES.values()])[0]
        prefix, digits = rng.choice(MOBILE_NUMBERS[country])
        phone = prefix + "".join(rng.choice("0123456789") for _ in range(digits - len(prefix)))
        parts = [re.sub("[^a-z]", "", name.lower()) for name in (fname, lname)]
        local = ".".join(part for part in parts if part) or "customer"
        body = {
            "fname": fname,
            "lname": lname,
            "phone": phone,
            "email": f"{local}{rng.randint(1, 999999)}@example.com",
            "pwd": self.new_id(),
        }
        status, customer = self.api("POST", "/customers/", json=body)
        if status != 201:
            self.stats[f"sign-up {status}"] += 1
            return None
        self.stats["sign-ups"] += 1
        buyer = (customer["c_id"], False)
        self.buyers.append(buyer)
        return buyer

    def session(self):
        session_id = self.new_id()
        buyer = self.sign_up() if rng.random() < SIGNUP_SHARE else rng.choice(self.buyers)
        if buyer is None:
            return
        buyer_id, has_card = buyer
        context = {"session_id": session_id, "buyer_id": buyer_id}
        self.stats["sessions"] += 1

        viewed = self.pick_products(rng.randint(*VIEWS))
        for p_id, price in viewed:
            at = self.clock.now()
            self.api("GET", f"/products/{p_id}/images")
            self.emit("product_viewed", context, at, p_id=p_id, price=price)

        buys = rng.random() < BUY_SHARE
        if not buys and rng.random() >= LEAVE_ITEMS_SHARE:
            return
        size = rng.choices(*self.sizes)[0]
        basket = viewed[:size] + self.pick_products(max(0, size - len(viewed)), exclude={p for p, _ in viewed})
        added = 0
        for p_id, price in basket:
            qty = rng.choices(*self.quantities)[0]
            at = self.clock.now()
            status, _ = self.api("POST", f"/cart/{buyer_id}", params={"p_id": p_id, "qty": qty})
            if status == 200:
                added += 1
                self.emit("added_to_cart", context, at, p_id=p_id, qty=qty, price=price)
            else:
                self.stats[f"add to cart {status}"] += 1
        if not buys or not added:
            self.stats["carts left"] += added > 0
            return

        method = "Credit Card" if has_card else "PayPal"
        at = self.clock.now()
        status, order = self.api("POST", f"/checkout/{buyer_id}", at=at, params={"payment_method": method})
        if status != 201:
            self.stats[f"checkout {status}"] += 1
            return
        self.stats["orders"] += 1
        self.emit(
            "order_placed",
            context,
            at,
            order_id=order["order_id"],
            payment_method=method,
            amount=order["payment"]["amount"],
            currency="EUR",
            items=[{"p_id": i["p_id"], "qty": i["qty"], "price": i["price_at_purchase"]} for i in order["items"]],
        )

    def advance_warehouse(self, at):
        status, moved = self.api("POST", "/warehouse/advance", at=at)
        if status != 200:
            self.stats[f"warehouse {status}"] += 1
            return
        for key, n in moved.items():
            self.stats[f"warehouse {key}"] += n

    def log(self, now):
        behind = max(0.0, (now - self.next_session).total_seconds() / 3600)
        print(
            f"{iso(now)} simulated, {behind:.1f} simulated hours behind | "
            + ", ".join(f"{key} {value}" for key, value in sorted(self.stats.items())),
            flush=True,
        )

    def run(self):
        next_warehouse = self.clock.now()
        next_log = next_warehouse + LOG_EVERY
        while True:
            week = str(self.next_session.isocalendar()[1])
            sessions_per_second = ORDERS_PER_DAY / BUY_SHARE / 86400 * self.index[week]
            self.next_session += dt.timedelta(seconds=rng.expovariate(sessions_per_second))
            self.clock.sleep_until(self.next_session)
            try:
                self.session()
                now = self.clock.now()
                if now >= next_warehouse:
                    self.advance_warehouse(now)
                    next_warehouse = now + WAREHOUSE_EVERY
            except requests.RequestException as error:
                self.stats["api unreachable"] += 1
                print(f"storefront API unreachable: {error}", flush=True)
                time.sleep(5)
            now = self.clock.now()
            if now >= next_log:
                self.log(now)
                next_log = now + LOG_EVERY


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    while True:
        try:
            latest, buyers, products, names = read_catalogue()
            if buyers and products and names:
                break
            print("waiting for data: the database has no buyers or products yet", flush=True)
        except psycopg.Error as error:
            print(f"waiting for the database: {error}".strip(), flush=True)
        time.sleep(30)

    start = latest or utc_now()
    clock = Clock(start, ACCELERATION)
    print(
        f"simulated clock starts at {iso(start)}, {ACCELERATION:g} times real time; "
        f"{ORDERS_PER_DAY:g} orders per simulated day; seed {SEED}; {len(buyers)} buyers, {len(products)} products",
        flush=True,
    )
    traffic = Traffic(clock, buyers, products, names, calibration)
    try:
        traffic.run()
    finally:
        traffic.producer.flush(10)
        traffic.log(clock.now())


if __name__ == "__main__":
    main()
