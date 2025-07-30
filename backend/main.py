import uvicorn
from fastapi import FastAPI, Depends, HTTPException, APIRouter
from typing import List
from sqlalchemy.orm import Session
import models, schemas, crud
from database import engine, SessionLocal

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="Mock E‑commerce API")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/customers/", response_model=schemas.Customer)
def create_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    if crud.get_customer_by_email(db, email=customer.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    return crud.create_customer(db, customer)

@app.get("/products/", response_model=List[schemas.Product])
def read_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_products(db, skip=skip, limit=limit)

@app.get("/cart/{buyer_id}", response_model=schemas.Cart)
def read_cart(buyer_id: str, db: Session = Depends(get_db)):
    cart = crud.get_or_create_cart(db, buyer_id)
    return cart

@app.post("/cart/{buyer_id}", response_model=schemas.Cart)
def add_cart_item(buyer_id: str, p_id: str, qty: int = 1, db: Session = Depends(get_db)):
    return crud.add_to_cart(db, buyer_id, p_id, qty)

@app.post("/checkout/{buyer_id}", response_model=schemas.Orders)
def checkout(buyer_id: str, payment_method: str, db: Session = Depends(get_db)):
    try:
        return crud.checkout_cart(db, buyer_id, payment_method)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/orders/{buyer_id}", response_model=List[schemas.Orders])
def get_orders(buyer_id: str, db: Session = Depends(get_db)):
    return crud.list_orders(db, buyer_id)

@app.get("/shipments/{order_id}", response_model=List[schemas.Shipment])
def get_shipments(order_id: int, db: Session = Depends(get_db)):
    shipments = crud.list_shipments(db, order_id)
    if not shipments:
        raise HTTPException(status_code=404, detail="No shipments found for this order")
    return shipments

@app.get(
    "/products/{p_id}/images",
    response_model=List[str],
    summary="List image URLs for a product",
)
def read_product_images(p_id: str, db: Session = Depends(get_db)):
    """
    Fetch all image URLs for product `p_id` from the product_images table.
    """
    imgs = crud.get_product_images(db, p_id)
    if not imgs:
        # 404 if you want, or just return []
        raise HTTPException(status_code=404, detail="No images found for this product")
    return [img.p_image for img in imgs]



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
