"""Step 2: the storefront's models and checkout against the migrated schema.

Imports storefront/backend as the API does (DATABASE_URL from the environment),
runs create_all() as main.py does at startup, then a checkout.
"""
import sys
import warnings

sys.path.insert(0, "/app")
warnings.simplefilter("ignore")

from sqlalchemy import inspect, text  # noqa: E402

import crud  # noqa: E402
import models  # noqa: E402
import schemas  # noqa: E402
from database import SessionLocal, engine  # noqa: E402

models.Base.metadata.create_all(bind=engine)
cols = {c["name"]: str(c["type"]) for c in inspect(engine).get_columns("order_items")}
print("order_items columns after create_all:", cols)

with engine.begin() as conn:
    conn.execute(text(
        "INSERT INTO customer (c_id, fname, lname, phone, email, pwd) "
        "VALUES ('SF1', 'Store', 'Front', '0633333333', 'sf1@example.com', 'plain')"))
    conn.execute(text("INSERT INTO buyer VALUES ('SF1')"))
    card = conn.execute(text(
        "INSERT INTO payment_details (card_no, cvv, expiry_date, billing_address) "
        "VALUES (4111111111111111, 123, DATE '2029-01-31', 'Teststrasse 1Berlin10115') RETURNING payment_id")).scalar()
    conn.execute(text("INSERT INTO customer_payment (payment_id, c_id, is_default) VALUES (:p, 'SF1', '1')"), {"p": card})
    conn.execute(text(
        "INSERT INTO product (p_id, p_name, p_desc, price, qty) VALUES "
        "('SFTEST0001', 'Cream', '{}', 12.99, 10), "
        "('SFTEST0002', 'Mask', '{}', 0.00042863802736903267, 10)"))

db = SessionLocal()
crud.add_to_cart(db, "SF1", "SFTEST0001", 2)
crud.add_to_cart(db, "SF1", "SFTEST0002", 1)
order = crud.checkout_cart(db, "SF1", "Credit Card", crud.utcnow())
print("order", order.order_id, "lines:",
      [(i.p_id, i.qty, i.price_at_purchase, type(i.price_at_purchase).__name__) for i in order.items])
print("API response:", schemas.Orders.model_validate(order, from_attributes=True).model_dump_json())

with engine.connect() as conn:
    for row in conn.execute(text("SELECT order_id, p_id, qty, price_at_purchase FROM order_items ORDER BY p_id")):
        print("db order_items:", tuple(row))
    for row in conn.execute(text("SELECT p_id, qty FROM product WHERE p_id LIKE 'SFTEST%' ORDER BY p_id")):
        print("db stock:", tuple(row))
