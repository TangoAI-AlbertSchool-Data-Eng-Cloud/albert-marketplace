CREATE OR REPLACE FUNCTION update_inventory()
RETURNS TRIGGER AS $$
DECLARE
    this_item RECORD;
    old_qty INTEGER;
    new_qty INTEGER;
BEGIN
    FOR this_item IN
        SELECT ci.p_id, ci.qty
        FROM cart_items ci
        JOIN cart c ON ci.cart_id = c.cart_id
        WHERE c.buyer_id = NEW.buyer_id
    LOOP
        SELECT qty INTO old_qty
        FROM product
        WHERE p_id = this_item.p_id;

        new_qty := old_qty - this_item.qty;

        IF new_qty < 0 THEN
            RAISE EXCEPTION 'Not enough stock for product %', this_item.p_id;
        END IF;

        UPDATE product
        SET qty = new_qty
        WHERE p_id = this_item.p_id;
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_inventory
BEFORE INSERT ON orders
FOR EACH ROW
EXECUTE FUNCTION update_inventory();
