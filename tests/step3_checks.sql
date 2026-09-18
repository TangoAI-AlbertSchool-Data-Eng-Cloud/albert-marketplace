-- Step 3 checks, after load_legacy.sql. C6 consumes one order id, so run it last.
\set ON_ERROR_STOP 0
\pset pager off

\echo '=== C1 row counts against the extract (build-spec §3)'
WITH expected (t, n) AS (VALUES
    ('buyer', 100000), ('carrier', 0), ('cart', 0), ('cart_items', 0), ('category', 2),
    ('customer', 130766), ('customer_payment', 100000), ('customer_shipping', 200001),
    ('daily_deals', 0), ('discount', 0), ('order_items', 0), ('orders', 222644),
    ('payment_details', 100000), ('product', 42858), ('product_images', 186837),
    ('product_reviews', 111322), ('returns', 0), ('review', 111322), ('review_images', 119382),
    ('seller', 30766), ('seller_products', 46593), ('seller_reviews', 111322), ('shipment', 0),
    ('shipping_details', 200001), ('subscription', 50091), ('wishlist_item', 24810)),
actual AS (
    SELECT table_name AS t,
           (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I', table_name), false, true, '')))[1]::text::bigint AS n
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name <> 'schema_migrations')
SELECT t AS table_name, e.n AS expected, a.n AS loaded,
       CASE WHEN e.n = a.n THEN 'ok' ELSE 'MISMATCH' END AS status
FROM expected e FULL JOIN actual a USING (t)
ORDER BY t;

\echo '=== C2 deliberate defects still there'
SELECT 'plaintext pwd (no bcrypt prefix)' AS defect, count(*) FILTER (WHERE pwd NOT LIKE '$2%') AS n FROM customer
UNION ALL SELECT 'pwd length min', min(length(pwd)) FROM customer
UNION ALL SELECT 'pwd length max', max(length(pwd)) FROM customer
UNION ALL SELECT 'payment rows with a CVV', count(cvv) FROM payment_details
UNION ALL SELECT 'CVV with 1 digit', count(*) FILTER (WHERE cvv < 10) FROM payment_details
UNION ALL SELECT 'CVV with 2 digits', count(*) FILTER (WHERE cvv BETWEEN 10 AND 99) FROM payment_details
UNION ALL SELECT 'orders repeating (buyer, payment, date), beyond the first',
    (SELECT sum(c - 1) FROM (SELECT count(*) AS c FROM orders GROUP BY buyer_id, payment_id, order_date HAVING count(*) > 1) g)
UNION ALL SELECT 'customer phones, 9 characters', count(*) FILTER (WHERE length(phone) = 9) FROM customer
UNION ALL SELECT 'customer phones, 10 characters', count(*) FILTER (WHERE length(phone) = 10) FROM customer
UNION ALL SELECT 'customer phones not starting with 0', count(*) FILTER (WHERE phone NOT LIKE '0%') FROM customer
UNION ALL SELECT 'address phones, 9 characters', count(*) FILTER (WHERE length(phone) = 9) FROM shipping_details
UNION ALL SELECT 'address phones, 10 characters', count(*) FILTER (WHERE length(phone) = 10) FROM shipping_details
UNION ALL SELECT 'first names None, NA, N/A, NULL', count(*) FILTER (WHERE fname IN ('None', 'NA', 'N/A', 'NULL')) FROM customer
UNION ALL SELECT 'empty product names', count(*) FILTER (WHERE p_name = '') FROM product
UNION ALL SELECT 'empty review texts', count(*) FILTER (WHERE r_desc = '') FROM review
UNION ALL SELECT 'NA-like review texts', count(*) FILTER (WHERE r_desc IN ('None', 'NA', 'N/A', 'NULL', 'n/a')) FROM review
UNION ALL SELECT 'NA-like review titles', count(*) FILTER (WHERE title IN ('None', 'NA', 'N/A', 'NULL', 'n/a')) FROM review
UNION ALL SELECT 'prices with more than 2 decimals', count(*) FILTER (WHERE scale(price) > 2) FROM product
UNION ALL SELECT 'products rounding to 0.00', count(*) FILTER (WHERE round(price, 2) = 0) FROM product
UNION ALL SELECT 'sellers without SELLER_NAME', count(*) FILTER (WHERE seller_name IS NULL) FROM seller
UNION ALL SELECT 'orders without a discount', count(*) FILTER (WHERE discount_id IS NULL) FROM orders
UNION ALL SELECT 'reviews flagged S', count(*) FILTER (WHERE seller_product_flag = 'S') FROM review;

\echo '=== C3 exact values'
SELECT p_id, price::text FROM product WHERE p_id IN ('B09FD6S7WS', 'B088BCCTN6', 'B00E759GX6') ORDER BY p_id;
SELECT min(order_date), max(order_date) FROM orders;

\echo '=== C4 identity sequences against their table''s highest id'
SELECT c.table_name, c.column_name,
       pg_sequence_last_value(pg_get_serial_sequence(c.table_name, c.column_name)::regclass) AS sequence_at,
       (xpath('/row/m/text()', query_to_xml(format('SELECT max(%I) AS m FROM %I', c.column_name, c.table_name), false, true, '')))[1]::text AS max_id
FROM information_schema.columns c
WHERE c.table_schema = 'public' AND c.is_identity = 'YES'
ORDER BY 1;

\echo '=== C5 stock trigger enabled again (O = enabled)'
SELECT tgname, tgenabled FROM pg_trigger WHERE tgname = 'trg_update_inventory';

\echo '=== C6 an order with a default id no longer collides (rolled back)'
BEGIN;
INSERT INTO orders (buyer_id, order_date)
SELECT buyer_id, DATE '2026-10-01' FROM buyer ORDER BY buyer_id LIMIT 1
RETURNING order_id;
ROLLBACK;

\echo '=== C7 size'
SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;
