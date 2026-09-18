-- Step 5 checks on a generated history. Run with: psql -v end=YYYY-MM-DD
\set ON_ERROR_STOP 0
\pset pager off

\echo '=== H1 counts'
SELECT (SELECT count(*) FROM orders) AS orders, (SELECT count(*) FROM order_items) AS lines,
       (SELECT count(*) FROM payment) AS payments, (SELECT count(*) FROM shipment) AS shipments,
       (SELECT count(*) FROM carrier) AS carriers;

\echo '=== H2 order dates within the three years before the end date'
SELECT min(order_date), max(order_date),
       (DATE :'end' - INTERVAL '3 years')::date AS window_start, DATE :'end' - 1 AS window_last_day
FROM orders;

\echo '=== H3 twin gaps: order i + 111322 minus order i, in days'
SELECT t.order_date - o.order_date AS gap_days, count(*)
FROM orders o JOIN orders t ON t.order_id = o.order_id + 111322
GROUP BY 1 ORDER BY 1;

\echo '=== H4 each original has its reviewed product; twins have identical lines'
SELECT count(*) AS originals_without_reviewed_product
FROM orders o
JOIN product_reviews pr ON pr.review_id = 96000 + o.order_id
LEFT JOIN order_items oi ON oi.order_id = o.order_id AND oi.p_id = pr.p_id
WHERE o.order_id <= 111322 AND oi.p_id IS NULL;
SELECT
  (SELECT count(*) FROM (SELECT order_id, p_id, qty, price_at_purchase FROM order_items WHERE order_id <= 111322
                         EXCEPT SELECT order_id - 111322, p_id, qty, price_at_purchase FROM order_items WHERE order_id > 111322) a) AS original_lines_missing_in_twin,
  (SELECT count(*) FROM (SELECT order_id - 111322, p_id, qty, price_at_purchase FROM order_items WHERE order_id > 111322
                         EXCEPT SELECT order_id, p_id, qty, price_at_purchase FROM order_items WHERE order_id <= 111322) b) AS twin_lines_missing_in_original;

\echo '=== H5 line prices: product price rounded to cents; 0.00 only on reviewed products'
SELECT count(*) AS price_mismatches FROM order_items oi JOIN product p USING (p_id) WHERE oi.price_at_purchase <> round(p.price, 2);
SELECT count(*) FILTER (WHERE oi.price_at_purchase = 0) AS zero_price_lines,
       count(*) FILTER (WHERE oi.price_at_purchase = 0 AND oi.p_id <> pr.p_id) AS zero_price_extra_lines
FROM order_items oi
JOIN product_reviews pr ON pr.review_id = 96000 + CASE WHEN oi.order_id > 111322 THEN oi.order_id - 111322 ELSE oi.order_id END;
SELECT count(*) AS lines_on_products_without_reviews
FROM order_items oi WHERE NOT EXISTS (SELECT 1 FROM product_reviews pr WHERE pr.p_id = oi.p_id);

\echo '=== H6 payments: one per order, amount = its lines, the order''s card, paid on the order date'
SELECT count(*) AS orders_without_exactly_one_payment
FROM orders o LEFT JOIN (SELECT order_id, count(*) AS c FROM payment GROUP BY order_id) p USING (order_id)
WHERE coalesce(p.c, 0) <> 1;
SELECT count(*) AS amount_mismatches
FROM payment p JOIN (SELECT order_id, sum(qty * price_at_purchase) AS s FROM order_items GROUP BY order_id) l USING (order_id)
WHERE p.amount <> l.s;
SELECT count(*) AS card_mismatches FROM payment p JOIN orders o USING (order_id) WHERE p.payment_id IS DISTINCT FROM o.payment_id;
SELECT count(*) AS paid_on_another_day FROM payment p JOIN orders o USING (order_id) WHERE p.created_at::date <> o.order_date;
SELECT method, status, count(*), sum(amount) AS revenue, min(transaction_id), max(transaction_id) FROM payment GROUP BY 1, 2;

\echo '=== H7 shipments: one per line; status from age at the end date'
SELECT count(*) AS lines_without_exactly_one_shipment
FROM order_items oi LEFT JOIN (SELECT order_id, p_id, count(*) AS c FROM shipment GROUP BY 1, 2) s USING (order_id, p_id)
WHERE coalesce(s.c, 0) <> 1;
SELECT s.status, count(*), min(DATE :'end' - o.order_date) AS min_age, max(DATE :'end' - o.order_date) AS max_age,
       min(s.actual_delivery_date - o.order_date) AS min_delivery_days, max(s.actual_delivery_date - o.order_date) AS max_delivery_days,
       count(*) FILTER (WHERE s.est_delivery_date <> o.order_date + 7) AS estimate_mismatches,
       count(*) FILTER (WHERE s.actual_delivery_date IS NULL) AS without_delivery_date
FROM shipment s JOIN orders o USING (order_id)
GROUP BY 1 ORDER BY 1;
SELECT c.carrier_id, c.carrier_name, count(*) FROM shipment s JOIN carrier c USING (carrier_id) GROUP BY 1, 2 ORDER BY 1;

\echo '=== H8 identity sequences at their table''s highest id'
SELECT c.table_name,
       pg_sequence_last_value(pg_get_serial_sequence(c.table_name, c.column_name)::regclass) AS sequence_at,
       (xpath('/row/m/text()', query_to_xml(format('SELECT max(%I) AS m FROM %I', c.column_name, c.table_name), false, true, '')))[1]::text AS max_id
FROM information_schema.columns c
WHERE c.table_schema = 'public' AND c.is_identity = 'YES' AND c.table_name IN ('carrier', 'payment', 'shipment', 'orders')
ORDER BY 1;

\echo '=== H9 stock and the legacy tables the history does not touch (compare with the step 3 load)'
SELECT 'product' AS t, md5(string_agg(x::text, E'\n' ORDER BY x::text COLLATE "C")) FROM product x
UNION ALL SELECT 'review', md5(string_agg(x::text, E'\n' ORDER BY x::text COLLATE "C")) FROM review x;

\echo '=== H10 size'
SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;
