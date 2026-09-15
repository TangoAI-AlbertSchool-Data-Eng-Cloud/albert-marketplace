from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PaymentMethod = Literal["Credit Card", "PayPal", "Bank Transfer"]


class CustomerCreate(BaseModel):
    # Limits follow the CUSTOMER columns, so bad input gets a 422, not a database error
    fname: str = Field(min_length=1, max_length=200)
    lname: str = Field(min_length=1, max_length=30)
    phone: str = Field(pattern=r"^[0-9]{6,15}$")
    email: EmailStr
    pwd: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def email_fits(cls, value):
        if len(value) > 250:
            raise ValueError("email must be at most 250 characters")
        return value

    @field_validator("pwd")
    @classmethod
    def password_fits_bcrypt(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes")
        return value


class Customer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    c_id: str
    fname: str
    lname: str
    phone: str
    email: str


class Product(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    p_id: str
    p_name: str
    p_desc: str
    price: float
    qty: int


class CartItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    p_id: str
    qty: int


class Cart(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    cart_id: int
    buyer_id: str
    total_qty: int
    total_price: float
    items: List[CartItem] = []


class OrderItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    p_id: str
    qty: int
    price_at_purchase: float


class Payment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    transaction_id: int
    payment_id: Optional[int]
    amount: float
    method: str
    status: str
    created_at: datetime


class Shipment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    shipping_id: int
    order_id: int
    p_id: str
    carrier_id: Optional[int]
    shipment_type: Optional[str]
    status: str
    est_delivery_date: Optional[date]
    actual_delivery_date: Optional[date]


class Orders(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    order_id: int
    buyer_id: Optional[str]
    payment_id: Optional[int]
    order_date: date
    items: List[OrderItem]
    payment: Optional[Payment]
    shipments: List[Shipment]
