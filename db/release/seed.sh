#!/usr/bin/env bash
# Restore the released dataset into an empty database, before the migrations
# run (docs/build-spec.md §5.7). The `seed` service in compose.yaml runs this;
# `seed-fetch` has already downloaded the dump, or left /seed empty.
#
# It does nothing at all when the database already has the schema, so restarting
# the stack, or starting it on a database built by hand, never overwrites data.
set -euo pipefail

# A dump built here (RELEASE_DIR, mounted at /local) wins over a downloaded one.
if [ -n "${SEED_DUMP:-}" ]; then
    DUMP=$SEED_DUMP
elif [ -f /local/marketplace.dump ]; then
    DUMP=/local/marketplace.dump
else
    DUMP=/seed/marketplace.dump
fi

if [ "$(psql --no-psqlrc --quiet --no-align --tuples-only \
        --command "SELECT to_regclass('public.orders') IS NOT NULL")" = t ]; then
    echo "The database already has the marketplace schema: nothing to restore."
    exit 0
fi

if [ ! -f "$DUMP" ]; then
    echo "No dump at $DUMP: starting on an empty database."
    echo "The migrations will create the schema; db/load_legacy.sql and the"
    echo "history generator can fill it (see README.md)."
    exit 0
fi

if [ -n "${SEED_SHA256:-}" ]; then
    echo "Checking the dump against SEED_SHA256"
    echo "$SEED_SHA256  $DUMP" | sha256sum --check --status ||
        { echo "The dump does not match SEED_SHA256. Delete it and start again."; exit 1; }
fi

echo "Restoring $(du -h "$DUMP" | cut -f1) from $DUMP. This takes a minute or so."
# The custom format restores the data before it creates the triggers, so
# trg_update_inventory does not fire on the restored orders.
pg_restore --dbname "postgres://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT:-5432}/${PGDATABASE}" \
    --no-owner --no-privileges --exit-on-error --single-transaction "$DUMP"
echo "Restored: $(psql --no-psqlrc --quiet --no-align --tuples-only \
    --command "SELECT count(*) FROM orders") orders."
