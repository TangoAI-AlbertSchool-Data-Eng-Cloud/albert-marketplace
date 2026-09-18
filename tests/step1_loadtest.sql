-- Step 1 load test: do the legacy CSVs fit the legacy schema's NOT NULL columns?
-- Run on a scratch database that has only db_creation.sql, Triggers.sql, Procedures.sql.
\set ON_ERROR_STOP 0
\pset pager off

CREATE SCHEMA stage;
CREATE TABLE stage.customer (idx text, c_id text, fname text, lname text, phone text, email text, pwd text);
CREATE TABLE stage.buyer    (idx text, buyer_id text);
CREATE TABLE stage.category (idx text, category_id text, name text, c_desc text);
CREATE TABLE stage.product  (idx text, p_id text, p_name text, p_desc text, price text, qty text, category_id text);
CREATE TABLE stage.review   (idx text, review_id text, buyer_id text, r_desc text, title text, rating text, seller_product_flag text);
\copy stage.customer FROM '/tmp/customer.csv' WITH (FORMAT csv, HEADER true)
\copy stage.buyer    FROM '/tmp/buyer.csv'    WITH (FORMAT csv, HEADER true)
\copy stage.category FROM '/tmp/category.csv' WITH (FORMAT csv, HEADER true)
\copy stage.product  FROM '/tmp/product.csv'  WITH (FORMAT csv, HEADER true)
\copy stage.review   FROM '/tmp/review.csv'   WITH (FORMAT csv, HEADER true)

\echo '=== what COPY (FORMAT csv) turns into NULL, and the NA-like strings it keeps'
SELECT 'customer.fname' AS col, count(*) FILTER (WHERE fname IS NULL) AS nulls,
       count(*) FILTER (WHERE fname IN ('None', 'NA', 'N/A', 'NULL', 'n/a')) AS na_strings FROM stage.customer
UNION ALL SELECT 'review.r_desc', count(*) FILTER (WHERE r_desc IS NULL),
       count(*) FILTER (WHERE r_desc IN ('None', 'NA', 'N/A', 'NULL', 'n/a')) FROM stage.review
UNION ALL SELECT 'review.title', count(*) FILTER (WHERE title IS NULL),
       count(*) FILTER (WHERE title IN ('None', 'NA', 'N/A', 'NULL', 'n/a')) FROM stage.review
UNION ALL SELECT 'product.p_name', count(*) FILTER (WHERE p_name IS NULL), 0 FROM stage.product;

\echo '=== insert into the legacy tables, in foreign-key order'
INSERT INTO customer SELECT c_id, fname, lname, phone, email, pwd FROM stage.customer;
INSERT INTO buyer SELECT buyer_id FROM stage.buyer;
INSERT INTO category SELECT category_id::int, name, c_desc FROM stage.category;
INSERT INTO product SELECT p_id, p_name, p_desc, price::numeric, qty::int, category_id::int FROM stage.product;
INSERT INTO review SELECT review_id::int, buyer_id, r_desc, title, rating::int, seller_product_flag FROM stage.review;

\echo '--- retry with NULL rows set aside, to see whether anything else breaks'
INSERT INTO customer SELECT c_id, fname, lname, phone, email, pwd FROM stage.customer WHERE fname IS NOT NULL ON CONFLICT DO NOTHING;
INSERT INTO buyer SELECT buyer_id FROM stage.buyer ON CONFLICT DO NOTHING;
INSERT INTO product SELECT p_id, p_name, p_desc, price::numeric, qty::int, category_id::int FROM stage.product WHERE p_name IS NOT NULL ON CONFLICT DO NOTHING;
INSERT INTO review SELECT review_id::int, buyer_id, r_desc, title, rating::int, seller_product_flag FROM stage.review WHERE r_desc IS NOT NULL AND title IS NOT NULL ON CONFLICT DO NOTHING;

\echo '=== loaded counts'
SELECT 'customer' AS t, count(*) FROM customer
UNION ALL SELECT 'buyer', count(*) FROM buyer
UNION ALL SELECT 'category', count(*) FROM category
UNION ALL SELECT 'product', count(*) FROM product
UNION ALL SELECT 'review', count(*) FROM review;

\echo '=== identity after an explicit-id load: the id the next default insert gets'
SELECT nextval(pg_get_serial_sequence('review', 'review_id')) AS next_default_review_id,
       (SELECT max(review_id) FROM review) AS max_loaded_review_id;
