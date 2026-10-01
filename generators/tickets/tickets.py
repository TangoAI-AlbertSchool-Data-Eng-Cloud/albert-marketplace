"""Support tickets for Albert's Marketplace, built on the released dataset.

The company has no ticket table, so tickets are written from real rows:
- review-derived: a low-star review becomes the email its author sends to
  support about the same problem (returns, sellers, delivery, product questions)
- order-derived: billing from the duplicated orders (every order was inserted
  twice, so a same-day twin is a real double charge), delivery from parcels
  still in transit or delivered late, account from subscriptions ending
- ambiguous: two real problems in one message, flagged for the human check

Two steps:

  plan   choose the source rows and the intended label for every ticket.
         Deterministic: a fixed seed and release give an identical plan.
  write  one model call per ticket writes only the wording. The model never
         sees or chooses a label. Every response is cached under the SHA-256
         of its request, so a re-run reproduces the draft byte for byte.

The labels in the draft are the plan's intent, not ground truth: a person
checks every one before the file is frozen (course decision: a set labelled
and scored by models is circular).

Run from the repo root:
  docker compose --profile build run --rm tickets plan
  docker compose --profile build run --rm tickets write
"""

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import random
import re
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

RELEASE = Path(os.environ.get("RELEASE_DIR", "/data/release"))
OUT = Path(os.environ.get("TICKETS_DIR", "/data/tickets"))
SEED = 7

# Batch 1: 60 tickets. Six labels, plus two-problem tickets for the human check.
MIX = {
    ("review", "returns_refunds"): 11,
    ("review", "seller"): 9,
    ("review", "delivery"): 4,
    ("review", "other"): 7,
    ("order", "delivery"): 7,
    ("order", "billing"): 9,
    ("order", "account"): 7,
    ("ambiguous", None): 6,
}
LANG_SHARE = {"fr": 5, "de": 4}  # of the 60; everything else is English
LANG_OF_COUNTRY = {"France": "fr", "Belgium": "fr", "Germany": "de"}

MODEL = "claude-opus-5-5"
EFFORT = "medium"
# claude-opus-5-5 list price, per million tokens: from the claude-api skill's
# model table (cached 2026-09-25). Re-check Anthropic's pricing page before
# quoting a figure anywhere.
PRICE_IN, PRICE_OUT = 4.00, 20.00

REVIEW_POOLS = {
    "returns_refunds": (2, r"\b(refund(ed)?|return(ed|ing)? (it|them|this)|money back|sen[dt] (it|them) back"
                           r"|arrived (broken|damaged|leaking|smashed)|leaked|spilled everywhere|crushed)\b"),
    "seller": (2, r"\b(wrong (item|product|colou?r|size|shade|one)|not as (described|pictured|advertised)"
                  r"|counterfeit|knock ?off|fake product|expired|already (used|opened)|used product"
                  r"|missing (parts|pieces|items))\b"),
    "delivery": (3, r"\b(never (arrived|received|came)|took (too long|forever|weeks|a month)"
                    r" to (arrive|ship|come|get here|be delivered)"
                    r"|shipping (took|was slow)|arrived late|late delivery|lost in the mail)\b"),
    "other": (3, r"\b(how (do|to|long|often|much)|ingredients?|allerg\w*|safe for|does (it|this) contain"
                 r"|is (it|this) (normal|supposed))\b[^.!]*\?"),
}
# Where the pattern must match. A delivery complaint buried at the end of a
# product review is not a delivery ticket, so it has to lead.
REVIEW_SCOPE = {"delivery": 200}

AMBIGUOUS = [
    ("delivery", "returns_refunds",
     "The parcel for this order arrived days after the promised date, and the customer no longer "
     "needs it: they want to send it back and be refunded."),
    ("billing", "account",
     "The customer sees two charges for this order, and also wants to cancel their yearly "
     "subscription because of it."),
    ("seller", "returns_refunds",
     "The product received is not the one ordered (another variant of it), and the customer "
     "wants their money back rather than an exchange."),
    ("other", "returns_refunds",
     "The customer asks whether this product is safe for sensitive skin, because it irritated "
     "theirs, and asks what they can do about it now that the bottle is open."),
    ("delivery", "seller",
     "The tracking says delivered, but the box that arrived contained only part of the order."),
    ("account", "billing",
     "The customer changed their card on their account, yet this order was charged to the old card."),
]

SYSTEM = """You write customer-support emails for a teaching dataset.

The company is Albert's Marketplace, a fictional European online marketplace for \
beauty products: third-party sellers list the products, and the marketplace runs \
payments and delivery. Each email is one message a customer sends to its support desk.

Rules:
- Write only as the customer, in the language you are given.
- Use only the facts you are given: order number, dates, amounts, product, carrier. \
Never invent another number, date or amount.
- Customers describe what happened to them. Never name a category, department or \
team, and never use support-desk vocabulary for the problem.
- Vary length and tone as real customers do: some write two lines, some ramble; \
some are polite, some are angry. An occasional typo is fine.
- Sign with the customer's first name, or not at all.

Return a subject line and a body."""

SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
    "required": ["subject", "body"],
    "additionalProperties": False,
}

LANG_NAME = {"en": "English", "fr": "French", "de": "German"}

# Batch "outliers": messages that land in the support inbox but fit no label
# cleanly. Ten briefs from Charles (2026-10-01), six tickets each, every one
# attached to a real order. The briefs are NOT in this public repository: which
# ticket is spam or abuse follows from them, and that is a course exercise's
# answer. Staff pass their folder as OUTLIER_BRIEFS_DIR (see compose.yaml).
BRIEFS = Path(os.environ.get("OUTLIER_BRIEFS", "/briefs/outlier_briefs.json"))


def load_outliers():
    """(kind, proposed label, second label, brief, six angles) per brief."""
    if not BRIEFS.exists():
        sys.exit(f"no outlier briefs at {BRIEFS}: they are staff-only, set OUTLIER_BRIEFS_DIR")
    data = json.loads(BRIEFS.read_text(encoding="utf-8"))
    return [(b["kind"], b["label"], b["second"], b["brief"], b["angles"]) for b in data["briefs"]]


OUTLIER_START = 61  # ticket ids continue after batch 1

SYSTEM_OUTLIERS = """You write messages for a teaching dataset of a support inbox.

The company is Albert's Marketplace, a fictional European online marketplace for \
beauty products: third-party sellers list the products, and the marketplace runs \
payments and delivery. Each message is one message that arrived in its support \
inbox. Some come from customers, some do not: the brief says who wrote it.

Rules:
- Write only as the author the brief describes, in the language you are given.
- Use only the facts you are given: order number, dates, amounts, product. Never \
invent another number, date or amount.
- Never name a category, department or team.
- Never name a real company, brand or website other than the products in the facts. \
Invented websites end in .example.
- Hostile messages stay free of slurs, threats, and remarks about anyone's origin, \
religion, gender, sexuality or disability.
- Sign with the first name given, or not at all, unless the brief says otherwise.

Return a subject line and a body."""
SYSTEMS = {"customer": SYSTEM, "outliers": SYSTEM_OUTLIERS}


# ------------------------------------------------------------------ release

def read_table(tar, name):
    member = tar.getmember(f"legacy_csv/{name}.csv")
    with tar.extractfile(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def load_release():
    path = RELEASE / "legacy_csv.tar.gz"
    manifest = json.loads((RELEASE / "MANIFEST.json").read_text(encoding="utf-8"))
    with tarfile.open(path, "r:gz") as tar:
        reviews = sorted(
            ({"review_id": int(r["review_id"]), "title": r["title"], "text": r["r_desc"],
              "rating": int(r["rating"]), "buyer_id": r["buyer_id"]}
             for r in read_table(tar, "review")),
            key=lambda r: r["review_id"])
        product_of_review = {int(r["review_id"]): r["p_id"] for r in read_table(tar, "product_reviews")}
        product_name = {r["p_id"]: r["p_name"] for r in read_table(tar, "product")}
        orders = {int(r["order_id"]): {"buyer_id": r["buyer_id"], "date": r["order_date"]}
                  for r in read_table(tar, "orders")}
        amount = {int(r["order_id"]): r["amount"] for r in read_table(tar, "payment")}
        carrier = {r["carrier_id"]: r["carrier_name"] for r in read_table(tar, "carrier")}
        shipments = defaultdict(list)
        for r in read_table(tar, "shipment"):
            shipments[int(r["order_id"])].append(r)
        first_name = {r["c_id"]: r["fname"] for r in read_table(tar, "customer")}
        address = {r["address_id"]: r["country"] for r in read_table(tar, "shipping_details")}
        country = {r["c_id"]: address.get(r["address_id"], "")
                   for r in read_table(tar, "customer_shipping") if r["is_default"] == "1"}
        subscriptions = [r for r in read_table(tar, "subscription")]
    return {
        "version": manifest["version"], "end": dt.date.fromisoformat(manifest["end_date"]),
        "reviews": reviews, "product_of_review": product_of_review, "product_name": product_name,
        "orders": orders, "amount": amount, "carrier": carrier, "shipments": shipments,
        "first_name": first_name, "country": country, "subscriptions": subscriptions,
    }


# --------------------------------------------------------------------- plan

def customer(rel, buyer_id):
    return {"first_name": rel["first_name"].get(buyer_id, ""), "country": rel["country"].get(buyer_id, "")}


def order_facts(rel, order_id):
    o = rel["orders"][order_id]
    ships = rel["shipments"].get(order_id, [])
    return {
        "order_id": order_id, "order_date": o["date"], "amount_eur": rel["amount"].get(order_id, ""),
        "products": sorted({rel["product_name"].get(s["p_id"], "") for s in ships}),
        "carrier": rel["carrier"].get(ships[0]["carrier_id"], "") if ships else "",
        "shipment_status": ships[0]["status"] if ships else "",
        "estimated_delivery": ships[0]["est_delivery_date"] if ships else "",
        "actual_delivery": ships[0]["actual_delivery_date"] if ships else "",
        **customer(rel, o["buyer_id"]),
    }


def received(rng, start, end, lo=1, hi=10):
    day = dt.date.fromisoformat(start) + dt.timedelta(days=rng.randint(lo, hi))
    return min(day, end).isoformat()


def plan(rel):
    rng = random.Random(SEED)
    n = len(rel["reviews"])
    used = set()
    tickets = []

    # Review-derived: the review at sorted position i is the purchase behind order i + 1.
    for (kind, label), count in MIX.items():
        if kind != "review":
            continue
        max_rating, pattern = REVIEW_POOLS[label]
        rx = re.compile(pattern, re.I)
        scope = REVIEW_SCOPE.get(label)
        pool = [i for i, r in enumerate(rel["reviews"])
                if r["rating"] <= max_rating and 80 <= len(r["text"].strip()) <= 900
                and rx.search(r["title"] + " " + (r["text"][:scope] if scope else r["text"]))]
        for i in rng.sample(pool, count):
            r = rel["reviews"][i]
            facts = order_facts(rel, i + 1)
            tickets.append({"label": label, "source": "review", "source_id": f"review:{r['review_id']}",
                            "received_at": received(rng, facts["order_date"], rel["end"]),
                            "facts": facts, "review": {"title": r["title"], "text": r["text"]}})
            used.add(i + 1)

    orders = rel["orders"]
    # Billing: a same-day twin is an exact double charge; a later twin, a second charge.
    twins = [i for i in range(1, n + 1) if i not in used and (n + i) in orders]
    same_day = [i for i in twins if orders[i]["date"] == orders[n + i]["date"]]
    later = [i for i in twins if orders[i]["date"] != orders[n + i]["date"]]
    billing = MIX[("order", "billing")]
    for i in rng.sample(same_day, billing - billing // 3) + rng.sample(later, billing // 3):
        facts = order_facts(rel, i)
        twin = order_facts(rel, n + i)
        situation = (f"The customer placed this order once, but was charged twice: a second order "
                     f"{twin['order_id']} for the same amount appears on {twin['order_date']}.")
        tickets.append({"label": "billing", "source": "order", "source_id": f"orders:{i}+{n + i}",
                        "received_at": received(rng, twin["order_date"], rel["end"], 0, 5),
                        "facts": facts, "situation": situation})
        used.add(i)

    # Delivery: parcels still moving at the end of the history, and parcels delivered late.
    delivery = MIX[("order", "delivery")]
    moving = sorted(o for o, ships in rel["shipments"].items()
                    if ships[0]["status"] in ("in_transit", "processing") and o not in used)
    late = sorted(o for o, ships in rel["shipments"].items()
                  if ships[0]["actual_delivery_date"] and ships[0]["est_delivery_date"]
                  and ships[0]["actual_delivery_date"] > ships[0]["est_delivery_date"]
                  and o not in used)
    for o in rng.sample(moving, delivery - delivery // 3):
        facts = order_facts(rel, o)
        tickets.append({"label": "delivery", "source": "order", "source_id": f"shipment:{o}",
                        "received_at": rel["end"].isoformat(), "facts": facts,
                        "situation": "The parcel has not arrived yet and the customer wants to know where it is."})
        used.add(o)
    for o in rng.sample(late, delivery // 3):
        facts = order_facts(rel, o)
        tickets.append({"label": "delivery", "source": "order", "source_id": f"shipment:{o}",
                        "received_at": facts["actual_delivery"], "facts": facts,
                        "situation": "The parcel arrived after the estimated delivery date and the customer is annoyed."})
        used.add(o)

    # Account: yearly subscriptions that ended in the last 90 days of the history.
    # (Every subscription in v1.0.0 ends by 2026-07-27, before the history does.)
    window = (rel["end"] - dt.timedelta(days=90)).isoformat(), rel["end"].isoformat()
    ended = sorted((s for s in rel["subscriptions"] if window[0] <= s["end_date"] <= window[1]),
                   key=lambda s: int(s["subscription_id"]))
    situations = [
        "The customer's yearly subscription has ended and they do not understand why it did not renew by itself.",
        "The customer wants to restart their yearly subscription, which has ended.",
        "The customer cannot sign in to their account any more and wants to know what happened to their subscription.",
    ]
    for k, s in enumerate(rng.sample(ended, MIX[("order", "account")])):
        facts = {"subscription_start": s["start_date"], "subscription_end": s["end_date"], **customer(rel, s["c_id"])}
        tickets.append({"label": "account", "source": "subscription", "source_id": f"subscription:{s['subscription_id']}",
                        "received_at": received(rng, s["end_date"], rel["end"], 1, 40),
                        "facts": facts, "situation": situations[k % len(situations)]})

    # Ambiguous: two real problems on one real order; the human check decides.
    pool = [i for i in range(1, n + 1) if i not in used]
    for (a, b, situation), i in zip(AMBIGUOUS, rng.sample(pool, len(AMBIGUOUS))):
        facts = order_facts(rel, i)
        tickets.append({"label": a, "ambiguous_with": b, "source": "ambiguous", "source_id": f"order:{i}",
                        "received_at": received(rng, facts["order_date"], rel["end"]),
                        "facts": facts, "situation": situation})

    # Languages: a minority in French and German, only for customers living there.
    for lang, count in LANG_SHARE.items():
        eligible = [t for t in tickets if "language" not in t
                    and LANG_OF_COUNTRY.get(t["facts"].get("country")) == lang]
        for t in rng.sample(eligible, min(count, len(eligible))):
            t["language"] = lang
    order = list(range(len(tickets)))
    rng.shuffle(order)  # so the file does not list tickets grouped by label
    out = []
    for k, idx in enumerate(order, 1):
        t = tickets[idx]
        t.setdefault("language", "en")
        t.setdefault("ambiguous_with", "")
        out.append({"ticket_id": f"T{k:03d}", **t})
    return out


def used_orders(tickets):
    """Every order a batch already speaks about, twins included."""
    used = set()
    for t in tickets:
        if t["facts"].get("order_id"):
            used.add(int(t["facts"]["order_id"]))
        kind, ref = t["source_id"].split(":", 1)
        if kind in ("orders", "shipment", "order"):  # review: and subscription: ids are not orders
            used.update(int(x) for x in re.findall(r"\d+", ref))
    return used


def plan_outliers(rel, taken):
    """Six tickets per outlier brief, each on a real order no other batch uses."""
    rng = random.Random(f"{SEED}:outliers")  # its own stream: batch 1 stays byte-identical
    n = len(rel["reviews"])
    pool = [i for i in range(1, n + 1) if i not in taken and rel["shipments"].get(i)]
    outliers = load_outliers()
    orders = rng.sample(pool, 6 * len(outliers))
    tickets = []
    for (kind, label, second, brief, angles), chunk in zip(outliers, zip(*[iter(orders)] * 6)):
        for angle, o in zip(angles, chunk):
            facts = order_facts(rel, o)
            tickets.append({"label": label, "ambiguous_with": second, "source": "outlier",
                            "source_id": f"outlier:{kind}/order:{o}", "system": "outliers",
                            "received_at": received(rng, facts["order_date"], rel["end"]),
                            "facts": facts, "situation": f"{brief}\nMake this one different: {angle}."})
    for lang, count in LANG_SHARE.items():
        eligible = [t for t in tickets if "language" not in t
                    and LANG_OF_COUNTRY.get(t["facts"].get("country")) == lang]
        for t in rng.sample(eligible, min(count, len(eligible))):
            t["language"] = lang
    rng.shuffle(tickets)
    out = []
    for k, t in enumerate(tickets, OUTLIER_START):
        t.setdefault("language", "en")
        out.append({"ticket_id": f"T{k:03d}", **t})
    return out


# -------------------------------------------------------------------- write

def prompt(t):
    f = t["facts"]
    outlier = t.get("system") == "outliers"
    lines = [f"Language: {LANG_NAME[t['language']]}", f"Date the email is sent: {t['received_at']}"]
    if f.get("first_name"):
        lines.append(f"{'Account holder' if outlier else 'Customer'}'s first name: {f['first_name']}")
    if f.get("country"):
        lines.append(f"Customer lives in: {f['country']}")
    for key, label in [("order_id", "Order number"), ("order_date", "Order date"),
                       ("amount_eur", "Amount charged (EUR)"), ("carrier", "Carrier"),
                       ("estimated_delivery", "Estimated delivery date"),
                       ("actual_delivery", "Actual delivery date"),
                       ("subscription_start", "Subscription started"),
                       ("subscription_end", "Subscription ends")]:
        if f.get(key):
            lines.append(f"{label}: {f[key]}")
    if f.get("products"):
        lines.append("Products in the order: " + "; ".join(p for p in f["products"] if p))
    if t.get("review"):
        lines += ["", "This customer also wrote the product review below. Turn it into the email "
                  "they send to support about the same problem, keeping their words and tone where "
                  "you can. Drop what only makes sense in a public review: star ratings, advice to "
                  "other buyers.", "", f"Review title: {t['review']['title']}", f"Review: {t['review']['text']}"]
    else:
        lines += ["", f"{'Brief' if outlier else 'What happened'}: {t['situation']}"]
    return "\n".join(lines)


def cache_key(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def call(client, request):
    """One ticket. Returns (subject, body, usage dict, served-by model), or None if declined."""
    response = client.beta.messages.create(
        betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request)
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        print(f"  declined ({category}), skipped; nothing cached", flush=True)
        return None
    if response.stop_reason == "max_tokens":
        raise SystemExit("hit max_tokens: raise it in the request")
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return data["subject"].strip(), data["body"].strip(), usage, response.model


def write(tickets, draft):
    cache = OUT / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    client = None
    rows, spent, fresh, declined = [], {"input_tokens": 0, "output_tokens": 0}, 0, []
    for t in tickets:
        request = {"model": MODEL, "max_tokens": 4000, "system": SYSTEMS[t.get("system", "customer")],
                   "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
                   "messages": [{"role": "user", "content": prompt(t)}]}
        key = cache_key(request)
        path = cache / f"{key}.json"
        if path.exists():
            hit = json.loads(path.read_text(encoding="utf-8"))
        else:
            if client is None:
                import anthropic  # container only: its compiled dependencies are blocked on the Windows host
                client = anthropic.Anthropic()
            result = call(client, request)
            if result is None:
                declined.append(t["ticket_id"])
                continue
            subject, body, usage, served = result
            hit = {"subject": subject, "body": body, "usage": usage, "served_by": served}
            path.write_text(json.dumps(hit, ensure_ascii=False, indent=1), encoding="utf-8")
            for k in spent:
                spent[k] += usage[k]
            fresh += 1
            print(f"  {t['ticket_id']} written", flush=True)
        f = t["facts"]
        rows.append({
            "ticket_id": t["ticket_id"], "received_at": t["received_at"], "language": t["language"],
            "subject": hit["subject"], "body": hit["body"], "order_id": f.get("order_id", ""),
            "gold_label": t["label"], "ambiguous_with": t["ambiguous_with"], "checked": "", "note": "",
            "source": t["source"], "source_id": t["source_id"], "model": hit["served_by"], "cache_key": key,
        })
    with draft.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    cost = spent["input_tokens"] / 1e6 * PRICE_IN + spent["output_tokens"] / 1e6 * PRICE_OUT
    print(f"{len(rows)} tickets -> {draft} ({fresh} new calls, {len(rows) - fresh} from cache)")
    print(f"new calls: {spent['input_tokens']} input + {spent['output_tokens']} output tokens, "
          f"about ${cost:.4f} at ${PRICE_IN}/${PRICE_OUT} per MTok")
    if declined:
        print(f"declined, not in the draft: {', '.join(declined)}")
    print("sha256", sha256(draft))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("step", choices=["plan", "write"])
    parser.add_argument("--batch", choices=["main", "outliers"], default="main")
    parser.add_argument("--limit", type=int, help="write: only the first N tickets (to try a change cheaply)")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "" if args.batch == "main" else f"_{args.batch}"
    plan_path = OUT / f"plan{suffix}.jsonl"
    if args.step == "plan":
        rel = load_release()
        if args.batch == "main":
            tickets = plan(rel)
        else:
            main_plan = OUT / "plan.jsonl"
            if not main_plan.exists():
                sys.exit("plan the main batch first: the outliers avoid its orders")
            taken = used_orders([json.loads(x) for x in main_plan.read_text(encoding="utf-8").splitlines()])
            tickets = plan_outliers(rel, taken)
        with plan_path.open("w", encoding="utf-8", newline="\n") as fh:
            for t in tickets:
                fh.write(json.dumps(t, ensure_ascii=False, sort_keys=True) + "\n")
        counts = defaultdict(int)
        for t in tickets:
            counts[(t["label"], t["language"])] += 1
        print(f"{len(tickets)} tickets planned from release {rel['version']} -> {plan_path}")
        for (label, lang), c in sorted(counts.items()):
            print(f"  {label:16} {lang}  {c}")
        print("sha256", sha256(plan_path))
    else:
        if not plan_path.exists():
            sys.exit(f"no plan at {plan_path}: run the plan step first")
        tickets = [json.loads(line) for line in plan_path.read_text(encoding="utf-8").splitlines()]
        write(tickets[:args.limit] if args.limit else tickets, OUT / f"tickets{suffix}_draft.csv")


if __name__ == "__main__":
    main()
