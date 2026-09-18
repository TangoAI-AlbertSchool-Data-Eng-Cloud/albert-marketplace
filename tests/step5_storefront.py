"""Step 5: the storefront's checkout writes PAYMENT rows on the generated database."""
import sys
import warnings

sys.path.insert(0, "/app")
warnings.simplefilter("ignore")

from sqlalchemy import text  # noqa: E402

import crud  # noqa: E402
import models  # noqa: E402
import schemas  # noqa: E402
from database import SessionLocal, engine  # noqa: E402

models.Base.metadata.create_all(bind=engine)
with engine.begin() as conn:
    conn.execute(text(
        "INSERT INTO customer (c_id, fname, lname, phone, email, pwd) "
        "VALUES ('SF1', 'Store', 'Front', '015199999999', 'sf1@example.com', 'plain')"))
    conn.execute(text("INSERT INTO buyer VALUES ('SF1')"))
    card = conn.execute(text(
        "INSERT INTO payment_details (card_no, cvv, expiry_date, billing_address) "
        "VALUES (4111111111111111, 123, DATE '2029-01-31', 'Teststrasse 1Berlin10115') RETURNING payment_id")).scalar()
    conn.execute(text("INSERT INTO customer_payment (payment_id, c_id, is_default) VALUES (:p, 'SF1', '1')"), {"p": card})
    # 12.985 rounds to 12.99 half away from zero (PostgreSQL), 12.98 half to even
    conn.execute(text(
        "INSERT INTO product (p_id, p_name, p_desc, price, qty) VALUES "
        "('SFTEST0001', 'Cream', '{}', 12.985, 10), ('SFTEST0002', 'Mask', '{}', 0.00042863802736903267, 10)"))
print("saved card:", card)

db = SessionLocal()
crud.add_to_cart(db, "SF1", "SFTEST0001", 2)
crud.add_to_cart(db, "SF1", "SFTEST0002", 1)
by_card = crud.checkout_cart(db, "SF1", "Credit Card", crud.utcnow())
print("card order:", schemas.Orders.model_validate(by_card, from_attributes=True).model_dump_json())
crud.add_to_cart(db, "SF1", "SFTEST0001", 1)
by_paypal = crud.checkout_cart(db, "SF1", "PayPal", crud.utcnow())
print("PayPal order:", schemas.Orders.model_validate(by_paypal, from_attributes=True).model_dump_json())

ids = {"a": by_card.order_id, "b": by_paypal.order_id}
with engine.connect() as conn:
    for sql in (
        "SELECT transaction_id, order_id, payment_id, amount, method, status FROM payment WHERE order_id IN (:a, :b) ORDER BY order_id",
        "SELECT order_id, payment_id FROM orders WHERE order_id IN (:a, :b) ORDER BY order_id",
        "SELECT order_id, p_id, qty, price_at_purchase FROM order_items WHERE order_id IN (:a, :b) ORDER BY 1, 2",
    ):
        for row in conn.execute(text(sql), ids):
            print("  ", tuple(row))
