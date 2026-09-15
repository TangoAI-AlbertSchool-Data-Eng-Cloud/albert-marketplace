"""SQLAlchemy mappings onto the migrated schema (db/migrations), which owns the tables.

Only the tables the storefront reads or writes are mapped. Foreign keys point
only at mapped tables.
"""

from sqlalchemy import CHAR, Column, Date, DateTime, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from database import Base


class Customer(Base):
    __tablename__ = "customer"
    c_id = Column(String(40), primary_key=True)
    fname = Column(String(200), nullable=False)
    lname = Column(String(30), nullable=False)
    phone = Column(String(15), unique=True, nullable=False)
    email = Column(String(250), unique=True, nullable=False)
    pwd = Column(String(60), nullable=False)


class Buyer(Base):
    __tablename__ = "buyer"
    buyer_id = Column(String(40), ForeignKey("customer.c_id", ondelete="CASCADE"), primary_key=True)


class CustomerPayment(Base):
    # payment_id is the saved card in PAYMENT_DETAILS, which the storefront does not map
    __tablename__ = "customer_payment"
    payment_id = Column(Integer, primary_key=True)
    c_id = Column(String(40), ForeignKey("customer.c_id", ondelete="CASCADE"), primary_key=True)
    is_default = Column(CHAR(1), default="0")


class Category(Base):
    __tablename__ = "category"
    category_id = Column(Integer, primary_key=True)
    name = Column(String(30), nullable=False)
    c_desc = Column(String(20), nullable=False)


class Product(Base):
    __tablename__ = "product"
    p_id = Column(String(10), primary_key=True)
    p_name = Column(String(1000), nullable=False)
    p_desc = Column(String(5000), nullable=False)
    price = Column(Numeric, nullable=False)
    qty = Column(Integer, nullable=False, default=0)
    category_id = Column(Integer, ForeignKey("category.category_id", ondelete="SET NULL"))
    images = relationship("ProductImage", back_populates="product", order_by="ProductImage.p_image")


class ProductImage(Base):
    __tablename__ = "product_images"
    p_id = Column(String(10), ForeignKey("product.p_id", ondelete="CASCADE"), primary_key=True)
    p_image = Column(String(100), primary_key=True)
    product = relationship("Product", back_populates="images")


class Cart(Base):
    __tablename__ = "cart"
    cart_id = Column(Integer, primary_key=True)
    buyer_id = Column(String(40), ForeignKey("buyer.buyer_id", ondelete="CASCADE"))
    total_qty = Column(Integer, nullable=False, default=0)
    total_price = Column(Float, nullable=False, default=0.0)  # FLOAT in the legacy schema
    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan", order_by="CartItem.p_id")


class CartItem(Base):
    __tablename__ = "cart_items"
    cart_id = Column(Integer, ForeignKey("cart.cart_id", ondelete="CASCADE"), primary_key=True)
    p_id = Column(String(10), ForeignKey("product.p_id", ondelete="CASCADE"), primary_key=True)
    qty = Column(Integer, nullable=False, default=1)
    cart = relationship("Cart", back_populates="items")


class Orders(Base):
    __tablename__ = "orders"
    order_id = Column(Integer, primary_key=True)
    buyer_id = Column(String(40), ForeignKey("buyer.buyer_id", ondelete="SET NULL"))
    discount_id = Column(Integer)
    payment_id = Column(Integer)  # the saved card used, as in the legacy orders
    order_date = Column(Date, nullable=False)
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.p_id")
    payment = relationship("Payment", back_populates="order", uselist=False)
    shipments = relationship("Shipment", back_populates="order", order_by="Shipment.shipping_id")


class OrderItem(Base):
    __tablename__ = "order_items"
    order_id = Column(Integer, ForeignKey("orders.order_id", ondelete="CASCADE"), primary_key=True)
    p_id = Column(String(10), ForeignKey("product.p_id"), primary_key=True)
    qty = Column(Integer, nullable=False)
    price_at_purchase = Column(Numeric(10, 2), nullable=False)
    order = relationship("Orders", back_populates="items")


class Payment(Base):
    # One transaction per order; payment_id is the saved card used, empty for other methods
    __tablename__ = "payment"
    transaction_id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    payment_id = Column(Integer)
    amount = Column(Numeric(10, 2), nullable=False)
    method = Column(String(20), nullable=False)
    status = Column(String(10), nullable=False)
    created_at = Column(DateTime, nullable=False)
    order = relationship("Orders", back_populates="payment")


class Carrier(Base):
    __tablename__ = "carrier"
    carrier_id = Column(Integer, primary_key=True)
    carrier_name = Column(String(30), nullable=False)


class Shipment(Base):
    __tablename__ = "shipment"
    shipping_id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.order_id", ondelete="SET NULL"))
    p_id = Column(String(10), ForeignKey("product.p_id", ondelete="SET NULL"))
    carrier_id = Column(Integer, ForeignKey("carrier.carrier_id", ondelete="SET NULL"))
    shipment_type = Column(CHAR(2), default="NP")
    status = Column(String(10), nullable=False)
    est_delivery_date = Column(Date)
    actual_delivery_date = Column(Date)
    order = relationship("Orders", back_populates="shipments")
