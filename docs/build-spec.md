# Build spec: Albert's Marketplace source system

**Written 2026-09-15**, at the handoff from the course-design session. Every
number here was measured on the files named, not estimated.

**Deadline:** everything in "Definition of done" works before the course's
first session in October 2026. Lesson 01's demo reads the historical export.

---

## 1. Definition of done

1. `docker compose up` from a clean clone starts:
   - PostgreSQL, seeded with the full dataset
   - the storefront (API + UI)
   - Kafka
   - the load generator
2. The database holds the original tables, **with their legacy defects**, plus
   the new `order_items` table, EU addresses and phones, and a three-year order
   history with seasonality.
3. **A checkout** in the storefront writes an order, its items, a shipment row
   per item and a payment, and decrements stock.
4. **The load generator** keeps writing orders (through the storefront API) and
   publishes clickstream events to Kafka, at a configurable accelerated clock.
5. **The dataset** is published as a versioned release asset with a dataset card
   (licence, attribution, known defects, generator assumptions).
6. **The history generator is deterministic:** same seed and parameters, same
   checksum.
7. **A `--scale` option** produces a larger copy for the teacher's demos (more
   years and customers).

---

## 2. What was imported

| Path | Source | Notes |
|---|---|---|
| `db/db_creation.sql` | amazon-database-design | 25 tables, PostgreSQL. Now `db/migrations/20260915120000_baseline.sql` (step 2) |
| `db/Procedures.sql`, `db/Triggers.sql` | same | `plpgsql`, converted to PostgreSQL 17 (commit a872d17). The README still says "PL/SQL". The trigger and the fixed procedure are now in the baseline; the original procedure is `docs/critique/Procedures.original.sql` |
| `db/amazon-data.ipynb` | same | Built the original data from Amazon Reviews'23 with Faker and `names.json`, and loaded it into a Neon database |
| `storefront/` | amazon-mockup-e-commerce | FastAPI (`backend/`), Streamlit (`streamlit_app.py`), `docker-compose.yaml` |

---

## 3. The original data (profiled 2026-09-14)

Source: the CSV extract in `TANGOAI_EDUCATION_assets/datasets/Amazon/` (see
`CLAUDE.md`). **Every CSV has a spurious index column,** written by pandas with
an empty header, which pandas reads back as `Unnamed: 0`.

This profile read the CSVs with pandas' `read_csv` defaults. What those defaults
change (phones, NA-like strings, empty texts) was corrected from the raw files
in §10.3 and step 3.

| Table | Rows | Notes |
|---|---|---|
| `customer` | 130,766 | 100,000 buyers + 30,766 sellers. `pwd` is a random plaintext string of 12 characters (one has 20). Phones are 10-character strings starting with 0, in `CHAR(10)` (`VARCHAR(15)` since §9.10); pandas reads them as integers, so they show as 9 digits (one as `0`), and the same happens to the phones in `shipping_details`. 4 first names are the strings `None`, `NA`, `N/A`, `NULL`, which pandas reads as null (§10.3). Fake email domains |
| `buyer` / `seller` | 100,000 / 30,766 | `seller` has no `SELLER_NAME` column, although the schema declares one |
| `shipping_details` / `customer_shipping` | 200,001 each | US addresses from Faker. Each buyer has 1, 2 or 3 addresses (33,219 / 33,561 / 33,220 buyers) |
| `payment_details` / `customer_payment` | 100,000 each | Card number, **CVV**, expiry 2026-2030, billing address. One payment per buyer. Every billing address is the buyer's default shipping address with street, city, state and ZIP glued together without separators (`548 Mendoza ForgeWest CynthiaArizona62999`) |
| `subscription` | 50,091 | 2024-07 → 2026-07 |
| `orders` | 222,644 | `order_date` 2000-10-28 → 2023-08-30, dense 2015-2021 (2020: 40,287; 2021: 39,545; 2022: 19,457). `discount_id` all null. **No product, no quantity.** Every buyer has 2 or more orders; 24,375 duplicate (buyer, payment, date) rows; day-of-week flat (14.0-14.7% each); no seasonality |
| `product` | 42,858 | ASIN ids, name (6 empty), JSON `p_desc`, price 0.00043 → 2,143.46 (missing prices were filled from a normal distribution, which left 35,205 prices with float noise), `qty` random 1-100. Categories: All Beauty 42,637, Premium Beauty 221 |
| `product_images` / `review_images` | 186,837 / 119,382 | Amazon CDN URLs |
| `review` | 111,322 | Rating 1-5 (5-star: 66,515), text median 102 characters (max 14,643), 14 empty texts plus 13 NA-like strings (§10.3) |
| `product_reviews` / `seller_reviews` | 111,322 each | |
| `seller_products` / `wishlist_item` | 46,593 / 24,810 | |
| `carrier`, `cart`, `cart_items`, `daily_deals`, `discount`, `returns`, `shipment` | 0 | |

**Where the orders came from** (notebook, cell around line 1410 of its code):
- one order per review, `order_date` = review timestamp minus a random 3-7 days
- the insert most likely ran twice: exactly two orders per review, and identical
  dates in about a fifth of the pairs (the random offset repeating)

That is a real non-idempotent load. **Keep it.**

---

## 4. The storefront and the database disagree

To reconcile before anything runs together:

| Topic | `db/db_creation.sql` | `storefront/backend/models.py` |
|---|---|---|
| Order lines | none | `order_items (order_id, p_id)` PK, `qty`, `price_at_purchase` Float |
| `orders` columns | `buyer_id → BUYER`, `discount_id`, `payment_id`, `order_date DATE` | `buyer_id → customer`, `order_date DateTime`; no payment or discount columns |
| Payments | `PAYMENT_DETAILS` (card, CVV, expiry, billing address) + `CUSTOMER_PAYMENT` | `payment (payment_id UUID, order_id, method, status, created_at)` |
| `cart.buyer_id` | → `BUYER` | → `customer` |
| `product_images.p_id` | `VARCHAR(10)` | `String(10)` while `product.p_id` is `String` |
| `category` | defined | referenced by `product.category_id`, **but no model**. `create_all()` does not fail on it (§10.2) |
| Passwords | plaintext in the data | bcrypt for new sign-ups |
| Tables owned by | the SQL script | `create_all()` at API startup |

**Also:**
- The trigger `trg_update_inventory` (BEFORE INSERT on `orders`) decrements
  stock from the buyer's `cart_items`. The storefront inserts the order before
  clearing the cart, so the trigger fires. Verified (§10.1).
- `APPLY_DAILY_DEALS` has two Oracle leftovers, both confirmed by calling it,
  and a third bug behind them (§10.1).
  - `WHERE cart_id = cart_id`: the parameter has the same name as the column.
    With PostgreSQL's default `plpgsql.variable_conflict = error`, calling the
    procedure fails with "column reference is ambiguous".
  - `EXCEPTION WHEN no_data_found`: a plain `SELECT … INTO` in plpgsql raises
    nothing when no row matches; it leaves the variable null. A product with no
    deal makes `discount_percent` null, and the total null with it. Only
    `SELECT … INTO STRICT` raises `no_data_found`.

**Recommendation:** the SQL migrations own the schema; the storefront stops
calling `create_all()` and maps onto them. The payment model is decided in §9.1.

---

## 5. Changes to make

### 5.1 `order_items` (decided by Charles)

```sql
CREATE TABLE ORDER_ITEMS (
    ORDER_ID           INTEGER       NOT NULL,
    P_ID               VARCHAR(10)   NOT NULL,
    QTY                INTEGER       NOT NULL CHECK ( QTY > 0 ),
    PRICE_AT_PURCHASE  NUMERIC(10,2) NOT NULL CHECK ( PRICE_AT_PURCHASE >= 0 ),
    PRIMARY KEY ( ORDER_ID, P_ID ),
    CONSTRAINT OIORDERFK FOREIGN KEY ( ORDER_ID )
        REFERENCES ORDERS ( ORDER_ID ) ON DELETE CASCADE,
    CONSTRAINT OIPRODUCTFK FOREIGN KEY ( P_ID )
        REFERENCES PRODUCT ( P_ID )
);
```

- Money is `NUMERIC`, not `Float`: change the storefront model to match.
- `P_ID` follows the schema's naming (`PRODUCT.P_ID`).
- A product with orders cannot be deleted (no `ON DELETE` action), because
  `SET NULL` is impossible on a primary-key column.

### 5.2 Europe (decided)

- Regenerate `shipping_details` and phone numbers with EU Faker locales.
  - Phones stay text in each country's national format, digits only, keeping
    the leading 0 where the country uses one (§9.7). Spanish numbers have none.
  - The phone columns are `VARCHAR(15)`, because German mobiles have 11 or 12
    digits (§9.10).
  - Faker's `phone_number()` cannot be used as it is (measured on 5,000 numbers
    per locale, Faker 40.18.0): it mixes international and national formats
    with spaces and brackets, and `fr_BE` returns US numbers. Generate the
    numbers from each country's mobile prefixes, with the seeded generator.
- Rebuild `PAYMENT_DETAILS.BILLING_ADDRESS` from each buyer's new default
  address, glued without separators as in the extract, where all 100,000
  billing addresses are exactly that (§9.13).
- `STATE` holds a region.
- Prices are read as EUR.
- Names, emails and IDs stay.
- **Country mix (decided, §9.3):** FR, DE, IT, ES, NL, BE, weighted by Eurostat
  population, cited in the dataset card.

### 5.3 Dates (decided)

- Keep **three full years** of history, ending at `--end-date`, which defaults
  to the day the generator runs (§9.11).
- The load generator continues from there.

### 5.4 History generator (decided; calibration measured 2026-09-15)

1. **Purchases come from the review graph.** Each review (`review` →
   `product_reviews`) is one purchase by its buyer. The order's first line is
   the reviewed product.
   - *Measured on the extract:* order ids run 1-222,644 and review ids
     96,001-207,322, both without gaps. Order *i* and order 111,322 + *i* both
     belong to review 96,000 + *i*: the buyers match in all 111,322 pairs.
   - Every review has exactly one product and one seller, and every order is
     paid with its buyer's own card (`CUSTOMER_PAYMENT`).
2. **Keep the duplicate twin of every order,** with the same lines as its
   original. Demand is then double-counted until the students' silver layer
   deduplicates it.
   - *Measured:* a twin's date is 0-4 days from its original's: 0 days for
     22,146 pairs, 1 day for 35,602, 2 for 26,792, 3 for 17,841, 4 for 8,941.
   - §3's 24,375 repeated (buyer, payment, date) rows include those 22,146
     same-day twins. The other 2,229 are different reviews by one buyer that
     fell on the same date, since each buyer has a single card.
3. **Redraw the order date.**
   - The **week** is drawn with probability proportional to Online Retail II's
     week-of-year index (§5.4.1) times a trend parameter (default: flat,
     because Online Retail II itself had 19,743 orders in Dec 2009-Nov 2010
     against 18,957 a year later).
   - The **day within the week is uniform:** there is no consumer day-of-week
     profile we can source.
   - The **duplicate twin keeps** the original's date or a date up to 4 days
     later, never earlier, reproducing today's pattern (§9.15).
4. **Extra lines per order:** the count comes from the consumer-like order
   distribution (§5.4.2). Products are drawn from the catalogue weighted by
   review count, never repeating within an order (the primary key forbids it).
5. **Quantity per line:** from the same consumer-like distribution.
6. **`PRICE_AT_PURCHASE`** is `PRODUCT.PRICE`. Extra lines never use a product
   whose price rounds to 0.00; a first line keeps its reviewed product's price,
   even at 0.00 (§9.4).
7. **Shipments:** one `SHIPMENT` row per order line, as the storefront writes
   them.
   - estimated delivery = order + 7 days (the storefront's rule)
   - status and actual delivery date derived from how old the order is at
     `--end-date` (§9.14), documented as an assumption
   - `CARRIER` holds a handful of **fictional** carriers
8. **Determinism:** one seed; a checksum of the output is written with the
   release.

#### 5.4.1 Week-of-year index (Online Retail II)

**Method:**
- sheets concatenated, exact duplicates dropped
- sales only: invoice not prefixed `C`, quantity > 0, price > 0, `StockCode`
  starting with 5 digits
- one date per invoice (its first timestamp), full ISO weeks
  2009-12-07 → 2011-12-04
- orders counted per (ISO year, week), averaged per week number, divided by the
  mean (1.0 = an average week)

Result: 1,003,214 sale lines, 39,516 invoices.

```
 1:0.59  2:0.69  3:0.65  4:0.82  5:0.78  6:0.66  7:0.80  8:0.80  9:0.89 10:0.78
11:0.91 12:0.95 13:0.88 14:0.81 15:0.89 16:0.86 17:0.84 18:0.94 19:1.06 20:1.05
21:1.00 22:0.71 23:1.15 24:0.94 25:0.87 26:0.86 27:0.94 28:0.90 29:0.93 30:0.91
31:0.83 32:0.80 33:0.86 34:0.92 35:0.75 36:0.93 37:1.00 38:1.24 39:1.31 40:1.34
41:1.34 42:1.32 43:1.32 44:1.39 45:1.72 46:1.76 47:1.72 48:1.75 49:1.40 50:1.29
51:0.86 52:0.28
```

**Read before using:**
- Weeks 22 and 35 dip, most likely on UK bank holidays.
- Week 52 collapses (0.28) because a UK wholesaler closes for Christmas. An
  online consumer marketplace does not, so those three weeks are smoothed
  (§9.2).
- The computed index is `generators/history/calibration.json`, with its method
  and attribution. `generators/history/calibrate.py` writes it:
  `docker compose --profile build run --rm calibrate`, reading the xlsx from
  `RETAIL_XLSX_DIR` (default `./data/online_retail_II`).
- Two ISO weeks of the window have no orders, 2009-W53 and 2010-W52 (Christmas
  closures). The means per week number leave them out, so week 52's 0.28 comes
  from 2009 alone.
- Week 51 is low too (0.86): 2010's closure had already begun (158 orders
  against 486 in 2009). It takes its 2009 count alone (§9.8).

#### 5.4.2 Basket profile (Online Retail II)

**Do not use the raw baskets.** The retailer sells mostly wholesale:
- lines per invoice: median 15, mean 25.4, p90 52 (distinct products: median
  15, mean 25.1, p90 51)
- units per line: median 4, p90 24

Use **consumer-like orders:** invoices with a customer and 12 units or fewer in
total. That's 1,840 invoices, 5.0% of those with a customer.

| Measure | p25 | median | p75 | p90 |
|---|---|---|---|---|
| Products per order | 1 | 1 | 2 | 4 |
| Units per product | | 2 | 4 | 10 |

Sample from the full empirical distributions, recomputed from the xlsx, not from
these quantiles.

**Also not borrowed:**
- day of week (Saturday is 0.1% of orders)
- hour of day (orders between 8:00 and 17:00; 12:00 is the peak at 16.1%)

It is a business-to-business working week.

### 5.5 Load generator

- **Writes orders through the storefront API** (cart → checkout), so the
  storefront's logic and the stock trigger stay the only way orders are written.
  That keeps change data capture realistic.
- **Publishes clickstream events to Kafka:** `product_viewed`, `added_to_cart`,
  `order_placed`. Keyed by buyer, with JSON payloads and a `schema_version`
  field.
- **Parameters:** clock acceleration, orders per simulated day, seed. Weekly
  seasonality from the same index.
- **Kafka** runs as a single broker in KRaft mode, in `compose.yaml`.

### 5.6 Storefront fixes (running code, not teaching data)

- Stop copying `.env` into the images: read the environment at run time.
- Pin every Python dependency.
- Move PostgreSQL 13 (past end of life) to 17, which is what the procedures were
  converted for.
- Stop calling `create_all()`; map the models onto the migrated schema (§4).
- Fix every failure in §10.2.
- Remove `.DS_Store` files. Rename `docker-compose.yaml` to a single root
  `compose.yaml`.
- **Keep the original `storefront/Dockerfile` as
  `docs/critique/Dockerfile.original`,** because the course uses it as a
  critique exercise.

### 5.7 Dataset release

- **Assets:**
  - a PostgreSQL dump (the seed)
  - the CSV "legacy export", with the `Unnamed: 0` columns kept
  - `calibration.json`
  - `CHECKSUMS`
- **Dataset card:**
  - CC BY-SA 4.0
  - attribution (Amazon Reviews'23; Online Retail II for calibration)
  - every deliberate defect
  - every generator assumption
  - the seed and end date the dataset was generated with
- **Size:** GitHub allows each release asset up to 2 GiB. Check the dump against
  that before choosing compression.

### 5.8 Migrations and loader (decided after step 1)

- **Migrations use dbmate** (`ghcr.io/amacneil/dbmate:2.35.1`, a 31 MB image):
  plain SQL files in `db/migrations/`, each with `-- migrate:up` and
  `-- migrate:down`. The `migrate` service in the root `compose.yaml` waits for
  PostgreSQL's health check, applies what is pending, and exits.
- **Fix `APPLY_DAILY_DEALS` in the baseline migration:** all three bugs in
  §10.1.
- **Keep the original `db/Procedures.sql` as
  `docs/critique/Procedures.original.sql`,** as a critique exercise.
- **The loader is `db/load_legacy.sql`:** plain SQL run by `psql` from the
  PostgreSQL image, as the `load-legacy` service behind the `build` compose
  profile. `LEGACY_CSV_DIR` names the folder holding the 25 CSVs (default
  `./data/legacy_csv`):
  `docker compose --profile build run --rm load-legacy`. It:
  - stages each CSV as text, leaves out the `Unnamed: 0` column, and casts into
    the legacy tables in foreign-key order
  - empties the legacy tables and `order_items` first, all in one transaction,
    so a rerun gives the same database and a failed run changes nothing
  - writes the 6 empty `PRODUCT.P_NAME` and 14 empty `REVIEW.R_DESC` as empty
    strings, so the `NOT NULL` constraints stay
  - keeps the NA-like strings (`None`, `NA`, `N/A`, `NULL`) as text
  - sets every identity sequence to its table's highest loaded id
  - loads `orders` with `trg_update_inventory` disabled

---

## 6. Suggested work order

1. **Run what exists first:** the SQL schema and procedures on PostgreSQL 17,
   then the storefront against it. Record what breaks (§4). *Done 2026-09-15,
   §10.*
2. **Migrations:** a baseline from `db_creation.sql`, then `order_items`.
   *Done 2026-09-15 (§5.8). Verified from a cold `docker compose up`:*
   - both migrations apply, and a second run applies nothing
   - a schema-only dump differs from the original scripts only in the
     procedure fix, `order_items` and dbmate's `schema_migrations`
   - rolling both back and migrating again gives an identical schema
   - `APPLY_DAILY_DEALS` returns 88 and 98 on the step 1 cases (§10.1), applies
     the minimum price, and leaves the total unchanged for an empty cart
   - `order_items` rejects quantity 0, a negative price, a repeated product and
     an unknown order; stores 0.00043 as 0.00; blocks deleting an ordered
     product; deletes its lines with their order
   - the storefront's updated `OrderItem` model checks out `NUMERIC` lines,
     through the stock trigger
3. **Loader:** CSVs → PostgreSQL, keeping the defects.
   *Done 2026-09-15 (§5.8). Verified on a fresh database:*
   - the load takes about 20 s, and every table's row count matches §3
   - loading twice gives identical tables and sequences (md5 of every table)
   - a run that fails part-way (a missing CSV) leaves the database unchanged
   - the loader runs the same with Windows line endings, as a Windows checkout
     has it
   - `customer`, `shipping_details`, `payment_details`, `subscription`,
     `seller`, `review`, `product` and `orders` match their CSVs value for
     value, including every digit of the prices
   - the defects are still there: 130,766 plaintext passwords, CVVs (961 with
     one digit, 8,440 with two), 24,375 orders repeating (buyer, payment,
     date), the 4 NA-like first names, 6 empty product names, 14 empty review
     texts, 35,205 prices with more than two decimals
   - no phone has 9 digits: all 330,767 (customers and addresses) are
     10-character strings starting with 0. pandas' `read_csv` defaults read
     them as integers, which drops the zero (§3)
   - identity sequences sit at each table's highest id (the next default order
     id is 222,645), and the stock trigger is enabled again
   - after a load: database 320 MB, data directory 1.4 GB (mostly WAL written by
     the load), container memory 466 MiB
4. **Calibration:** `calibration.json` and the consumer basket distributions.
   *Done 2026-09-15 (§5.4.1). Verified:*
   - `calibrate.py` reproduces every number in §5.4: 1,003,214 sale lines,
     39,516 invoices, the 52 index values (within their 2-decimal rounding),
     19,743 and 18,957 orders a year, 1,840 consumer-like invoices of 36,594
     with a customer, and the basket quantiles
   - two runs write byte-identical JSON; `generators/uv.lock` pins pandas
     3.0.5, python-calamine 0.8.2 and numpy 2.5.3, on Python 3.12.12
   - the adjustments (§9.2, §9.8) move week 51 from 0.86 to 1.25 (level with
     week 50's 1.25), week 52 from 0.28 to 0.91, week 22 from 0.71 to 1.04 and
     week 35 from 0.75 to 0.90; rescaling to a mean of 1.0 multiplies every
     other week by 0.97
   - the basket counts keep the pack-size spikes (§9.9): of 3,384 order lines,
     318 have 6 units and 246 have 12
5. **History generator,** then EU localisation, then shipments and carriers.
6. **Storefront reconciliation and fixes.**
7. **Load generator and Kafka.**
8. **Release packaging,** then the `--scale` copy.

---

## 7. Verification

**Row counts and integrity:**
- original tables unchanged in count, except redrawn dates and localised
  addresses
- `order_items` primary key unique
- every foreign key resolves
- every identity sequence is past its table's highest loaded id

**The deliberate defects are still there:**
- 24,375-ish duplicate twins
- plaintext `pwd`
- CVV
- `Unnamed: 0` in the CSV export

**The calibration took:**
- the generated weekly index tracks §5.4.1, after the smoothing decision
- products per order and units per product match §5.4.2 within sampling noise

**Determinism:** two runs with the same seed give the same checksum.

**End to end:**
- a clean-clone `docker compose up` works
- a storefront checkout writes order, items, shipments, payment, and decrements
  stock
- the load generator's events arrive on the Kafka topic

---

## 8. Constraints worth remembering

- **Students' laptops also run Airbyte** (8 GB RAM minimum on its own), Airflow
  and dbt. Keep the company's memory footprint small, and measure it.
- **Each student group runs its own copy.** Change data capture needs its own
  replication slot and write access, so a shared database would couple 30
  groups.
- **Nothing here may identify a real person.** Review text is public Amazon
  review text; buyer IDs are the dataset's pseudonymous user IDs.

---

## 9. Decisions on the open questions (Charles, 2026-09-15)

1. **Payments: both tables, split by role.**
   - `PAYMENT_DETAILS` / `CUSTOMER_PAYMENT` stay the saved card, CVV defect
     included.
   - A new `PAYMENT` table holds one transaction per order: the order, the card
     used (`PAYMENT_DETAILS`), amount, method, status and timestamp.
   - The history generator backfills it, so historical and live orders have the
     same shape.
2. **Seasonality: smooth weeks 22, 35 and 52** to the mean of their neighbouring
   weeks, and record that in `calibration.json`. ISO week 53 reuses week 52's
   smoothed value (the next one starts 2026-12-28, while the load generator
   runs).
3. **Countries: FR, DE, IT, ES, NL, BE, weighted by Eurostat population,** one
   cited figure per country in the dataset card.
4. **Price outliers: every product stays in `PRODUCT`; generated extra lines
   never use a product whose price rounds to 0.00.** Products above 1,000 stay
   eligible at their review weight. The question assumed products priced 0;
   step 1 found none, only 5 that round to 0.00 (§10.3). The first lines of
   their 15 reviews' orders keep the €0.00 price, listed as a defect.
5. **`APPLY_DAILY_DEALS`: fixed in the migrations,** all three bugs (§10.1).
   The original is kept as a critique exercise (§5.8).
6. **Empty `PRODUCT.P_NAME` (6) and `REVIEW.R_DESC` (14):** loaded as empty
   strings, so the `NOT NULL` constraints stay. Listed as a defect.
7. **Phones: the defect is the leading zero, not 9-digit values** (decided after
   step 3 found no 9-digit phone). Phones stay text with a leading 0, which
   pandas' `read_csv` defaults turn into 9-digit integers (§3). The EU
   regeneration keeps national formats with their leading 0 (§5.2).
8. **Week 51 takes its 2009 count alone** (decided after step 4). 2010's
   Christmas closure had already begun that week (158 orders against 486 in
   2009), and an online shop's week before Christmas is busy. The adjustment
   comes before smoothing, so week 52 averages the adjusted week 51 and week 1.
9. **Units per product keep their pack-size spikes** (6, 12, 4, 8 and 10
   units; decided after step 4). The measured distribution is used as it is and
   listed in the dataset card as a generator assumption.
10. **`CUSTOMER.PHONE` and `SHIPPING_DETAILS.PHONE` widen from `CHAR(10)` to
    `VARCHAR(15)`** (decided before step 5), in their own migration, with the
    storefront model. German mobiles have 11 or 12 digits in national format,
    and 15 is the most digits any international number has.
    *Verified:* the migration applies on a cold start; after the legacy load
    every phone matches its CSV value; a 12-digit German mobile is accepted and
    16 digits are refused; a rollback refuses while a longer phone exists (dbmate
    prints "Rolled back" after the error, but the migration stays applied) and
    works once it is gone; the storefront's checkout still runs.
11. **`--end-date` defaults to the day the generator runs** (decided before step
    5); the history covers the three years before it. Output is identical for
    the same seed *and* end date, and the dataset card records both.
12. **The `PAYMENT` table (§9.1) is migrated in step 5,** because the history
    backfills it. The storefront's `Payment` model and checkout switch to it in
    the same commit.
13. **Billing addresses are rebuilt** from each buyer's new default address,
    glued without separators as in the extract.
14. **Shipment status comes from the order's age at `--end-date`,** listed in
    the dataset card as an assumption:
    - over 10 days: `delivered`, actual delivery 2-9 days after the order
    - 3 to 10 days: `in_transit`, no actual delivery date
    - under 3 days: `processing`, no actual delivery date
    - four fictional carriers; `RETURNS` stays empty
15. **A twin's date is on or after its original's,** 0-4 days later with the
    measured shares (§5.4 item 2). The extract shows gap sizes, not direction.

---

## 10. Step 1 results: the imported code on PostgreSQL 17 (2026-09-15)

Run in scratch Docker containers on `postgres:17` (17.11); the imported code was
not modified. The storefront images were built from the shipped Dockerfiles,
whose unpinned requirements resolved to Python 3.9 with FastAPI 0.128.8,
Pydantic 2.13.5, SQLAlchemy 2.0.53, passlib 1.7.4, bcrypt 5.0.0 and
Streamlit 1.50.0.

### 10.1 Schema, trigger and procedure

- **`db_creation.sql`, `Triggers.sql` and `Procedures.sql` install without
  error:** 25 tables, `update_inventory` with `trg_update_inventory`, and
  `APPLY_DAILY_DEALS`.
- **The stock trigger works.**
  - An order decrements `PRODUCT.QTY` by the buyer's cart lines.
  - When a line would go negative it raises `Not enough stock for product …`
    and the insert rolls back.
  - An order with a null buyer is a no-op.
  - It runs a cart lookup for every inserted row, so the loader should load
    `orders` before creating the trigger, or disable it during the load.
- **`APPLY_DAILY_DEALS` has three bugs, not two.**
  1. As written, every call fails: `column reference "cart_id" is ambiguous`.
  2. With the ambiguity forced away (`#variable_conflict use_variable`, in a
     scratch copy), `cart_id = cart_id` is always true, so the loop runs over
     every cart's items. A cart whose correct total was 88 came back 87.
     Oracle resolves the name to the column, so this was already wrong there.
  3. `WHEN no_data_found` never fires: one item without a deal makes the total
     `NULL` (correct: 98).
- **Identity columns do not follow explicit ids.** After a load that keeps the
  CSV ids, the next default `review_id` is 1 while the highest loaded id is
  207,322. The loader must `setval` every identity sequence, or the storefront's
  first write collides (§10.2, row 6).
- `CUSTOMER.PHONE CHAR(10)` blank-pads the 9-digit phones: `'612345678 '`.

### 10.2 The storefront against that schema

**What works,** once the backend is running: `create_all()` leaves the 25 legacy
tables alone and adds `order_items` and `payment`, with no error about the
unmapped `category`. A legacy buyer's checkout writes the order, one
`order_items` row and one `shipment` row per line, and a `payment` row. The
trigger decrements stock and the cart is emptied. Streamlit answers on its port
and health check.

**What breaks:**

| # | Symptom | Cause |
|---|---|---|
| 1 | The image build fails without `storefront/.env`, and so does `docker compose config` | `COPY .env .` in both Dockerfiles; `env_file: ".env"` in compose |
| 2 | On a fresh `up` the backend exits: `Connection refused` | `create_all()` runs at import while PostgreSQL is still initialising; `depends_on` has no health check and there is no restart policy |
| 3 | Every sign-up returns 500 | passlib 1.7.4 cannot drive bcrypt 5.0: `bcrypt.__about__` is gone, then its self-test raises `ValueError: password cannot be longer than 72 bytes` |
| 4 | A new sign-up cannot shop: every cart call returns 500 | `/customers/` writes `CUSTOMER` only, while `CART.BUYER_ID` references `BUYER` |
| 5 | `GET /orders/{buyer_id}` returns 500 for a buyer with any legacy order, which is all 100,000 | the response model requires `payment` and `shipment`; legacy orders have neither |
| 6 | Checkout returns 500 when the next identity value is already taken | identity sequences behind the loaded ids (§10.1) |
| 7 | Adding an unknown product returns 500 | `prod.price` on `None` |
| 8 | Adding a negative quantity returns 500 | the `CHECK` violation is not handled |
| 9 | The cart accepts 1,000 units of a product with 3 in stock, and every later checkout returns 500 | no stock check before the trigger, the trigger's error is not mapped to a 4xx, and there is no endpoint to remove a cart line |
| 10 | The order response shows one shipment for a two-line order | `Orders.shipment` is `uselist=False`; SQLAlchemy warns "Multiple rows returned" |
| 11 | Emails on reserved domains such as `.test` are rejected with 422 | `EmailStr` (email-validator 2.3). Matters if the load generator invents domains |

**Drift to reconcile, not crashes:**
- `ORDERS.ORDER_DATE` is `DATE`, so storefront orders lose their time (the API
  returns `T00:00:00`), while the clickstream will carry timestamps.
- `ORDERS.PAYMENT_ID` stays null for storefront orders, and `payment` has no
  amount.
- `order_items.price_at_purchase` and `cart.total_price` are
  `double precision`; a cart total came back as `25.98042863802737`.
- Shipments get a null `carrier_id`, status `processing`, and an estimate of
  today + 7 days.
- `Carrier.name` maps a column that does not exist (`CARRIER_NAME`). Nothing
  reads carriers yet, so it has not failed.
- The UI prints prices with `$`.
- Pydantic warns that `orm_mode` is now `from_attributes`; Compose warns that
  `version:` is obsolete.

**Footprint** (idle, near-empty database): backend 57 MiB, frontend 31 MiB,
PostgreSQL 40 MiB. The images are 821 MB (backend) and 818 MB (frontend),
because each installs both apps' dependencies: the backend's requirements
include Streamlit, the root file includes FastAPI and SQLAlchemy. The base image,
`python:3.9-slim`, is past end of life (October 2025).

**Host ports:** the backend's 8000 is also Airbyte's default local port. On the
build machine, 8501 was already in use and 58000 sat inside a Windows excluded
port range (57944-58043). Make host ports configurable in the root
`compose.yaml`.

### 10.3 The CSV extract against the schema

Measured with `COPY … (FORMAT csv)` into text staging tables, then
`INSERT … SELECT` into the legacy tables, for `customer`, `buyer`, `category`,
`product` and `review`. The key and length checks ran in Python over all 25
CSVs.

- **Every primary key, unique constraint and foreign key holds.** No value
  exceeds its `VARCHAR` length, and no card number overflows `BIGINT`.
- **Two inserts fail on `NOT NULL`:** 6 empty `PRODUCT.P_NAME` and 14 empty
  `REVIEW.R_DESC`. With those rows set aside, everything else loads: customer
  130,766, buyer 100,000, product 42,852, review 111,308.
- **The "4 null first names" are the strings `None`, `NA`, `N/A` and `NULL`.**
  `COPY` keeps them as text and they load; pandas reads them as missing. The
  same trap is in `review`: 13 `R_DESC` and 21 `TITLE` values are NA-like
  strings. Keep them: a loader on pandas defaults turns them into nulls.
- **No product is priced 0.** The lowest price is 0.00043.
  - 5 products round to 0.00 in `NUMERIC(10,2)`, with 15 reviews.
  - 706 products are under 1.00, with 1,503 reviews.
  - 2 are above 1,000 (1,069.00 and 2,143.46), with one review each.
  - 35,205 of 42,858 prices have more than two decimals, left by the
    normal-distribution fill.
- **More defects for the dataset card:**
  - CVVs lost their leading zeros in `SMALLINT`: 961 have one digit and 8,440
    two, the shares a uniform 000-999 draw gives.
  - Card numbers are 11 to 19 digits long.
  - Every review has `SELLER_PRODUCT_FLAG = 'S'`, although all 111,322 are
    linked to both a seller and a product.
