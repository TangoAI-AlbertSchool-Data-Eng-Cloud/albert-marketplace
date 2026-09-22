# Albert's Marketplace: dataset card

Albert's Marketplace is a fictional European online marketplace for beauty
products. This dataset is its operational database: three years of orders,
payments and shipments over a catalogue of real product and review text, with
synthetic customers in six EU countries.

It exists to be ingested. It is the source system for a data engineering
course, so it carries the defects a real operational database carries. They are
listed below on purpose: **do not treat this data as clean.**

| | |
|---|---|
| Version | v1.0.0 |
| Database | PostgreSQL 17 |
| Licence | data CC BY-SA 4.0, code MIT |
| Source repository | https://github.com/TangoAI-AlbertSchool-Data-Eng-Cloud/albert-marketplace |
| Every person in it | synthetic |

`MANIFEST.json` in the release records the exact version, build time, seed, end
date, scale and row counts of the copy you downloaded.

## Files

| File | What it is |
|---|---|
| `marketplace.dump` | The whole database, `pg_dump --format=custom`. Restore it with `pg_restore`, or let `docker compose up` do it. |
| `legacy_csv.tar.gz` | One CSV per table. The 25 tables of the original extract keep the unnamed index column pandas wrote (`Unnamed: 0`); `order_items` and `payment`, which came later, do not. |
| `calibration.json` | The seasonality index and basket distributions the order history was drawn from, measured on Online Retail II. |
| `MANIFEST.json` | Version, build time, seed, end date, scale, row counts, date range. |
| `CHECKSUMS` | sha256 of each file above. |

The CSVs are byte-identical between builds of the same dataset version.
`marketplace.dump` is not: pg_dump's custom format records when it was taken.

## What is in it

27 tables. The largest, and what they hold:

| Table | Rows | |
|---|---:|---|
| `customer` | 130,766 | people, with their phone, email and password |
| `buyer` | 100,000 | the customers who buy; the other 30,766 are sellers |
| `shipping_details` | 200,001 | addresses in six countries |
| `payment_details` | 100,000 | saved cards |
| `subscription` | 50,091 | prime-like subscriptions |
| `product` | 42,858 | the catalogue, with price and stock |
| `review` | 111,322 | review text, title and rating |
| `orders` | 222,644 | three years of orders, half of them duplicates |
| `order_items` | 408,560 | order lines: product, units, unit price |
| `payment` | 222,644 | one transaction per order, €39,199,900.62 in all |
| `shipment` | 408,560 | one shipment per order line |
| `carrier` | 4 | fictional carriers |
| `cart`, `cart_items` | 0 | filled by the storefront, empty in the dataset |
| `daily_deals`, `discount`, `returns` | 0 | empty in the extract, and left empty |

The schema is the one in `db/migrations/` in the repository: 25 tables from the
original extract, plus `ORDER_ITEMS` (order lines) and `PAYMENT` (one
transaction per order).

## Where the data comes from

- **Products and reviews: McAuley Lab's Amazon Reviews'23,** beauty category.
  Product names, descriptions, prices, image URLs, review titles, review text
  and ratings are real rows from that dataset. Buyer IDs are its pseudonymous
  user IDs.
  Hou, Y., Li, J., He, Z., Yan, A., Chen, X., McAuley, J. (2024). *Bridging
  Language and Items for Retrieval and Recommendation.* arXiv:2403.03952.
- **Seasonality and basket sizes: UCI Online Retail II,** used for calibration
  only. No row of it is redistributed here.
  Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning
  Repository. https://doi.org/10.24432/C5CG6D. CC BY 4.0.
- **Addresses: GeoNames postal codes** (https://www.geonames.org/), CC BY 4.0:
  real combinations of postcode, town and region for the six countries.
- **The country mix and the regional weights: Eurostat.** Population on
  1 January 2026 (`tps00001`) for the countries, and population by NUTS region
  (`demo_r_pjanaggr3`) for the regions inside them.
- **Everything else is synthetic:** names, street numbers, email addresses,
  phone numbers, passwords, card numbers, orders, payments and shipments. No
  customer in this dataset is a real person, and no card number is a real card.

**Images are URLs only.** Product and review images are links into Amazon's
image hosts, exactly as the source dataset gives them. Nothing is downloaded or
redistributed here, and the links may rot.

## How it was made

1. The 25-table extract of the source dataset is loaded into the schema in
   `db/migrations/`, with its defects (below).
2. `generators/history/generate.py` redraws the order history on top of it:
   order dates, order lines, payments, shipments and carriers, and localised
   addresses and phone numbers for every customer. Products, reviews, sellers,
   stock and the catalogue are left as loaded.
3. The release is packaged from the resulting database.

The generator is deterministic: the same seed and the same end date give the
same database, table for table. `MANIFEST.json` records both for this build.

## Generator assumptions

Everything the generator invented, and what it assumed while inventing it.

**Order volume and dates**

- Orders are spread over the three years before the end date, with a
  week-of-year seasonality index measured on Online Retail II (2009-2011) and
  rescaled to a mean of 1.0.
- Three weeks of that index are smoothed to the mean of their neighbours (weeks
  22, 35 and 52), because the shop it was measured on closed for Christmas and
  had two isolated spikes. Week 51 is taken from 2009 alone, for the same
  reason. ISO week 53 reuses week 52's value.
- Order volume has no year-on-year trend: 2024 is as busy as 2026.

**Baskets**

- The number of distinct products in an order, and the units of each product,
  follow the distributions measured on consumer-like invoices of Online Retail
  II. Units keep their pack-size spikes: 6, 12, 4, 8 and 10 units are more
  common than their neighbours, because that source sells in packs.
- A line's price is the product's catalogue price rounded to cents, so a line is
  units times price. The history has no per-order discount.
- An order's lines include the product its review is about; any further line is
  drawn from products that have reviews, never from one whose price rounds to
  €0.00.

**Duplicate orders**

- Every order appears twice (see the defects below). The twin is dated 0 to 4
  days after the original, with the gap sizes measured in the extract, and
  carries the same lines.

**Payments**

- One `PAYMENT` row per order, on the order's date, for the sum of its lines.
- A card payment uses the buyer's default saved card.

**Shipments**

- One shipment per order line, with one of four fictional carriers.
- Status follows the order's age at the end date: over 10 days `delivered`
  (actual delivery 2 to 9 days after the order), 3 to 10 days `in_transit`,
  under 3 days `processing`.

**Customers and addresses**

- Customers are spread over France, Germany, Italy, Spain, the Netherlands and
  Belgium, weighted by each country's population.
- Inside a country, a region is drawn by its population, then a postcode
  uniformly inside the region, then a town uniformly inside the postcode.
  GeoNames gives no population below the region, so within a region a village is
  as likely as a city: small places are over-represented and large ones
  under-represented. The region shares themselves match the population.
- Street names come from Faker in the country's language; in Belgium, French in
  Wallonia and Dutch in Flanders and Brussels.
- Dutch postcodes in GeoNames have only their four digits, so the generator adds
  the two letters. It never generates `SS`, `SD` or `SA`: Dutch postcodes avoid
  those combinations because of their association with the Schutzstaffel, the
  Sicherheitsdienst and the Sturmabteilung during the 1940-45 occupation of the
  Netherlands (source: Wikipedia).
- Phone numbers follow each country's mobile format, from simplified prefixes.
  Every customer has one phone, repeated on their addresses.
- A customer's addresses are all in one country, and their billing address is
  their default shipping address glued together without separators, as the
  extract had it.

## Deliberate defects

These are what the course is about. They are in the data on purpose, and a
pipeline built on this dataset is expected to find them.

- **Passwords in plain text**, in `CUSTOMER.PWD`.
- **Card numbers stored with their CVV**, in `PAYMENT_DETAILS`, and CVVs that
  lost their leading zeros: some have one or two digits.
- **Every order appears twice.** The duplicate is a few days later, with the
  same buyer, payment and lines.
- **An index column in the CSVs.** The 25 legacy files start with pandas'
  unnamed index, which `read_csv` calls `Unnamed: 0`.
- **Phone numbers are text with a leading zero.** `pandas.read_csv` with its
  defaults reads them as integers and silently drops that zero, turning a
  10-character French mobile into a 9-digit number.
- **Prices at full floating-point precision**: catalogue prices carry more than
  two decimals, while order lines and payments are rounded to cents.
- **Five products priced below half a cent**, which round to €0.00. The orders
  attached to their 15 reviews keep a €0.00 line.
- **Six products with an empty name, and 14 reviews with empty text.**
- **NA-like strings as values**: `None`, `NA`, `N/A` and `NULL` appear as text in
  name columns, not as nulls.
- **The flat files carry no constraints.** The schema has foreign keys; the CSVs
  do not, and loading them in the wrong order fails.

## What is not in it

- No real person, no real address, no real payment card.
- No image files: only the URLs the source dataset gives.
- No returns, no per-order discounts, and no marketing or web analytics tables.
  The clickstream is produced live by the repository's load generator, not
  shipped here.

## Rebuilding it yourself

Everything needed is in the repository. With the original extract in
`LEGACY_CSV_DIR`, and the seed and end date from `MANIFEST.json`:

```
docker compose --profile build run --rm generate-history --seed 7 --end-date 2026-09-15
docker compose --profile build run --rm release
```

The first command reloads the extract and regenerates the history; the second
writes these files into `data/release/`.

`generate.py` also takes `--scale`, which changes how many orders the three
years hold without touching the customers or the catalogue: `--scale 0.1` for a
tenth of them, `--scale 5` for five times as many. A scaled copy keeps every
assumption and every defect listed here, including the duplicate orders.

## Citing it

> Albert's Marketplace dataset, Albert School, 2026. CC BY-SA 4.0. Derived from
> McAuley Lab's Amazon Reviews'23, with addresses from GeoNames (CC BY 4.0) and
> calibration from UCI Online Retail II (CC BY 4.0).
