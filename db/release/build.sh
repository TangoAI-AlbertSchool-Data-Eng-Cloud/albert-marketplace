#!/usr/bin/env bash
# Build the release assets from the seeded database (docs/build-spec.md §5.7).
#
# Run it with:  docker compose --profile build run --rm release
# It writes into RELEASE_DIR (default ./data/release), mounted at /out:
#
#   marketplace.dump     the whole database, pg_dump's custom format
#   legacy_csv.tar.gz    one CSV per table, the 25 legacy ones with their index column
#   calibration.json     what the history generator was calibrated on
#   DATASET_CARD.md      licence, attribution, defects, assumptions
#   MANIFEST.json        version, row counts, date range, the seed and end date
#   CHECKSUMS            sha256 of each of the above
#
# The CSVs are byte-identical between runs; marketplace.dump is not, because
# the custom format records when it was taken.
set -euo pipefail

OUT=${OUT_DIR:-/out}
CSV_DIR="$OUT/legacy_csv"
VERSION=${DATASET_VERSION:-dev}
SEED=${DATASET_SEED:-}
END_DATE=${DATASET_END_DATE:-}
SCALE=${DATASET_SCALE:-1.0}

# In the order db/load_legacy.sql loads them. The 25 legacy tables keep the
# index column the original extract was exported with; ORDER_ITEMS and PAYMENT
# came later, from the database itself, so they have none.
LEGACY_TABLES="customer shipping_details customer_shipping payment_details customer_payment
    subscription buyer seller review seller_reviews review_images category product
    wishlist_item seller_products product_reviews product_images daily_deals carrier
    cart cart_items discount orders shipment returns"
NEW_TABLES="order_items payment"

q() { psql --no-psqlrc --quiet --no-align --tuples-only --command "$1"; }

columns() {  # quoted column names, in the table's own order
    q "SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
       FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = '$1'"
}

header() {  # the same names, as the CSV header spells them
    q "SELECT string_agg(column_name, ',' ORDER BY ordinal_position)
       FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = '$1'"
}

primary_key() {  # primary key columns, in key order: the export's row order
    q "SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY k.ord)
       FROM pg_index i
       CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
       JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
       WHERE i.indrelid = '$1'::regclass AND i.indisprimary"
}

export_table() {  # $1 table, $2 "indexed" to add the index column
    local table=$1 mode=${2:-plain} cols keys head
    cols=$(columns "$table")
    head=$(header "$table")
    keys=$(primary_key "$table")
    if [ "$mode" = indexed ]; then
        printf ',%s\n' "$head" > "$CSV_DIR/$table.csv"
        psql --no-psqlrc --quiet --command \
            "\copy (SELECT row_number() OVER (ORDER BY $keys) - 1, $cols FROM $table ORDER BY $keys) TO STDOUT WITH (FORMAT csv)" \
            >> "$CSV_DIR/$table.csv"
    else
        printf '%s\n' "$head" > "$CSV_DIR/$table.csv"
        psql --no-psqlrc --quiet --command \
            "\copy (SELECT $cols FROM $table ORDER BY $keys) TO STDOUT WITH (FORMAT csv)" \
            >> "$CSV_DIR/$table.csv"
    fi
    printf '  %-18s %8s rows  %6s\n' "$table" "$(q "SELECT count(*) FROM $table")" \
        "$(du -h "$CSV_DIR/$table.csv" | cut -f1)"
}

echo "Albert's Marketplace release $VERSION"
echo
echo "CSV export"
rm -rf "$CSV_DIR"
mkdir -p "$CSV_DIR"
for table in $LEGACY_TABLES; do export_table "$table" indexed; done
for table in $NEW_TABLES; do export_table "$table"; done
tar --create --gzip --sort=name --owner=0 --group=0 --numeric-owner --mtime='@0' \
    --file "$OUT/legacy_csv.tar.gz" --directory "$OUT" legacy_csv
rm -rf "$CSV_DIR"

echo
echo "Database dump"
pg_dump --format=custom --compress=9 --no-owner --no-privileges --file "$OUT/marketplace.dump"

echo
echo "Manifest"
q "SELECT jsonb_pretty(jsonb_build_object(
       'dataset', 'albert-marketplace',
       'version', '$VERSION',
       'built_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),
       'seed', nullif('$SEED', ''),
       'end_date', nullif('$END_DATE', ''),
       'scale', '$SCALE'::numeric,
       'postgres_version', current_setting('server_version'),
       'first_order_date', (SELECT min(order_date)::text FROM orders),
       'last_order_date', (SELECT max(order_date)::text FROM orders),
       'revenue_eur', (SELECT sum(amount) FROM payment),
       'stock_units', (SELECT sum(qty) FROM product),
       'rows', (SELECT jsonb_object_agg(table_name, n)
                FROM (SELECT c.relname AS table_name,
                             (xpath('/row/c/text()',
                                 query_to_xml(format('SELECT count(*) AS c FROM public.%I', c.relname),
                                              false, true, '')))[1]::text::bigint AS n
                      FROM pg_class c
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                      WHERE n.nspname = 'public' AND c.relkind = 'r'
                        AND c.relname <> 'schema_migrations') counts)
   ))" > "$OUT/MANIFEST.json"

cp /card/dataset-card.md "$OUT/DATASET_CARD.md"
cp /calibration/calibration.json "$OUT/calibration.json"

echo
echo "Checksums"
cd "$OUT"
sha256sum marketplace.dump legacy_csv.tar.gz calibration.json DATASET_CARD.md MANIFEST.json > CHECKSUMS
cat CHECKSUMS
echo
ls -lh "$OUT" | tail -n +2
