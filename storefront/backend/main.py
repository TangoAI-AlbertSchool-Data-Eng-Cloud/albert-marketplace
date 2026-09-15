"""Albert's Marketplace storefront API.

The schema belongs to db/migrations: this app maps onto it and never creates tables.
"""

from typing import List

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

import crud
import schemas
from database import SessionLocal

app = FastAPI(title="Albert's Marketplace storefront API")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.exception_handler(crud.StorefrontError)
def storefront_error(request: Request, error: crud.StorefrontError):
    return JSONResponse(status_code=error.status, content={"detail": str(error)})


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/customers/", response_model=schemas.Customer, status_code=201)
def create_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    return crud.create_customer(db, customer)


@app.get("/products/", response_model=List[schemas.Product])
def read_products(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), db: Session = Depends(get_db)):
    return crud.list_products(db, skip=skip, limit=limit)


@app.get("/products/{p_id}/images", response_model=List[str], summary="List image URLs for a product")
def read_product_images(p_id: str, db: Session = Depends(get_db)):
    return crud.get_product_images(db, p_id)


@app.get("/cart/{buyer_id}", response_model=schemas.Cart)
def read_cart(buyer_id: str, db: Session = Depends(get_db)):
    return crud.get_or_create_cart(db, buyer_id)


@app.post("/cart/{buyer_id}", response_model=schemas.Cart)
def add_cart_item(buyer_id: str, p_id: str, qty: int = Query(1, ge=1, le=1000), db: Session = Depends(get_db)):
    return crud.add_to_cart(db, buyer_id, p_id, qty)


@app.delete("/cart/{buyer_id}/{p_id}", response_model=schemas.Cart)
def remove_cart_item(buyer_id: str, p_id: str, db: Session = Depends(get_db)):
    return crud.remove_from_cart(db, buyer_id, p_id)


@app.post("/checkout/{buyer_id}", response_model=schemas.Orders, status_code=201)
def checkout(buyer_id: str, payment_method: schemas.PaymentMethod, db: Session = Depends(get_db)):
    return crud.checkout_cart(db, buyer_id, payment_method)


@app.get("/orders/{buyer_id}", response_model=List[schemas.Orders])
def get_orders(buyer_id: str, db: Session = Depends(get_db)):
    return crud.list_orders(db, buyer_id)


@app.get("/shipments/{order_id}", response_model=List[schemas.Shipment])
def get_shipments(order_id: int, db: Session = Depends(get_db)):
    return crud.list_shipments(db, order_id)
