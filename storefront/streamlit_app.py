import os

import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://storefront-api:8000")
PAYMENT_METHODS = ["Credit Card", "PayPal", "Bank Transfer"]


def api(method, path, **params):
    """Call the storefront API; show its error and return None when the call fails."""
    try:
        response = requests.request(method, f"{API_URL}{path}", params=params, timeout=10)
    except requests.RequestException:
        st.error("The storefront API is not reachable.")
        return None
    if response.ok:
        return response.json()
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    if isinstance(detail, list):  # validation errors
        detail = "; ".join(error.get("msg", str(error)) for error in detail)
    st.error(detail)
    return None


def euros(value):
    return f"€{value:,.2f}"


st.title("Albert's Marketplace")

if notice := st.session_state.pop("notice", None):
    st.success(notice)

buyer_id = st.text_input("Enter your buyer ID:")

if buyer_id:
    cart = api("GET", f"/cart/{buyer_id}")
    if cart is not None:
        products = api("GET", "/products/") or []
        if products:
            labels = [f"{(p['p_name'] or p['p_id'])[:80]} — {euros(p['price'])}" for p in products]
            index = st.selectbox("Select a product", range(len(products)), format_func=lambda i: labels[i])
            selected = products[index]

            image_urls = api("GET", f"/products/{selected['p_id']}/images") or []
            if image_urls:
                st.image(image_urls, width=200)

            if selected["qty"] > 0:
                qty = st.number_input("Quantity", min_value=1, max_value=selected["qty"], value=1)
                if st.button("Add to cart"):
                    if api("POST", f"/cart/{buyer_id}", p_id=selected["p_id"], qty=int(qty)) is not None:
                        st.session_state["notice"] = f"Added {int(qty)} × {labels[index]}"
                        st.rerun()
            else:
                st.warning("Out of stock.")

        st.header("Your cart")
        if cart["items"]:
            for item in cart["items"]:
                line, remove = st.columns([4, 1])
                line.write(f"{item['p_id']}: {item['qty']}")
                if remove.button("Remove", key=f"remove-{item['p_id']}"):
                    if api("DELETE", f"/cart/{buyer_id}/{item['p_id']}") is not None:
                        st.rerun()
            st.write(f"**Items:** {cart['total_qty']}")
            st.write(f"**Total:** {euros(cart['total_price'])}")

            st.subheader("Checkout")
            payment_method = st.selectbox("Payment method", PAYMENT_METHODS)
            if st.button("Buy now"):
                order = api("POST", f"/checkout/{buyer_id}", payment_method=payment_method)
                if order is not None:
                    st.session_state["last_order"] = order
                    st.session_state["notice"] = f"Order {order['order_id']} placed: {euros(order['payment']['amount'])}"
                    st.rerun()
        else:
            st.info("Your cart is empty.")

        order = st.session_state.get("last_order")
        if order and order["buyer_id"] == buyer_id:
            st.subheader(f"Shipments for order {order['order_id']}")
            for shipment in order["shipments"]:
                st.write(
                    f"{shipment['p_id']}: {shipment['status']}, carrier {shipment['carrier_id']}, "
                    f"estimated delivery {shipment['est_delivery_date']}"
                )
