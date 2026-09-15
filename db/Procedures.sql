CREATE OR REPLACE PROCEDURE APPLY_DAILY_DEALS(
    IN cart_id INTEGER,
    IN o_date DATE,
    IN minimum_price NUMERIC,
    INOUT total NUMERIC
)
LANGUAGE plpgsql
AS $$
DECLARE
    this_product RECORD;
    discount_percent NUMERIC := 0;
    item_price NUMERIC;
    item_discount NUMERIC;
BEGIN
    FOR this_product IN
        SELECT * FROM cart_items WHERE cart_id = cart_id
    LOOP
        BEGIN
            SELECT discount INTO discount_percent
            FROM daily_deals
            WHERE p_id = this_product.p_id
              AND deal_date = o_date;
        EXCEPTION
            WHEN no_data_found THEN
                discount_percent := 0;
        END;

        SELECT price INTO item_price
        FROM product
        WHERE p_id = this_product.p_id;

        FOR i IN 1..this_product.qty LOOP
            item_discount := (discount_percent / 100.0) * item_price;
            total := total - item_discount;
        END LOOP;

        IF total < minimum_price THEN
            total := minimum_price;
        END IF;
    END LOOP;
END;
$$;
