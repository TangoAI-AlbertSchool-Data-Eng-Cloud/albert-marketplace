-- Step 2 checks, on a freshly migrated scratch database. Never on real data.
\set ON_ERROR_STOP 0
\pset pager off

\echo '=== migrations applied'
SELECT version FROM schema_migrations ORDER BY version;

\echo '=== seed: 2 buyers, 3 products, 2 carts, 3 deals'
INSERT INTO customer (c_id, fname, lname, phone, email, pwd) VALUES
  ('B1', 'Test', 'One', '0600000001', 'b1@example.test', 'plain1'),
  ('B2', 'Test', 'Two', '0600000002', 'b2@example.test', 'plain2');
INSERT INTO buyer VALUES ('B1'), ('B2');
INSERT INTO product (p_id, p_name, p_desc, price, qty) VALUES
  ('P000000001', 'Lipstick', '{}', 10.00, 5),
  ('P000000002', 'Serum',    '{}', 20.00, 1),
  ('P000000003', 'Mask',     '{}', 0.00042863802736903267, 3);
INSERT INTO cart (buyer_id) VALUES ('B1'), ('B2');
INSERT INTO cart_items (cart_id, p_id, qty) VALUES
  (1, 'P000000001', 2), (1, 'P000000002', 1),
  (2, 'P000000001', 1);
INSERT INTO daily_deals (p_id, deal_date, discount) VALUES
  ('P000000001', DATE '2026-10-01', 10),
  ('P000000001', DATE '2026-10-02', 10),
  ('P000000002', DATE '2026-10-02', 50);

\echo '=== D1 fixed APPLY_DAILY_DEALS, cart 1 on 2026-10-02: expect 88 (step 1: ambiguous, then 87)'
CALL apply_daily_deals(1, DATE '2026-10-02', 0, 100);
\echo '=== D2 an item without a deal, 2026-10-01: expect 98 (step 1: NULL)'
CALL apply_daily_deals(1, DATE '2026-10-01', 0, 100);
\echo '=== D3 minimum price 95: expect 95'
CALL apply_daily_deals(1, DATE '2026-10-02', 95, 100);
\echo '=== D4 a cart with no items: expect 100'
CALL apply_daily_deals(99, DATE '2026-10-02', 0, 100);

\echo '=== T1 stock trigger unchanged: an order for B1 takes P1 5->3 and P2 1->0'
INSERT INTO orders (buyer_id, order_date) VALUES ('B1', DATE '2026-10-01');
SELECT p_id, qty FROM product ORDER BY p_id;

\echo '=== O1 order_items accepts lines; 0.00042863802736903267 is stored as 0.00'
INSERT INTO order_items (order_id, p_id, qty, price_at_purchase) VALUES
  (1, 'P000000001', 2, 10.00),
  (1, 'P000000003', 1, 0.00042863802736903267);
SELECT * FROM order_items ORDER BY p_id;
\echo '=== O2 rejects qty 0'
INSERT INTO order_items VALUES (1, 'P000000002', 0, 20.00);
\echo '=== O3 rejects a negative price'
INSERT INTO order_items VALUES (1, 'P000000002', 1, -1);
\echo '=== O4 rejects a second line for the same product'
INSERT INTO order_items VALUES (1, 'P000000001', 1, 10.00);
\echo '=== O5 rejects an unknown order'
INSERT INTO order_items VALUES (999, 'P000000001', 1, 10.00);
\echo '=== O6 a product with order lines cannot be deleted'
DELETE FROM product WHERE p_id = 'P000000001';
\echo '=== O7 deleting an order deletes its lines: expect 0'
DELETE FROM orders WHERE order_id = 1;
SELECT count(*) AS order_items_left FROM order_items;
