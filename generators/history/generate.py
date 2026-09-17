"""Generate the three-year order history on the freshly loaded legacy database.

Runs after db/load_legacy.sql, in one transaction (docs/build-spec.md §5.2, §5.4, §9):
- redraws every order's date over the three years before --end-date, weighted by
  the week-of-year index in calibration.json; each twin lands 0-4 days after its
  original
- writes order lines: the reviewed product first, then extra products weighted
  by review count, with quantities from the consumer basket counts; a twin gets
  its original's lines
- writes one PAYMENT per order and one SHIPMENT per order line, with four
  fictional carriers
- moves every customer to one of six European countries: a national mobile
  number, addresses spread like each country's regional population from
  places.json (GeoNames postcodes, Eurostat populations) with streets from
  Faker, and billing addresses rebuilt from the default address

    docker compose --profile build run --rm generate-history [--seed N] [--end-date YYYY-MM-DD]

Deterministic: the same legacy load, calibration, places, seed and end date give
the same database.
"""

import argparse
import datetime as dt
import json
import string
import sys
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import psycopg
from faker import Faker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from europe import COUNTRIES, MOBILE_NUMBERS  # noqa: E402

CALIBRATION = Path(__file__).with_name("calibration.json")
PLACES = Path(__file__).with_name("places.json")

# Twin date gaps measured on the legacy extract, days -> pairs (build-spec §5.4
# item 2); the twin is on or after its original (§9.15)
TWIN_GAP_PAIRS = {0: 22146, 1: 35602, 2: 26792, 3: 17841, 4: 8941}

# Fictional carriers (build-spec §5.4 item 7)
CARRIERS = ["Albatros Parcels", "Blue Heron Logistics", "Kestrel Freight", "Swift Otter Delivery"]

# Shipment status from the order's age in days at the end date (build-spec §9.14)
DELIVERED_AFTER_DAYS = 10
IN_TRANSIT_FROM_DAYS = 3
DELIVERY_DAYS = (2, 9)
ESTIMATED_DELIVERY_DAYS = 7

# Every legacy order was paid with its buyer's saved card (build-spec §5.4 item 1)
PAYMENT_METHOD = "Credit Card"
PAYMENT_STATUS = "completed"

# Streets from Faker in the country's language; Belgian streets follow the
# region, French in Wallonia and Dutch in Flanders and Brussels (§9.16)
STREET_LOCALES = {"FR": "fr_FR", "DE": "de_DE", "IT": "it_IT", "ES": "es_ES", "NL": "nl_NL", "BE": "nl_BE"}
WALLONIA = "Wallonie"

# Dutch postcodes: GeoNames' four digits plus two letters, never SS, SD or SA (§9.16)
DUTCH_POSTCODE_LETTERS = [
    a + b for a in string.ascii_uppercase for b in string.ascii_uppercase if a + b not in {"SS", "SD", "SA"}
]

CENT = Decimal("0.01")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument(
        "--end-date",
        type=dt.date.fromisoformat,
        default=dt.date.today(),
        help="the history ends the day before this date (default: today)",
    )
    parser.add_argument(
        "--trend", type=float, default=1.0, help="yearly growth factor of order volume (default 1.0: flat)"
    )
    return parser.parse_args()


def years_before(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


def distribution(counts):
    values = np.array([int(k) for k in counts])
    weights = np.array(list(counts.values()), dtype=float)
    return values, weights / weights.sum()


def read_legacy(cur):
    for table in ("order_items", "payment", "shipment", "carrier"):
        cur.execute(f"SELECT count(*) FROM {table}")
        if cur.fetchone()[0]:
            raise SystemExit(f"{table} is not empty: run load-legacy before generating the history")

    cur.execute("SELECT review_id, buyer_id FROM review ORDER BY review_id")
    reviews = cur.fetchall()
    cur.execute("SELECT order_id, buyer_id, payment_id FROM orders ORDER BY order_id")
    orders = cur.fetchall()
    n = len(reviews)
    if len(orders) != 2 * n:
        raise SystemExit(f"expected two orders per review, got {len(orders)} orders for {n} reviews")
    # Order i and order n + i both belong to the i-th review (build-spec §5.4 item 1)
    for i, (order_id, buyer_id, _) in enumerate(orders):
        review_id, review_buyer = reviews[i % n]
        if order_id != i + 1 or buyer_id != review_buyer:
            raise SystemExit(f"order {order_id} does not match review {review_id}: run load-legacy first")

    cur.execute("SELECT review_id, p_id FROM product_reviews")
    reviewed = dict(cur.fetchall())
    if len(reviewed) != n:
        raise SystemExit(f"expected one product per review, got {len(reviewed)} for {n} reviews")

    cur.execute(
        """
        SELECT p.p_id, p.price, count(pr.review_id)
        FROM product p LEFT JOIN product_reviews pr USING (p_id)
        GROUP BY p.p_id, p.price
        ORDER BY p.p_id COLLATE "C"
        """
    )
    products = cur.fetchall()

    cur.execute('SELECT c_id, phone FROM customer ORDER BY c_id COLLATE "C"')
    customers = cur.fetchall()
    cur.execute("SELECT address_id, c_id, is_default FROM customer_shipping ORDER BY address_id")
    addresses = cur.fetchall()
    cur.execute("SELECT payment_id, c_id FROM customer_payment WHERE is_default = '1' ORDER BY payment_id")
    cards = cur.fetchall()
    return reviews, orders, reviewed, products, customers, addresses, cards


def draw_order_dates(rng, n, end, trend, index):
    start = years_before(end, 3)
    days = [start + dt.timedelta(days=d) for d in range((end - start).days)]
    weights = np.array(
        [index[str(day.isocalendar()[1])] * trend ** ((day - start).days / 365.25) for day in days]
    )
    picks = rng.choice(len(days), size=n, p=weights / weights.sum())
    originals = [days[k] for k in picks]

    gap_values, gap_p = distribution({str(k): v for k, v in TWIN_GAP_PAIRS.items()})
    gaps = rng.choice(gap_values, size=n, p=gap_p)
    last = end - dt.timedelta(days=1)
    twins = [min(day + dt.timedelta(days=int(gap)), last) for day, gap in zip(originals, gaps)]
    return start, originals, twins


def draw_lines(rng, reviews, reviewed, products, basket):
    # Line prices as NUMERIC(10,2) stores them, rounded half away from zero
    price = {p_id: value.quantize(CENT, rounding=ROUND_HALF_UP) for p_id, value, _ in products}
    # Extra lines: products with reviews, never one whose price rounds to 0.00 (§9.4)
    eligible = [(p_id, n) for p_id, _, n in products if n > 0 and price[p_id] > 0]
    extra_ids = [p_id for p_id, _ in eligible]
    cumulative = np.cumsum([n for _, n in eligible], dtype=float)
    cumulative /= cumulative[-1]

    size_values, size_p = distribution(basket["products_per_order"])
    sizes = rng.choice(size_values, size=len(reviews), p=size_p)
    chosen_per_order = []
    for (review_id, _), size in zip(reviews, sizes):
        chosen = [reviewed[review_id]]
        while len(chosen) < size:
            candidate = extra_ids[int(np.searchsorted(cumulative, rng.random(), side="right"))]
            if candidate not in chosen:
                chosen.append(candidate)
        chosen_per_order.append(chosen)

    qty_values, qty_p = distribution(basket["units_per_product"])
    quantities = iter(rng.choice(qty_values, size=sum(map(len, chosen_per_order)), p=qty_p).tolist())
    return [[(p_id, next(quantities), price[p_id]) for p_id in chosen] for chosen in chosen_per_order]


def build_rows(rng, orders, n, originals, twins, lines, end):
    order_dates, items, payments, shipments = [], [], [], []
    for i, (order_id, _, card_id) in enumerate(orders):
        day = originals[i] if i < n else twins[i - n]
        order_lines = lines[i % n]
        order_dates.append((order_id, day))

        amount = sum((price * qty for _, qty, price in order_lines), Decimal("0.00"))
        paid_at = dt.datetime.combine(day, dt.time()) + dt.timedelta(seconds=int(rng.integers(0, 86400)))
        payments.append((order_id, card_id, amount, PAYMENT_METHOD, PAYMENT_STATUS, paid_at))

        age = (end - day).days
        for p_id, qty, price in order_lines:
            items.append((order_id, p_id, qty, price))
            carrier_id = int(rng.integers(1, len(CARRIERS) + 1))
            if age > DELIVERED_AFTER_DAYS:
                delivered = day + dt.timedelta(days=int(rng.integers(DELIVERY_DAYS[0], DELIVERY_DAYS[1] + 1)))
                status = "delivered"
            elif age >= IN_TRANSIT_FROM_DAYS:
                delivered, status = None, "in_transit"
            else:
                delivered, status = None, "processing"
            estimated = day + dt.timedelta(days=ESTIMATED_DELIVERY_DAYS)
            shipments.append((order_id, p_id, carrier_id, "NP", status, estimated, delivered))
    return order_dates, items, payments, shipments


def place_chooser(rows, regions):
    """Group a country's places by region and postcode, with regions weighted by population."""
    postcodes = {}
    for postcode, town, region in rows:
        postcodes.setdefault(region, {}).setdefault(postcode, []).append(town)
    names = sorted(postcodes)
    missing = [name for name in names if name not in regions]
    if missing:
        raise SystemExit(f"no population for regions {missing}: rebuild places.json with fetch-places")
    cumulative = np.cumsum([regions[name]["population"] for name in names], dtype=float)
    return names, cumulative / cumulative[-1], {name: sorted(postcodes[name].items()) for name in names}


def draw_place(rng, chooser):
    """A region by population, a postcode uniformly within it, a town uniformly within the postcode (§9.16)."""
    names, cumulative, postcodes = chooser
    region = names[int(np.searchsorted(cumulative, rng.random(), side="right"))]
    postcode, towns = postcodes[region][int(rng.integers(len(postcodes[region])))]
    return postcode, towns[int(rng.integers(len(towns)))], region


def localise(rng, customers, addresses, cards, places):
    codes = list(COUNTRIES)
    population = np.array([COUNTRIES[code][1] for code in codes], dtype=float)
    picks = rng.choice(len(codes), size=len(customers), p=population / population.sum())
    country_of = {c_id: codes[k] for (c_id, _), k in zip(customers, picks)}

    # New numbers avoid the legacy ones too, so the bulk update never meets a
    # value still held by a row it has not reached yet
    taken = {phone for _, phone in customers}
    phone_of = {}
    for c_id, _ in customers:
        plans = MOBILE_NUMBERS[country_of[c_id]]
        while True:
            prefix, digits = plans[int(rng.integers(len(plans)))]
            number = prefix + "".join(map(str, rng.integers(0, 10, size=digits - len(prefix))))
            if number not in taken:
                taken.add(number)
                phone_of[c_id] = number
                break

    fakers = {}
    for locale in sorted(set(STREET_LOCALES.values()) | {"fr_FR"}):
        fakers[locale] = Faker(locale)
        fakers[locale].seed_instance(int(rng.integers(2**32)))

    choosers = {code: place_chooser(places["countries"][code], places["regions"][code]) for code in COUNTRIES}
    new_addresses, default_address = [], {}
    for address_id, c_id, is_default in addresses:
        country = country_of[c_id]
        postcode, town, region = draw_place(rng, choosers[country])
        if country == "NL":
            postcode = f"{postcode} {DUTCH_POSTCODE_LETTERS[int(rng.integers(len(DUTCH_POSTCODE_LETTERS)))]}"
        locale = "fr_FR" if country == "BE" and region == WALLONIA else STREET_LOCALES[country]
        street = fakers[locale].street_address()
        # Every address keeps its customer's phone, as in the extract (§5.2)
        row = (address_id, street, town, region, postcode, COUNTRIES[country][0], phone_of[c_id])
        new_addresses.append(row)
        if is_default == "1":
            default_address[c_id] = row

    # Billing address: the default address's street, town, region and postcode, glued as in the extract (§9.13)
    billing = [(payment_id, "".join(default_address[c_id][1:5])) for payment_id, c_id in cards]
    phones = [(c_id, phone_of[c_id]) for c_id, _ in customers]
    return phones, new_addresses, billing, Counter(country_of.values())


def copy_rows(cur, statement, rows):
    with cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def write_history(cur, order_dates, items, payments, shipments):
    cur.execute("CREATE TEMP TABLE new_order_dates (order_id integer PRIMARY KEY, order_date date) ON COMMIT DROP")
    copy_rows(cur, "COPY new_order_dates (order_id, order_date) FROM STDIN", order_dates)
    cur.execute("UPDATE orders o SET order_date = n.order_date FROM new_order_dates n WHERE o.order_id = n.order_id")

    cur.executemany(
        "INSERT INTO carrier (carrier_id, carrier_name) VALUES (%s, %s)", list(enumerate(CARRIERS, start=1))
    )
    cur.execute("SELECT setval(pg_get_serial_sequence('carrier', 'carrier_id'), (SELECT max(carrier_id) FROM carrier))")

    copy_rows(cur, "COPY order_items (order_id, p_id, qty, price_at_purchase) FROM STDIN", items)
    # PAYMENT and SHIPMENT ids come from their identity columns, in row order
    copy_rows(cur, "COPY payment (order_id, payment_id, amount, method, status, created_at) FROM STDIN", payments)
    copy_rows(
        cur,
        "COPY shipment (order_id, p_id, carrier_id, shipment_type, status, est_delivery_date, actual_delivery_date) "
        "FROM STDIN",
        shipments,
    )


def write_places(cur, phones, addresses, billing):
    cur.execute("CREATE TEMP TABLE new_phones (c_id varchar(40) PRIMARY KEY, phone varchar(15)) ON COMMIT DROP")
    copy_rows(cur, "COPY new_phones (c_id, phone) FROM STDIN", phones)
    cur.execute("UPDATE customer c SET phone = n.phone FROM new_phones n WHERE c.c_id = n.c_id")

    cur.execute(
        """
        CREATE TEMP TABLE new_addresses (
            address_id integer PRIMARY KEY, street_address varchar(100), city varchar(100),
            state varchar(100), zip varchar(10), country varchar(60), phone varchar(15)
        ) ON COMMIT DROP
        """
    )
    copy_rows(
        cur, "COPY new_addresses (address_id, street_address, city, state, zip, country, phone) FROM STDIN", addresses
    )
    cur.execute(
        """
        UPDATE shipping_details s
        SET street_address = n.street_address, city = n.city, state = n.state, zip = n.zip,
            country = n.country, phone = n.phone
        FROM new_addresses n
        WHERE s.address_id = n.address_id
        """
    )

    cur.execute("CREATE TEMP TABLE new_billing (payment_id integer PRIMARY KEY, billing_address varchar(500)) ON COMMIT DROP")
    copy_rows(cur, "COPY new_billing (payment_id, billing_address) FROM STDIN", billing)
    cur.execute(
        "UPDATE payment_details p SET billing_address = n.billing_address FROM new_billing n WHERE p.payment_id = n.payment_id"
    )


def main():
    args = parse_args()
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    places = json.loads(PLACES.read_text(encoding="utf-8"))
    # Independent streams, so a change to one step leaves the others' draws alone
    dates_rng, lines_rng, rows_rng, places_rng = (
        np.random.default_rng(s) for s in np.random.SeedSequence(args.seed).spawn(4)
    )

    # Connection settings come from the libpq environment (PGHOST, PGUSER, ...)
    with psycopg.connect() as conn, conn.cursor() as cur:
        reviews, orders, reviewed, products, customers, addresses, cards = read_legacy(cur)
        n = len(reviews)
        start, originals, twins = draw_order_dates(
            dates_rng, n, args.end_date, args.trend, calibration["week_of_year"]["index"]
        )
        lines = draw_lines(lines_rng, reviews, reviewed, products, calibration["basket"])
        order_dates, items, payments, shipments = build_rows(rows_rng, orders, n, originals, twins, lines, args.end_date)
        write_history(cur, order_dates, items, payments, shipments)
        phones, new_addresses, billing, per_country = localise(places_rng, customers, addresses, cards, places)
        write_places(cur, phones, new_addresses, billing)

    last = args.end_date - dt.timedelta(days=1)
    print(f"seed {args.seed}, end date {args.end_date}, trend {args.trend}: orders dated {start} to {last}")
    print(
        f"orders {len(orders)}, order lines {len(items)}, payments {len(payments)}, shipments {len(shipments)}, "
        f"carriers {len(CARRIERS)}"
    )
    print("shipment status:", dict(sorted(Counter(row[4] for row in shipments).items())))
    print(f"customers by country: {dict(per_country.most_common())}; addresses {len(new_addresses)}, billing addresses {len(billing)}")


if __name__ == "__main__":
    main()
