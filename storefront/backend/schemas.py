from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, date

class CustomerBase(BaseModel):
    fname: str
    lname: str
    phone: str
    email: EmailStr

class CustomerCreate(CustomerBase):
    pwd: str

class Customer(CustomerBase):
    c_id: str
    class Config:
        orm_mode = True

class Product(BaseModel):
    p_id: str
    p_name: str
    p_desc: str
    price: float
    qty: int
    class Config:
        orm_mode = True

class ProductImage(BaseModel):
    p_id: str
    p_image: str

    class Config:
        orm_mode = True

class CartItem(BaseModel):
    p_id: str
    qty: int
    class Config:
        orm_mode = True

class Cart(BaseModel):
    cart_id: int
    buyer_id: str
    total_qty: int
    total_price: float
    items: List[CartItem] = []
    class Config:
        orm_mode = True

class OrderItem(BaseModel):
    p_id: str
    qty: int
    price_at_purchase: float
    class Config:
        orm_mode = True

class Payment(BaseModel):
    transaction_id: int
    payment_id: Optional[int]
    amount: float
    method: str
    status: str
    created_at: datetime
    class Config:
        orm_mode = True

class Shipment(BaseModel):
    shipping_id: int
    order_id: int
    p_id: str
    carrier_id: Optional[int]
    shipment_type: str
    status: str
    est_delivery_date: Optional[date]
    actual_delivery_date: Optional[date]
    class Config:
        orm_mode = True

class Orders(BaseModel):
    order_id: int
    buyer_id: str
    order_date: datetime
    items: List[OrderItem]
    payment: Payment
    shipment: Shipment
    class Config:
        orm_mode = True
