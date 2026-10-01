# CLAUDE.md

**Albert's Marketplace** is a fictional European online marketplace for beauty
products. The Data Engineering & Cloud Infrastructure course (MSA-DAT09-02,
Albert School) builds a data platform for it.

**This repo is the company's side:**
- its operational PostgreSQL database
- its storefront
- the generators that give it a realistic order history and live traffic

Students clone it and run it locally as the source system their pipelines
ingest from.

**It is not:**
- the course website (private repo `TANGOAI_EDUCATION`: Docusaurus on Vercel,
  staff material)
- the students' data platform (dbt, Terraform and Airflow live in their own
  group repos)

## Status

Two earlier repos by Charles are imported with their history and are being
adapted, in the order of `docs/build-spec.md` §6:
- `db/`: from `JedhaBootcamp/amazon-database-design`. The notebook that built
  the original data, the diagrams, `db/migrations/` (dbmate, plain SQL: a
  baseline with the legacy schema, trigger and fixed procedure, then
  `order_items`, then wider phone columns), and `db/load_legacy.sql`, which
  loads the legacy CSV extract
  with its defects.
- `storefront/`: from `JedhaBootcamp/amazon-mockup-e-commerce`. FastAPI +
  Streamlit, mapped onto the migrations (it never creates tables), with every
  dependency pinned. `storefront/README.md` lists its endpoints.
- `generators/`: a uv project (Python 3.12, pinned in `uv.lock`), run in
  containers. `history/calibrate.py` writes `history/calibration.json` from
  Online Retail II; `history/generate.py` generates the order history on the
  loaded legacy data, with addresses from `history/places.json` (GeoNames
  postcodes and Eurostat regional populations), which `history/places.py`
  builds. `live/traffic.py` is the load generator, with its own image
  (`generators/Dockerfile`, live dependency group only).
  `tickets/tickets.py` writes support tickets for the LLM course from the
  released dataset (`tickets` compose service, `tickets` dependency group):
  `plan` is deterministic; `write` calls the Anthropic API and is reproducible
  only through its response cache in `data/tickets/cache/`, which ships with
  the tickets. The labels come from the plan, never from the model, and are
  checked by hand before release. Its `outliers` batch reads staff-only briefs
  from `OUTLIER_BRIEFS_DIR`: they encode a course exercise's answer, so they
  never enter this repo, and neither do the plan files or `source_id` columns
  (the released file carries student columns only).
- `compose.yaml` at the root: PostgreSQL 17 (`wal_level=logical`, for the
  students' change data capture), `seed-fetch` and `seed`, which download the
  released dump and restore it into an empty database before the `migrate`
  service runs, the
  storefront (`storefront-api` on port 8100, `storefront-ui` on 8510), Kafka
  (`kafka` on host port 9092, topic `clickstream`), the `load-generator`, and
  `load-legacy`, `calibrate`, `fetch-places`, `generate-history` and `release`
  behind the `build` profile.
  Tear those down with `docker compose --profile build down`: a plain `down`
  leaves their containers behind.
- `docs/critique/`: originals the course critiques, kept unchanged.
- `db/release/`: `build.sh` packages the release assets from the seeded
  database into `data/release/` (dump, CSV export, calibration, dataset card,
  manifest, checksums); `seed.sh` restores one. `docs/dataset-card.md` ships
  with them. The root `README.md` is what students read first, and `LICENSE`
  is MIT plus the CC BY-SA 4.0 note for the data.
- `tests/`: the checks behind every verified claim in the build spec, one
  runner per step, each in its own compose project (`tests/README.md`).

**Read `docs/build-spec.md` before changing anything.** It is the plan, and it
holds every measurement taken so far (data profile, schema mismatches,
calibration numbers).

## Context outside this repo

Add these with `/add-dir` when needed. Treat them as read-only:

| What | Path |
|---|---|
| Course bible (§4 the company, §5 data, §0 decisions D1-D19) | `C:\Users\charl\Documents\Work\ALBERT_SCHOOL\TANGOAI_EDUCATION\docs\data-engineering\ressources\course-bible.md` |
| Original 25-table CSV extract and `db_creation.sql` | `C:\Users\charl\Documents\Work\ALBERT_SCHOOL\TANGOAI_EDUCATION_assets\datasets\Amazon\` |
| Online Retail II (calibration only) | `C:\Users\charl\Documents\Work\ALBERT_SCHOOL\TANGOAI_EDUCATION_assets\datasets\online_retail_II\online_retail_II.xlsx` |

**The course bible is staff-only material. Never copy its content into this
public repo;** data facts and design decisions are fine, syllabus and teaching
notes are not.

## Non-negotiables

- **This repo is public.** No secrets, no real personal data. Every person,
  address, phone, password and card in it is synthetic, and the README says so.
- **The legacy defects in the seed data are deliberate.** Do not clean them;
  they are what the course teaches:
  - plaintext passwords
  - card numbers with CVV
  - duplicate orders
  - `Unnamed: 0` index columns
  - phone numbers stored as text with a leading zero, which pandas' `read_csv`
    defaults turn into 9-digit integers
- **Defects in running code are not deliberate.** Fix those (the storefront's
  Docker setup, for example), but keep a copy of anything the course uses as a
  "critique this" exercise.
- **Generated data never goes in git.** It goes in `data/` (gitignored) and ships
  as a GitHub release asset.
- **The schema is the contract.** A table change updates the migration, the
  storefront models and both generators in the same commit.
- **Generators are deterministic.** A fixed seed and end date give identical
  output on every run, checked by a checksum. The course teaches idempotency and pins a dataset
  version.
- **Licences:**
  - code is MIT
  - data is CC BY-SA 4.0
- **Attribution** goes in the README and the dataset card:
  - McAuley Lab's Amazon Reviews'23: Hou et al. 2024, "Bridging Language and
    Items for Retrieval and Recommendation"
  - UCI Online Retail II: Chen 2012, CC BY 4.0, used for calibration only
  - GeoNames postal codes (www.geonames.org): CC BY 4.0, used for addresses
- **Product and review images are URLs only.** Never download or redistribute
  them.
- **Never push, publish a release or deploy without Charles's go-ahead.**

## Working on this machine (Windows 11)

- **Long paths are not enabled.** Keep paths short. `core.longpaths` is set in
  this repo.
- **Git Bash heredocs collapse doubled backslashes,** so build escape
  characters with `chr(92)` in inline scripts.
- **The console encoding is cp1252.** Set `PYTHONIOENCODING=utf-8` before
  printing data: review text contains emoji, and a print once crashed on one.
- **Docker Desktop runs everything.** Students will also run this on laptops
  where Airbyte alone needs 8 GB of RAM, so keep the company's own footprint
  small.
- **Docker Desktop is often not running.** Start it
  (`C:\Program Files\Docker\Docker\Docker Desktop.exe`) and wait for
  `docker info` before any container work.
- **Ports 8501 and 57744-58413 are unavailable here:** another project's
  container holds 8501, and Windows reserves the rest.
- **Windows application control blocks compiled packages that uv downloads**
  (pandas failed with "DLL load failed"). Pure-Python scripts run on the host;
  run anything that needs pandas or similar in a `python` container.

## Owner

Charles (GitHub `Charlestng`) teaches the course. He is at home with data
tooling (Airflow, dbt, Docker, Terraform, Snowflake) and wants exact steps for
anything web or deployment related.
