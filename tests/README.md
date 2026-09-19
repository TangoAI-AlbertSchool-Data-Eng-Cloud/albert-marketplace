# Tests

The checks behind every "verified" line in `docs/build-spec.md`. They are for
whoever maintains this repository, not for students: each one drives Docker
Compose in its own project, on its own ports, so it never touches a stack you
started with `docker compose up`.

They are PowerShell runners (`*_verify.ps1`) that call Python checks (`*.py`)
and psql scripts (`*.sql`). Run one from anywhere:

```
powershell -NoProfile -ExecutionPolicy Bypass -File tests\step7a_verify.ps1
```

## What each one covers

| Runner | Checks |
|---|---|
| `step2_verify.ps1` | Migrations apply, roll back and reapply; the fixed `APPLY_DAILY_DEALS`; `order_items` constraints; the stock trigger |
| `step3_verify.ps1` | The legacy loader: row counts, repeatability, a failed load changing nothing, values identical to the CSVs, the defects still present |
| `step4_verify.ps1` | `calibration.json` reproduces every §5.4 number and is byte-identical between runs |
| `step5_verify.ps1` | The history generator: determinism, calibration fit, §9 rules, localisation, then a storefront checkout |
| `step5_phone_verify.ps1` | The `VARCHAR(15)` phone migration, forwards and backwards |
| `step6_verify.ps1` | The storefront: models against the schema, the API (one check per step 1 failure), the UI flow headless |
| `step7_kafka_verify.ps1` | The broker: topic, all three listeners, memory under load, data surviving restarts |
| `step7a_verify.ps1` | Live traffic at 720x, then every Kafka event against the database |
| `step7b_verify.ps1` | The clock resuming after a restart, `SIMULATION` on and off, the step 6 API tests again |
| `step8_verify.ps1` | The release: its checksums, a cold start that seeds itself from it, the CSV export and its defects, and the stack starting without a dump |

`step1_loadtest.sql`, `step2_checks.sql`, `step3_checks.sql`, `step3_fingerprint.sql`
and `step5_checks.sql` are the psql scripts those runners copy into the database
container. `step3_fingerprint.sql` prints one md5 per table and is what the
determinism checks compare.

## What they need

- Docker Desktop running.
- `LEGACY_CSV_DIR` pointing at the folder with the 25 legacy CSVs, for anything
  that loads or generates data. Each runner falls back to the path on Charles's
  machine.
- `data/release/` built, for `step8_verify.ps1`:
  `docker compose --profile build run --rm release`.
- Python on the host, for the checks the runners call. They only use the
  standard library, except `step7_host_client.py`, which uses `kafka-python`
  through `uv run --with`.

Runs write their logs and dumps next to the scripts; `.gitignore` keeps those
out of the repository.

## Expected values

Some checks compare against measured values: the md5 of each history table for
seed 7 and end date 2026-09-15, the row counts of the legacy extract, and the
numbers in `calibration.json`. When a generator changes on purpose, update those
values in the runner and say so in the build spec.
