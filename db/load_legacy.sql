-- Load the legacy CSV extract (the 25 files of Amazon_tx_database_files) into
-- the migrated schema, keeping its defects (docs/build-spec.md §3, §5.8, §10.3).
--
-- Run it with:  docker compose --profile build run --rm load-legacy
-- The CSV folder is LEGACY_CSV_DIR (default ./data/legacy_csv), mounted at /csv.
--
-- Idempotent: every run empties the legacy tables and the tables the history
-- generator fills (order_items, payment), then reloads them in one transaction,
-- so a failed run leaves the database as it was.

\set ON_ERROR_STOP on
\encoding UTF8

BEGIN;

TRUNCATE payment, order_items, returns, shipment, orders, discount, cart_items, cart,
    carrier, daily_deals, product_images, product_reviews, seller_products,
    wishlist_item, product, category, review_images, seller_reviews, review,
    seller, buyer, subscription, customer_payment, payment_details,
    customer_shipping, shipping_details, customer
    RESTART IDENTITY;

-- Each CSV is staged as text, then cast into its table. Every CSV starts with
-- pandas' index column (header ''), staged as unnamed_0 and not loaded: the
-- legacy tables have no such column. Tables load in foreign-key order.

-- CUSTOMER
CREATE TEMP TABLE csv_customer (unnamed_0 text, c_id text, fname text, lname text, phone text, email text, pwd text) ON COMMIT DROP;
\copy csv_customer FROM '/csv/customer.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO customer (c_id, fname, lname, phone, email, pwd)
SELECT c_id, fname, lname, phone, email, pwd
FROM csv_customer;

-- SHIPPING_DETAILS
CREATE TEMP TABLE csv_shipping_details (unnamed_0 text, address_id text, street_address text, city text, state text, zip text, country text, phone text) ON COMMIT DROP;
\copy csv_shipping_details FROM '/csv/shipping_details.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO shipping_details (address_id, street_address, city, state, zip, country, phone)
SELECT address_id::integer, street_address, city, state, zip, country, phone
FROM csv_shipping_details;

-- CUSTOMER_SHIPPING
CREATE TEMP TABLE csv_customer_shipping (unnamed_0 text, address_id text, c_id text, is_default text) ON COMMIT DROP;
\copy csv_customer_shipping FROM '/csv/customer_shipping.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO customer_shipping (address_id, c_id, is_default)
SELECT address_id::integer, c_id, is_default
FROM csv_customer_shipping;

-- PAYMENT_DETAILS
CREATE TEMP TABLE csv_payment_details (unnamed_0 text, payment_id text, card_no text, cvv text, expiry_date text, billing_address text) ON COMMIT DROP;
\copy csv_payment_details FROM '/csv/payment_details.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO payment_details (payment_id, card_no, cvv, expiry_date, billing_address)
SELECT payment_id::integer, card_no::bigint, cvv::smallint, expiry_date::date, billing_address
FROM csv_payment_details;

-- CUSTOMER_PAYMENT
CREATE TEMP TABLE csv_customer_payment (unnamed_0 text, payment_id text, c_id text, is_default text) ON COMMIT DROP;
\copy csv_customer_payment FROM '/csv/customer_payment.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO customer_payment (payment_id, c_id, is_default)
SELECT payment_id::integer, c_id, is_default
FROM csv_customer_payment;

-- SUBSCRIPTION
CREATE TEMP TABLE csv_subscription (unnamed_0 text, subscription_id text, c_id text, start_date text, end_date text) ON COMMIT DROP;
\copy csv_subscription FROM '/csv/subscription.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO subscription (subscription_id, c_id, start_date, end_date)
SELECT subscription_id::integer, c_id, start_date::date, end_date::date
FROM csv_subscription;

-- BUYER
CREATE TEMP TABLE csv_buyer (unnamed_0 text, buyer_id text) ON COMMIT DROP;
\copy csv_buyer FROM '/csv/buyer.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO buyer (buyer_id)
SELECT buyer_id
FROM csv_buyer;

-- SELLER: the CSV has no SELLER_NAME column, so it stays NULL
CREATE TEMP TABLE csv_seller (unnamed_0 text, seller_id text, seller_type text) ON COMMIT DROP;
\copy csv_seller FROM '/csv/seller.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO seller (seller_id, seller_type)
SELECT seller_id, seller_type
FROM csv_seller;

-- REVIEW: 14 empty texts become empty strings (R_DESC is NOT NULL);
-- NA-like strings such as 'None' stay as text
CREATE TEMP TABLE csv_review (unnamed_0 text, review_id text, buyer_id text, r_desc text, title text, rating text, seller_product_flag text) ON COMMIT DROP;
\copy csv_review FROM '/csv/review.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO review (review_id, buyer_id, r_desc, title, rating, seller_product_flag)
SELECT review_id::integer, buyer_id, COALESCE(r_desc, ''), title, rating::integer, seller_product_flag
FROM csv_review;

-- SELLER_REVIEWS
CREATE TEMP TABLE csv_seller_reviews (unnamed_0 text, seller_id text, review_id text) ON COMMIT DROP;
\copy csv_seller_reviews FROM '/csv/seller_reviews.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO seller_reviews (seller_id, review_id)
SELECT seller_id, review_id::integer
FROM csv_seller_reviews;

-- REVIEW_IMAGES
CREATE TEMP TABLE csv_review_images (unnamed_0 text, review_id text, review_img text) ON COMMIT DROP;
\copy csv_review_images FROM '/csv/review_images.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO review_images (review_id, review_img)
SELECT review_id::integer, review_img
FROM csv_review_images;

-- CATEGORY
CREATE TEMP TABLE csv_category (unnamed_0 text, category_id text, name text, c_desc text) ON COMMIT DROP;
\copy csv_category FROM '/csv/category.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO category (category_id, name, c_desc)
SELECT category_id::integer, name, c_desc
FROM csv_category;

-- PRODUCT: 6 empty names become empty strings (P_NAME is NOT NULL);
-- prices keep every digit of the CSV
CREATE TEMP TABLE csv_product (unnamed_0 text, p_id text, p_name text, p_desc text, price text, qty text, category_id text) ON COMMIT DROP;
\copy csv_product FROM '/csv/product.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO product (p_id, p_name, p_desc, price, qty, category_id)
SELECT p_id, COALESCE(p_name, ''), p_desc, price::numeric, qty::integer, category_id::integer
FROM csv_product;

-- WISHLIST_ITEM
CREATE TEMP TABLE csv_wishlist_item (unnamed_0 text, product_id text, buyer_id text) ON COMMIT DROP;
\copy csv_wishlist_item FROM '/csv/wishlist_item.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO wishlist_item (product_id, buyer_id)
SELECT product_id, buyer_id
FROM csv_wishlist_item;

-- SELLER_PRODUCTS
CREATE TEMP TABLE csv_seller_products (unnamed_0 text, seller_id text, p_id text) ON COMMIT DROP;
\copy csv_seller_products FROM '/csv/seller_products.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO seller_products (seller_id, p_id)
SELECT seller_id, p_id
FROM csv_seller_products;

-- PRODUCT_REVIEWS
CREATE TEMP TABLE csv_product_reviews (unnamed_0 text, p_id text, review_id text) ON COMMIT DROP;
\copy csv_product_reviews FROM '/csv/product_reviews.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO product_reviews (p_id, review_id)
SELECT p_id, review_id::integer
FROM csv_product_reviews;

-- PRODUCT_IMAGES
CREATE TEMP TABLE csv_product_images (unnamed_0 text, p_id text, p_image text) ON COMMIT DROP;
\copy csv_product_images FROM '/csv/product_images.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO product_images (p_id, p_image)
SELECT p_id, p_image
FROM csv_product_images;

-- DAILY_DEALS
CREATE TEMP TABLE csv_daily_deals (unnamed_0 text, p_id text, deal_date text, discount text) ON COMMIT DROP;
\copy csv_daily_deals FROM '/csv/daily_deals.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO daily_deals (p_id, deal_date, discount)
SELECT p_id, deal_date::date, discount::numeric
FROM csv_daily_deals;

-- CARRIER
CREATE TEMP TABLE csv_carrier (unnamed_0 text, carrier_id text, carrier_name text) ON COMMIT DROP;
\copy csv_carrier FROM '/csv/carrier.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO carrier (carrier_id, carrier_name)
SELECT carrier_id::integer, carrier_name
FROM csv_carrier;

-- CART
CREATE TEMP TABLE csv_cart (unnamed_0 text, cart_id text, buyer_id text, total_qty text, total_price text) ON COMMIT DROP;
\copy csv_cart FROM '/csv/cart.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO cart (cart_id, buyer_id, total_qty, total_price)
SELECT cart_id::integer, buyer_id, total_qty::integer, total_price::double precision
FROM csv_cart;

-- CART_ITEMS
CREATE TEMP TABLE csv_cart_items (unnamed_0 text, cart_id text, p_id text, qty text) ON COMMIT DROP;
\copy csv_cart_items FROM '/csv/cart_items.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO cart_items (cart_id, p_id, qty)
SELECT cart_id::integer, p_id, qty::integer
FROM csv_cart_items;

-- DISCOUNT
CREATE TEMP TABLE csv_discount (unnamed_0 text, discount_id text, discount_name text, d_desc text, discount_amt text) ON COMMIT DROP;
\copy csv_discount FROM '/csv/discount.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO discount (discount_id, discount_name, d_desc, discount_amt)
SELECT discount_id::integer, discount_name, d_desc, discount_amt::numeric
FROM csv_discount;

-- ORDERS: the legacy orders never went through a cart, and the stock trigger
-- would run a cart lookup for each of them, so it is off during this insert
CREATE TEMP TABLE csv_orders (unnamed_0 text, order_id text, buyer_id text, discount_id text, payment_id text, order_date text) ON COMMIT DROP;
\copy csv_orders FROM '/csv/orders.csv' WITH (FORMAT csv, HEADER true)
ALTER TABLE orders DISABLE TRIGGER trg_update_inventory;
INSERT INTO orders (order_id, buyer_id, discount_id, payment_id, order_date)
SELECT order_id::integer, buyer_id, discount_id::integer, payment_id::integer, order_date::date
FROM csv_orders;
ALTER TABLE orders ENABLE TRIGGER trg_update_inventory;

-- SHIPMENT
CREATE TEMP TABLE csv_shipment (unnamed_0 text, shipping_id text, order_id text, p_id text, carrier_id text, shipment_type text, status text, est_delivery_date text, actual_delivery_date text) ON COMMIT DROP;
\copy csv_shipment FROM '/csv/shipment.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO shipment (shipping_id, order_id, p_id, carrier_id, shipment_type, status, est_delivery_date, actual_delivery_date)
SELECT shipping_id::integer, order_id::integer, p_id, carrier_id::integer, shipment_type, status, est_delivery_date::date, actual_delivery_date::date
FROM csv_shipment;

-- RETURNS
CREATE TEMP TABLE csv_returns (unnamed_0 text, return_id text, buyer_id text, p_id text, order_id text) ON COMMIT DROP;
\copy csv_returns FROM '/csv/returns.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO returns (return_id, buyer_id, p_id, order_id)
SELECT return_id::integer, buyer_id, p_id, order_id::integer
FROM csv_returns;

-- Identity columns do not follow explicit ids: move every identity sequence to
-- its table's highest id, so the next default id does not collide (§10.1)
DO $$
DECLARE
    col RECORD;
    top BIGINT;
BEGIN
    FOR col IN
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND is_identity = 'YES'
    LOOP
        EXECUTE format('SELECT max(%I) FROM %I', col.column_name, col.table_name) INTO top;
        IF top IS NULL THEN
            PERFORM setval(pg_get_serial_sequence(col.table_name, col.column_name), 1, false);
        ELSE
            PERFORM setval(pg_get_serial_sequence(col.table_name, col.column_name), top);
        END IF;
    END LOOP;
END;
$$;

COMMIT;

ANALYZE;

-- Exact row counts
SELECT table_name,
       (xpath('/row/n/text()',
              query_to_xml(format('SELECT count(*) AS n FROM %I', table_name), false, true, '')))[1]::text::bigint AS rows
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
  AND table_name <> 'schema_migrations'
ORDER BY table_name;
