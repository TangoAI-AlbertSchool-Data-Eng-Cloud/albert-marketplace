-- Revenue last year under three definitions, for the duplicate-orders lecture.
--
-- Run it against a database holding the dataset:
--   docker exec -i albert-marketplace-db-1 psql -U postgres -d marketplace -X -f - < docs/lecture-figures.sql
-- or, from inside the repository with the stack up:
--   docker compose exec -T db psql -U postgres -d marketplace -X < docs/lecture-figures.sql
--
-- Everything is derived from the data, so the figures follow a regenerated
-- dataset (another --seed, --end-date or --scale). Two windows are reported,
-- because "last year" is ambiguous: the twelve months to the last order, and
-- the last complete calendar year.
--
-- The three definitions:
--   1. the export as it is:      every order, duplicates included
--   2. exact duplicates removed: orders identical on buyer, discount, card,
--      date and amount collapse to one. This only catches a twin that landed
--      on the same day as its original
--   3. twin orders removed:      only the real orders. Each review's order has
--      ORDER_ID = i and its duplicate ORDER_ID = i + (number of reviews)

\pset border 2
\set ON_ERROR_STOP on

-- The layout the third definition relies on: every pair shares a buyer, and the
-- twin is 0 to 4 days after its original. pairs_with_a_different_buyer must be 0.
WITH n AS (SELECT count(*)::int AS n FROM review)
SELECT count(*) FILTER (WHERE a.buyer_id IS DISTINCT FROM b.buyer_id) AS pairs_with_a_different_buyer,
       count(*)                                                       AS pairs,
       min(b.order_date - a.order_date)                               AS smallest_gap_days,
       max(b.order_date - a.order_date)                               AS largest_gap_days
FROM n
CROSS JOIN orders a
JOIN orders b ON b.order_id = a.order_id + n.n
WHERE a.order_id <= n.n;

CREATE TEMP VIEW windows AS
WITH last_day AS (SELECT max(order_date) AS day FROM orders),
     year AS (
         SELECT CASE
                    WHEN day = make_date(extract(year FROM day)::int, 12, 31) THEN extract(year FROM day)::int
                    ELSE extract(year FROM day)::int - 1
                END AS y
         FROM last_day
     )
SELECT 'A: 12 months to ' || day AS label, day - 364 AS lo, day AS hi FROM last_day
UNION ALL
SELECT 'B: calendar year ' || y, make_date(y, 1, 1), make_date(y, 12, 31) FROM year;

CREATE TEMP VIEW scoped AS
WITH n AS (SELECT count(*)::int AS n FROM review)
SELECT w.label,
       o.order_id,
       o.buyer_id,
       o.discount_id,
       o.payment_id,
       o.order_date,
       p.amount,
       o.order_id <= n.n AS is_original,
       -- the two orders of a pair share this
       CASE WHEN o.order_id <= n.n THEN o.order_id ELSE o.order_id - n.n END AS pair_id
FROM n
CROSS JOIN windows w
JOIN orders o ON o.order_date BETWEEN w.lo AND w.hi
JOIN payment p USING (order_id);

-- The three figures
WITH as_is AS (SELECT label, count(*) AS orders, sum(amount) AS revenue FROM scoped GROUP BY label),
     deduped AS (
         SELECT label, count(*) AS orders, sum(amount) AS revenue
         FROM (SELECT DISTINCT ON (label, buyer_id, discount_id, payment_id, order_date, amount)
                      label, order_id, amount
               FROM scoped
               ORDER BY label, buyer_id, discount_id, payment_id, order_date, amount, order_id) d
         GROUP BY label
     ),
     twinless AS (SELECT label, count(*) AS orders, sum(amount) AS revenue FROM scoped WHERE is_original GROUP BY label)
SELECT a.label                                             AS window,
       a.orders                                            AS orders_as_is,
       to_char(a.revenue, 'FM999G999G999D00')              AS revenue_as_is,
       d.orders                                            AS orders_exact_dupes_removed,
       to_char(d.revenue, 'FM999G999G999D00')              AS revenue_exact_dupes_removed,
       t.orders                                            AS orders_twins_removed,
       to_char(t.revenue, 'FM999G999G999D00')              AS revenue_twins_removed,
       round(a.revenue / t.revenue, 2)                     AS as_is_over_true
FROM as_is a JOIN deduped d USING (label) JOIN twinless t USING (label)
ORDER BY a.label;

-- What the exact-duplicate rule removes, and whether it was right to
WITH ranked AS (
    SELECT label, pair_id,
           row_number() OVER (PARTITION BY label, buyer_id, discount_id, payment_id, order_date, amount
                              ORDER BY order_id) AS rn,
           first_value(pair_id) OVER (PARTITION BY label, buyer_id, discount_id, payment_id, order_date, amount
                                      ORDER BY order_id) AS kept_pair
    FROM scoped
)
SELECT label                                                       AS window,
       count(*) FILTER (WHERE rn > 1)                              AS rows_removed,
       count(*) FILTER (WHERE rn > 1 AND pair_id = kept_pair)      AS were_its_own_twin,
       count(*) FILTER (WHERE rn > 1 AND pair_id <> kept_pair)     AS looked_alike_but_were_not
FROM ranked GROUP BY label ORDER BY label;

-- What it misses: the duplicates still inside the deduplicated figure
WITH deduped AS (
         SELECT label, count(*) AS orders, sum(amount) AS revenue
         FROM (SELECT DISTINCT ON (label, buyer_id, discount_id, payment_id, order_date, amount)
                      label, order_id, amount
               FROM scoped
               ORDER BY label, buyer_id, discount_id, payment_id, order_date, amount, order_id) d
         GROUP BY label
     ),
     twinless AS (SELECT label, count(*) AS orders, sum(amount) AS revenue FROM scoped WHERE is_original GROUP BY label)
SELECT d.label                                                  AS window,
       d.orders - t.orders                                      AS duplicates_left_in,
       to_char(d.revenue - t.revenue, 'FM999G999G999D00')       AS phantom_revenue_left_in,
       round(100 * (1 - (d.revenue - t.revenue) / (SELECT sum(amount) FROM scoped s WHERE s.label = d.label AND NOT s.is_original)), 1)
                                                                AS percent_of_phantom_revenue_caught
FROM deduped d JOIN twinless t USING (label)
ORDER BY d.label;
