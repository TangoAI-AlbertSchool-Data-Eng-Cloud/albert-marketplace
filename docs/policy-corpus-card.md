# Albert's Marketplace: policy corpus card

Albert's Marketplace's help centre, its seller policy, four product pages and
an extract of its product catalogue, as PDFs. They are the documents the LLM
course's retrieval work answers from: questions about returns, delivery,
payments, accounts and selling, which no model has read before.

**The company and its policies are fictional.** The policy pages were written
for the course and checked by the course author; their values (a 21-day return
window, a €3.95 return cost, free delivery from €35, a 12% commission) were
chosen to differ from common practice, so that an answer guessed from other
shops is visibly wrong. They agree with the dataset release wherever the two
meet: card payments only, the four carriers, the six countries, a delivery
estimate seven days after the order.

| | |
|---|---|
| Version | policy-corpus-v1.0.0 |
| Built on | dataset release v1.0.0 |
| Documents | 6 PDFs, 31 pages, about 16,500 tokens |
| Policy text written by | an AI model (Claude, Anthropic) for the course, October 2026, checked by the course author |
| Catalogue | 150 products drawn from the dataset release with a fixed seed |
| Licence | CC BY-SA 4.0 |
| Source repository | https://github.com/TangoAI-AlbertSchool-Data-Eng-Cloud/albert-marketplace |

## Files

| File | What it is |
|---|---|
| `01-returns-and-refunds.pdf` | When an item can be returned, what it costs, when a refund arrives; late deliveries |
| `02-delivery.pdf` | Countries, carriers, delivery times and costs, late, lost and damaged parcels |
| `03-payments-and-account.pdf` | Payment by card, discount codes, double charges, the account, closing it and the data |
| `04-seller-policy.pdf` | Fees, payouts, shipping, answering customers, product pages, prohibited products, reviews |
| `05-product-pages.pdf` | Four product pages as their sellers wrote them |
| `06-product-catalogue.pdf` | 150 products: name, id, category, price, attributes as the sellers entered them |
| `POLICY_CORPUS_CARD.md` | This card |
| `CHECKSUMS` | sha256 of each file above |

## What is not in it, on purpose

A customer-service phone number, gift wrapping and loyalty points: questions a
customer may ask, which the help centre does not answer. A system built on
these documents should say it does not know.

## How it was made

`generators/policy_corpus/build.py` in the source repository: the five pages
under `sources/` are Markdown, the catalogue is drawn from the dataset
release's `product` and `category` tables, and both are laid out as A4 PDFs
with `fpdf2`. The command is at the top of the script; the build is
deterministic, so the checksums do not change from one build to the next.

The four product pages' sellers are named for the pages; the dataset release
records no seller names, so the names contradict nothing in it.

## Licence and attribution

CC BY-SA 4.0, like the dataset it is built on. The product names and
attributes in the catalogue come from McAuley Lab's Amazon Reviews'23, through
the dataset release; see the repository's README for the full attribution.
