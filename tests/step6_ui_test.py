"""Step 6: the Streamlit UI flow, headless, with Streamlit's AppTest. Runs inside the UI container."""
import sys

from streamlit.testing.v1 import AppTest

buyer = sys.argv[1]
at = AppTest.from_file("/app/streamlit_app.py", default_timeout=60)


def step(label):
    errors = [e.value for e in at.error]
    exceptions = [str(e.value) for e in at.exception]
    print(f"{'ok  ' if not exceptions else 'FAIL'} {label}" + (f" | errors shown: {errors}" if errors else "") + (f" | exceptions: {exceptions}" if exceptions else ""))
    if exceptions:
        sys.exit(1)


at.run()
step("page renders: " + str([t.value for t in at.title]))
at.text_input[0].input(buyer).run()
products = at.selectbox[0]
step(f"buyer entered: {len(products.options)} products listed, first '{products.options[0]}'")

for i in range(len(products.options)):
    if any(b.label == "Add to cart" for b in at.button):
        break
    at.selectbox[0].set_value(i + 1).run()
[b for b in at.button if b.label == "Add to cart"][0].click().run()
step(f"add to cart: notices {[s.value for s in at.success]}")
cart_lines = [m.value for m in at.markdown if m.value.startswith("**Items:**") or m.value.startswith("**Total:**")]
print(f"{'ok  ' if len(cart_lines) == 2 and '€' in cart_lines[1] else 'FAIL'} cart shows items and a euro total: {cart_lines}")

[s for s in at.selectbox if s.label == "Payment method"][0].set_value("PayPal").run()
[b for b in at.button if b.label == "Buy now"][0].click().run()
placed = [s.value for s in at.success if "placed" in s.value]
step(f"buy now: notices {placed}")
shipments = [m.value for m in at.markdown if "estimated delivery" in m.value]
print(f"{'ok  ' if placed and shipments else 'FAIL'} order placed and its shipments shown: {shipments}")
print(f"{'ok  ' if any(i.value == 'Your cart is empty.' for i in at.info) else 'FAIL'} cart is empty afterwards")
sys.exit(0 if placed and shipments else 1)
