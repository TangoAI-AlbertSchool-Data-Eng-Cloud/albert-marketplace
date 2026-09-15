"""Storefront logic. Failures raise StorefrontError subclasses, which main.py turns into HTTP statuses."""

import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import bcrypt
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

import models
import schemas

CENT = Decimal("0.01")
ESTIMATED_DELIVERY_DAYS = 7


class StorefrontError(Exception):
    status = 400


class NotFound(StorefrontError):
    status = 404


class Conflict(StorefrontError):
    status = 409


def rounded(price):
    """Round as PostgreSQL rounds NUMERIC(10,2): half away from zero."""
    return price.quantize(CENT, rounding=ROUND_HALF_UP)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Customers


def create_customer(db: Session, customer: schemas.CustomerCreate):
    """A sign-up is a buyer: a CUSTOMER row with a bcrypt password, and its BUYER row."""
    if db.scalar(select(models.Customer).where(models.Customer.email == customer.email)):
        raise Conflict("Email already registered")
    if db.scalar(select(models.Customer).where(models.Customer.phone == customer.phone)):
        raise Conflict("Phone already registered")
    row = models.Customer(
        c_id=str(uuid.uuid4()),
        fname=customer.fname,
        lname=customer.lname,
        phone=customer.phone,
        email=customer.email,
        pwd=bcrypt.hashpw(customer.pwd.encode("utf-8"), bcrypt.gensalt()).decode("ascii"),
    )
    db.add(row)
    db.flush()
    db.add(models.Buyer(buyer_id=row.c_id))
    try:
        db.commit()
    except IntegrityError:  # a concurrent sign-up took the email or phone
        db.rollback()
        raise Conflict("Email or phone already registered")
    db.refresh(row)
    return row


# Products


def list_products(db: Session, skip: int, limit: int):
    return db.scalars(select(models.Product).order_by(models.Product.p_id).offset(skip).limit(limit)).all()


def get_product(db: Session, p_id: str):
    product = db.get(models.Product, p_id)
    if product is None:
        raise NotFound("Unknown product")
    return product


def get_product_images(db: Session, p_id: str):
    return [image.p_image for image in get_product(db, p_id).images]


# Cart


def get_or_create_cart(db: Session, buyer_id: str):
    if db.get(models.Buyer, buyer_id) is None:
        raise NotFound("Unknown buyer")
    cart = db.scalar(select(models.Cart).where(models.Cart.buyer_id == buyer_id).order_by(models.Cart.cart_id))
    if cart is None:
        cart = models.Cart(buyer_id=buyer_id, total_qty=0, total_price=0.0)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart


def update_totals(db: Session, cart):
    lines = [(item.qty, rounded(get_product(db, item.p_id).price)) for item in cart.items]
    cart.total_qty = sum(qty for qty, _ in lines)
    cart.total_price = float(sum((qty * price for qty, price in lines), Decimal("0.00")))


def add_to_cart(db: Session, buyer_id: str, p_id: str, qty: int):
    cart = get_or_create_cart(db, buyer_id)
    product = get_product(db, p_id)
    item = db.get(models.CartItem, (cart.cart_id, p_id))
    wanted = qty + (item.qty if item else 0)
    if wanted > product.qty:
        raise Conflict(f"Only {product.qty} in stock")
    if item:
        item.qty = wanted
    else:
        cart.items.append(models.CartItem(p_id=p_id, qty=qty))
    db.flush()
    update_totals(db, cart)
    db.commit()
    db.refresh(cart)
    return cart


def remove_from_cart(db: Session, buyer_id: str, p_id: str):
    cart = get_or_create_cart(db, buyer_id)
    item = db.get(models.CartItem, (cart.cart_id, p_id))
    if item is None:
        raise NotFound("Product not in cart")
    cart.items.remove(item)
    db.flush()
    update_totals(db, cart)
    db.commit()
    db.refresh(cart)
    return cart


# Checkout and orders


def checkout_cart(db: Session, buyer_id: str, payment_method: str):
    cart = get_or_create_cart(db, buyer_id)
    if not cart.items:
        raise StorefrontError("Cart is empty")

    # A card payment uses the buyer's default saved card
    card_id = None
    if payment_method == "Credit Card":
        card_id = db.scalar(
            select(models.CustomerPayment.payment_id).where(
                models.CustomerPayment.c_id == buyer_id, models.CustomerPayment.is_default == "1"
            )
        )
        if card_id is None:
            raise StorefrontError("No saved card: choose another payment method")

    today = utcnow().date()
    order = models.Orders(buyer_id=buyer_id, payment_id=card_id, order_date=today)
    db.add(order)
    try:
        db.flush()  # the stock trigger runs here, on the buyer's cart lines
    except DBAPIError as error:
        db.rollback()
        message = str(error.orig).splitlines()[0]
        if "Not enough stock" in message:
            raise Conflict(message)
        raise

    carriers = db.scalars(select(models.Carrier.carrier_id).order_by(models.Carrier.carrier_id)).all()
    amount = Decimal("0.00")
    for item in cart.items:
        price = rounded(get_product(db, item.p_id).price)
        order.items.append(models.OrderItem(p_id=item.p_id, qty=item.qty, price_at_purchase=price))
        order.shipments.append(
            models.Shipment(
                p_id=item.p_id,
                carrier_id=random.choice(carriers) if carriers else None,
                shipment_type="NP",
                status="processing",
                est_delivery_date=today + timedelta(days=ESTIMATED_DELIVERY_DAYS),
            )
        )
        amount += price * item.qty
    order.payment = models.Payment(
        payment_id=card_id, amount=amount, method=payment_method, status="completed", created_at=utcnow()
    )

    cart.items.clear()
    cart.total_qty = 0
    cart.total_price = 0.0
    db.commit()
    db.refresh(order)
    return order


def list_orders(db: Session, buyer_id: str):
    if db.get(models.Buyer, buyer_id) is None:
        raise NotFound("Unknown buyer")
    return db.scalars(
        select(models.Orders).where(models.Orders.buyer_id == buyer_id).order_by(models.Orders.order_id)
    ).all()


def list_shipments(db: Session, order_id: int):
    order = db.get(models.Orders, order_id)
    if order is None:
        raise NotFound("Unknown order")
    return order.shipments
