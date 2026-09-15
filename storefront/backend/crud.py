import uuid
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import text
from sqlalchemy.orm import Session
from passlib.hash import bcrypt
import models, schemas
from datetime import datetime, date, timedelta

# Customer

def get_customer_by_email(db: Session, email: str):
    return db.query(models.Customer).filter(models.Customer.email == email).first()


def create_customer(db: Session, customer: schemas.CustomerCreate):
    hashed = bcrypt.hash(customer.pwd)
    db_obj = models.Customer(
        c_id=str(uuid.uuid4()),
        fname=customer.fname,
        lname=customer.lname,
        phone=customer.phone,
        email=customer.email,
        pwd=hashed,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

# Product

def list_products(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Product).offset(skip).limit(limit).all()

# Cart

def get_or_create_cart(db: Session, buyer_id: str):
    cart = db.query(models.Cart).filter(models.Cart.buyer_id == buyer_id).first()
    if not cart:
        cart = models.Cart(buyer_id=buyer_id)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart


def add_to_cart(db: Session, buyer_id: str, p_id: str, qty: int = 1):
    cart = get_or_create_cart(db, buyer_id)
    item = (
        db.query(models.CartItem)
        .filter(models.CartItem.cart_id == cart.cart_id, models.CartItem.p_id == p_id)
        .first()
    )
    if item:
        item.qty += qty
    else:
        item = models.CartItem(cart_id=cart.cart_id, p_id=p_id, qty=qty)
        db.add(item)
    cart.total_qty += qty
    # Recompute price
    prod = db.query(models.Product).get(p_id)
    cart.total_price += float(prod.price) * qty
    db.commit()
    db.refresh(cart)
    return cart

# Existing customer, product, cart logic omitted for brevity...

def checkout_cart(db: Session, buyer_id: str, payment_method: str):
    cart = db.query(models.Cart).filter(models.Cart.buyer_id == buyer_id).first()
    if not cart or cart.total_qty == 0:
        raise ValueError("Cart is empty or does not exist")
    # A card payment uses the buyer's default saved card
    card_id = None
    if payment_method == "Credit Card":
        card_id = db.execute(
            text("SELECT payment_id FROM customer_payment WHERE c_id = :c_id AND is_default = '1'"),
            {"c_id": buyer_id},
        ).scalar()
    # Create order
    order = models.Orders(
        buyer_id=buyer_id,
        payment_id=card_id,
    )
    db.add(order)
    db.flush()  # populate order_id
    # Create order items
    amount = Decimal("0.00")
    for item in cart.items:
        prod = db.query(models.Product).get(item.p_id)
        # Round as PostgreSQL rounds NUMERIC(10,2): half away from zero
        price = prod.price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        order_item = models.OrderItem(
            order_id=order.order_id,
            p_id=item.p_id,
            qty=item.qty,
            price_at_purchase=price,
        )
        db.add(order_item)
        amount += price * item.qty
        # Create shipment per item
        shipment = models.Shipment(
            order_id=order.order_id,
            p_id=item.p_id,
            carrier_id=None,
            shipment_type='NP',
            status='processing',
            est_delivery_date=(date.today() + timedelta(days=7)),
        )
        db.add(shipment)
    # Create payment record
    payment = models.Payment(
        order_id=order.order_id,
        payment_id=card_id,
        amount=amount,
        method=payment_method,
        status="completed",
    )
    db.add(payment)
    # Clear cart
    db.query(models.CartItem).filter(models.CartItem.cart_id == cart.cart_id).delete()
    cart.total_qty = 0
    cart.total_price = 0.0
    db.commit()
    db.refresh(order)
    return order


def get_order(db: Session, order_id: str):
    return db.query(models.Orders).filter(models.Orders.order_id == order_id).first()

def list_orders(db: Session, buyer_id: str):
    return db.query(models.Orders).filter(models.Orders.buyer_id == buyer_id).all()

def list_shipments(db: Session, order_id: int):
    return db.query(models.Shipment).filter(models.Shipment.order_id == order_id).all()

def get_product_images(db: Session, p_id: str):
    """
    Return all ProductImage rows for the given product ID.
    """
    return db.query(models.ProductImage).filter(models.ProductImage.p_id == p_id).all()
