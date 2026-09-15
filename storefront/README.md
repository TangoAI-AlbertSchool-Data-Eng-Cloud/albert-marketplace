# Storefront

Albert's Marketplace's shop: a FastAPI backend (`backend/`) and a Streamlit UI
(`streamlit_app.py`), on the company's PostgreSQL database.

The database schema belongs to `db/migrations`. The API maps onto it with
SQLAlchemy and never creates tables.

## Run it

From the repository root:

```
docker compose up --build
```

This starts PostgreSQL, applies the migrations, then starts the API and the UI:

| What | Address | Port variable |
|---|---|---|
| API documentation (try every endpoint) | http://localhost:8100/docs | `API_PORT` |
| UI | http://localhost:8510 | `UI_PORT` |

In the UI, enter a buyer ID from the `buyer` table, for example from
`docker compose exec db psql -U postgres -d marketplace -c "SELECT buyer_id FROM buyer LIMIT 5"`.

## API

| Method and path | What it does |
|---|---|
| `GET /health` | 200 when the API can reach the database |
| `POST /customers/` | Sign up: creates the customer and its buyer, password hashed with bcrypt |
| `GET /products/?skip=&limit=` | Products, by product ID, at most 100 at a time |
| `GET /products/{p_id}/images` | Image URLs of a product |
| `GET /cart/{buyer_id}` | The buyer's cart, created when missing |
| `POST /cart/{buyer_id}?p_id=&qty=` | Adds units to the cart, within the product's stock |
| `DELETE /cart/{buyer_id}/{p_id}` | Removes a product from the cart |
| `POST /checkout/{buyer_id}?payment_method=` | Places the order: order lines, one shipment per line, one payment; the stock trigger decrements stock |
| `GET /orders/{buyer_id}` | The buyer's orders, with lines, payment and shipments |
| `GET /shipments/{order_id}` | An order's shipments |

`payment_method` is `Credit Card` (the buyer's default saved card), `PayPal` or
`Bank Transfer`. Errors come back as 400, 404, 409 or 422 with a `detail`
message.

## Dependencies

`requirements.in` (UI) and `backend/requirements.in` (API) list the direct
dependencies; each `requirements.txt` pins every package. The command to
regenerate a pinned file is at the top of its `.in` file.
