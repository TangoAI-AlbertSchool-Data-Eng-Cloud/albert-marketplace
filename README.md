# Albert's Marketplace

Albert's Marketplace is a fictional European online marketplace for beauty
products. This repository is the company's own side of it: the operational
PostgreSQL database, the storefront that writes to it, and the generators that
give it three years of order history and a stream of live traffic.

It is the source system for the Data Engineering & Cloud Infrastructure course
at Albert School. You run it locally, and build your pipelines against it:
extract from its database or its Kafka topic, and land the data wherever your
platform lives.

**Everything in it is made up.** Every customer, address, phone number,
password and payment card is synthetic. Product and review text comes from a
public research dataset, and images are URLs into someone else's host, never
copies. See [`docs/dataset-card.md`](docs/dataset-card.md).

## Start it

You need Docker Desktop (or Docker Engine with Compose v2), about 6 GB of free
disk and 3 GB of free RAM.

```
git clone https://github.com/TangoAI-AlbertSchool-Data-Eng-Cloud/albert-marketplace.git
cd albert-marketplace
docker compose up
```

The first start downloads the dataset (a 66 MB database dump, published as a
release asset) and restores it, which takes a minute or two. Later starts find
the data already there and skip it. Then:

| What | Where | |
|---|---|---|
| Storefront (the shop) | http://localhost:8510 | Streamlit |
| Storefront API | http://localhost:8100/docs | FastAPI, [endpoints](storefront/README.md) |
| PostgreSQL | `localhost:5432` | database `marketplace`, user `postgres`, password `postgres` |
| Kafka | `localhost:9092` | topic `clickstream` |

The load generator starts with everything else: it shops through the API on a
simulated clock, so orders, payments and shipments keep arriving in the
database, and clickstream events keep arriving on the Kafka topic.

Stop it with `Ctrl+C`, and `docker compose down` to remove the containers. The
data lives in a Docker volume and survives both; `docker compose down -v`
deletes it, and the next start downloads the dataset again.

## Connect to it

From your machine:

```
psql postgresql://postgres:postgres@localhost:5432/marketplace
```

From another container on your machine (Airbyte, Airflow, dbt), the database is
`host.docker.internal:5432` and Kafka is `host.docker.internal:29092`.

PostgreSQL runs with `wal_level=logical`, so change data capture works: create a
replication slot, or point Airbyte or Debezium at it. A forgotten slot is
dropped once it holds back 512 MB of write-ahead log, so it cannot fill your
disk.

## What is in here

| | |
|---|---|
| [`db/`](db/) | The schema, as dbmate migrations, and `load_legacy.sql`, which loads the original CSV extract with its defects |
| [`storefront/`](storefront/) | FastAPI backend and Streamlit shop ([README](storefront/README.md)) |
| [`generators/`](generators/) | `history/` builds the order history; `live/traffic.py` is the load generator |
| [`tests/`](tests/) | The checks behind the build spec's verified claims |
| [`docs/`](docs/) | [Dataset card](docs/dataset-card.md), [build spec](docs/build-spec.md), and `critique/`: original files the course picks apart |
| `data/` | Downloads and generated files. Never in git |

The schema is the contract between all of it: 25 tables from the original
extract, plus `ORDER_ITEMS` (order lines) and `PAYMENT` (one transaction per
order).

## Settings

Every setting has a default, so `docker compose up` needs no `.env`. Override
any of them in the environment or in a `.env` file next to `compose.yaml`.

| Variable | Default | |
|---|---|---|
| `DB_PORT`, `API_PORT`, `UI_PORT` | 5432, 8100, 8510 | host ports, if one is taken |
| `KAFKA_PORT`, `KAFKA_DOCKER_PORT` | 9092, 29092 | from your machine, from another container |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | postgres, postgres, marketplace | |
| `SEED_URL` | the release asset | set it empty to start on an empty database |
| `CLOCK_ACCELERATION` | 15 | how much faster than real time the live traffic runs |
| `ORDERS_PER_DAY` | 200 | orders per simulated day |
| `TRAFFIC_SEED` | 20260915 | the load generator's seed |
| `SIMULATION` | true | lets the load generator date orders on its own clock. Off, the storefront uses the real time |

To run without the live traffic:
`docker compose up db seed migrate storefront-api storefront-ui`.

## Rebuild the dataset

You do not need this to follow the course: the release asset is the dataset.
It is here because the course reads it.

The `build` profile holds the services that make the data. They need the
original CSV extract in `LEGACY_CSV_DIR` and, for the calibration, Online
Retail II in `RETAIL_XLSX_DIR`.

```
docker compose --profile build run --rm load-legacy        # CSVs -> database
docker compose --profile build run --rm calibrate          # -> history/calibration.json
docker compose --profile build run --rm fetch-places       # GeoNames -> history/places.json
docker compose --profile build run --rm generate-history --seed 7 --end-date 2026-09-15
docker compose --profile build run --rm release            # -> data/release/
```

`--scale` changes how many orders those three years hold, without touching the
customers or the catalogue: `--scale 0.1` for a tenth of them (a small copy for
a laptop or for CI), `--scale 5` for five times as many. Every rule the full
dataset follows still holds, duplicates included.

The history generator is deterministic: the same seed, end date and scale give
the same database every time. Tear these down with
`docker compose --profile build down`; a plain `down` leaves their containers
behind.

## Licence and attribution

- **Code: MIT** ([LICENSE](LICENSE)).
- **Data: CC BY-SA 4.0.** It is derived from:
  - McAuley Lab's Amazon Reviews'23: Hou, Y., Li, J., He, Z., Yan, A., Chen, X.,
    McAuley, J. (2024). *Bridging Language and Items for Retrieval and
    Recommendation.* arXiv:2403.03952
  - UCI Online Retail II, used for calibration only: Chen, D. (2012). *Online
    Retail II* [Dataset]. UCI Machine Learning Repository.
    https://doi.org/10.24432/C5CG6D. CC BY 4.0
  - GeoNames postal codes (https://www.geonames.org/), CC BY 4.0, for addresses
  - Eurostat population figures, for the country and region mix

The storefront and the original schema began as
[amazon-database-design](https://github.com/JedhaBootcamp/amazon-database-design)
and
[amazon-mockup-e-commerce](https://github.com/JedhaBootcamp/amazon-mockup-e-commerce).
