# Albert's Marketplace: support tickets card

120 messages that arrived in Albert's Marketplace's support inbox, each labelled
with the team that should handle it. They are the input of the LLM course's
classification, extraction and evaluation work, the way the dataset release is
the input of the data engineering course.

**The wording is machine-written and the labels are human-checked.** A
language model wrote every message from facts taken from the dataset release;
a person then checked every label. Read the ticket text as realistic, not as
real: no customer wrote it.

| | |
|---|---|
| Version | tickets-v1.0.0 |
| Built on | dataset release v1.0.0 |
| Messages | 120: 102 English, 10 French, 8 German |
| Sent | 2023-09-22 to 2026-09-15 |
| Written by | `claude-opus-5-5` (Anthropic), October 2026 |
| Labels checked by | the course author, every message |
| Licence | CC BY-SA 4.0 |
| Source repository | https://github.com/TangoAI-AlbertSchool-Data-Eng-Cloud/albert-marketplace |

## Files

| File | What it is |
|---|---|
| `tickets_v1.csv` | The 120 messages, one per row. |
| `tickets-cache-v1.tar.gz` | The model's saved responses for messages T001-T060, so they can be rebuilt without calling the model (see below). |
| `TICKETS_CARD.md` | This card. |
| `CHECKSUMS` | sha256 of each file above. |

## Columns

| Column | Meaning |
|---|---|
| `ticket_id` | `T001` to `T120` |
| `received_at` | the date the message was sent |
| `language` | `en`, `fr` or `de` |
| `subject`, `body` | the message |
| `order_id` | the order it concerns, a real `order_id` in the dataset release. Empty for 7 messages about a subscription rather than an order |
| `gold_label` | the team that should handle it (below) |
| `ambiguous_with` | a second label that also fits, when one does (72 messages). Empty otherwise |

## Labels

| Label | The message is about | Messages |
|---|---|---|
| `billing` | a charge, a payment, a way to pay | 16 |
| `delivery` | where a parcel is, or when it came | 11 |
| `returns_refunds` | sending something back, getting money back | 12 |
| `account` | signing in, the subscription, the account itself | 14 |
| `seller` | what a third-party seller did or sent | 15 |
| `product` | the product itself: quality, not as expected | 6 |
| `information` | a question about using a product or the service | 9 |
| `other` | anything else | 37 |

**The label set was revised by reading the messages.** It started with six
labels; `product` and `information` were added during the human check, because
messages that needed them were being forced into `other`. Treat the set as a
decision you may disagree with, not as a fact about the messages.

## How the messages were made

Every message is attached to real rows of the dataset release, so its order
number, dates, amount, products and carrier are true in the data.

- **T001-T060, from the data.**
  - Low-star reviews became the email their author sends to support about the
    same problem. The review at sorted position *i* is the purchase behind order
    *i* + 1 in the release, so the message carries that order's facts.
  - Order data supplied what reviews never mention: double charges (every order
    in the release was inserted twice, so a same-day twin is a real double
    charge), parcels still in transit at the end of the history or delivered
    late, and subscriptions that ended.
- **T061-T120, from briefs.** 60 messages written from briefs by the course
  staff, each on a real order the first sixty do not use. The briefs are
  teaching material and are not published, so this half cannot be rebuilt
  from this repository.
- **The model never saw a label.** It was asked for the wording only; each
  label comes from how the message was planned, and was then checked by hand.
- **A minority is in French and German**, and only for customers who live in
  France, Belgium or Germany.

## Rebuilding T001-T060

The model does not give the same answer twice, so the generator saves every
response under the SHA-256 of its request and reuses it. With the saved
responses, a rebuild makes no call to the model and costs nothing:

```bash
mkdir -p data/tickets && tar -xzf tickets-cache-v1.tar.gz -C data/tickets
docker compose --profile build run --rm tickets plan
docker compose --profile build run --rm tickets write
```

`write` writes `data/tickets/tickets_draft.csv`: the same sixty messages with
the labels as planned, before the human check. `tickets_v1.csv` holds the
checked labels.

## What is not in it

- **No real customer.** Names, where present, are the release's synthetic
  first names.
- **No real company other than the products' own brands.** Messages that
  mention a website use invented names on the reserved `.example` domain.
- **Nothing graded.** A label is the course author's judgement, recorded so
  that a model's answers can be compared with something.

## Citing it

> Albert's Marketplace support tickets, Albert School, 2026. CC BY-SA 4.0.
> Written by Claude (Anthropic) from the Albert's Marketplace dataset, itself
> derived from McAuley Lab's Amazon Reviews'23 (Hou et al. 2024,
> arXiv:2403.03952).
