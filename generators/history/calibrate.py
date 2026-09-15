"""Compute the Online Retail II calibration for the order-history generator.

Reads online_retail_II.xlsx and writes calibration.json: the week-of-year order
index (docs/build-spec.md §5.4.1, adjusted as decided in §9.2 and §9.8) and the
consumer-like basket distributions (§5.4.2).

    docker compose --profile build run --rm calibrate

Deterministic: the same xlsx gives byte-identical JSON. Counts stay integers,
and the index is computed with exact fractions, rounded once at the end.
"""

import hashlib
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pandas as pd

WINDOW_START = date(2009, 12, 7)  # Monday of ISO week 2009-W50
WINDOW_END = date(2011, 12, 4)  # Sunday of ISO week 2011-W48
# 2010's Christmas closure had already begun in week 51 (158 orders against 486
# in 2009), so week 51 takes its 2009 count alone (build-spec §9.8)
SINGLE_YEAR_WEEKS = {51: 2009}
SMOOTHED_WEEKS = {22: (21, 23), 35: (34, 36), 52: (51, 1)}
CONSUMER_MAX_UNITS = 12
INDEX_DECIMALS = 4

SOURCE = {
    "dataset": "Online Retail II",
    "citation": "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. "
    "https://doi.org/10.24432/C5CG6D",
    "licence": "CC BY 4.0",
    "use": "calibration only: no row of the dataset is redistributed",
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code(value):
    """Invoice and StockCode cells are numbers or text; compare them as text."""
    text = str(value)
    return text[:-2] if text.endswith(".0") else text


def rounded(value):
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return float(exact.quantize(Decimal(1).scaleb(-INDEX_DECIMALS)))


def load_sales(xlsx):
    sheets = pd.read_excel(xlsx, sheet_name=None, engine="calamine")
    rows = pd.concat(sheets.values(), ignore_index=True)
    total = len(rows)
    rows = rows.drop_duplicates()
    deduplicated = len(rows)
    rows["invoice"] = rows["Invoice"].map(code)
    rows["product"] = rows["StockCode"].map(code)
    is_sale = (
        ~rows["invoice"].str.startswith("C")
        & (rows["Quantity"] > 0)
        & (rows["Price"] > 0)
        & rows["product"].str.match("^[0-9]{5}")
    )
    sales = rows[is_sale]
    summary = {
        "sheets": list(sheets),
        "rows": total,
        "rows_without_exact_duplicates": deduplicated,
        "rules": [
            "both sheets concatenated, exact duplicate rows dropped",
            "Invoice not prefixed C (cancellations)",
            "Quantity > 0",
            "Price > 0",
            "StockCode starts with 5 digits (products, not postage or fees)",
        ],
        "sale_lines": len(sales),
        "invoices": int(sales["invoice"].nunique()),
    }
    return sales, summary


def iso_weeks(start, end):
    day = start
    while day <= end:
        year, week, _ = day.isocalendar()
        yield year, week
        day += timedelta(days=7)


def week_of_year(sales):
    first = sales.groupby("invoice")["InvoiceDate"].min()
    in_window = first[
        (first >= pd.Timestamp(WINDOW_START)) & (first < pd.Timestamp(WINDOW_END + timedelta(days=1)))
    ]
    counts = in_window.dt.isocalendar().groupby(["year", "week"]).size().sort_index()
    orders = {(int(year), int(week)): int(n) for (year, week), n in counts.items()}

    per_week_number = {}
    for (_, week), n in orders.items():
        per_week_number.setdefault(week, []).append(n)
    # Week 53 occurs once in the window (2009) and has no orders: the index covers weeks 1-52
    means = {week: Fraction(sum(ns), len(ns)) for week, ns in sorted(per_week_number.items()) if week <= 52}
    if sorted(means) != list(range(1, 53)):
        raise SystemExit(f"expected orders in every week number 1-52, got {sorted(means)}")
    average = sum(means.values()) / 52
    raw = {week: mean / average for week, mean in means.items()}

    adjusted = dict(raw)
    for week, year in SINGLE_YEAR_WEEKS.items():
        adjusted[week] = orders[(year, week)] / average
    for week, (before, after) in SMOOTHED_WEEKS.items():
        adjusted[week] = (adjusted[before] + adjusted[after]) / 2
    scale = sum(adjusted.values()) / 52
    index = {week: value / scale for week, value in adjusted.items()}
    index[53] = index[52]

    in_year = lambda start, end: int(((first >= pd.Timestamp(start)) & (first < pd.Timestamp(end))).sum())
    return {
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "method": [
            "one date per invoice: its first InvoiceDate",
            "invoices dated within full ISO weeks 2009-W50 to 2011-W48",
            "orders counted per (ISO year, ISO week); weeks without orders are left out of the means, "
            "as in the measurement of build-spec §5.4.1",
            "raw index: mean orders per ISO week number, divided by the mean of the 52 week means "
            "(1.0 = an average week)",
        ],
        "invoices_in_window": len(in_window),
        "weeks_without_orders": [
            {"iso_year": year, "iso_week": week}
            for year, week in iso_weeks(WINDOW_START, WINDOW_END)
            if (year, week) not in orders
        ],
        "orders_per_iso_week": [
            {"iso_year": year, "iso_week": week, "orders": n} for (year, week), n in orders.items()
        ],
        "orders_december_to_november": {
            "2009-12 to 2010-11": in_year("2009-12-01", "2010-12-01"),
            "2010-12 to 2011-11": in_year("2010-12-01", "2011-12-01"),
        },
        "index_raw": {str(week): rounded(value) for week, value in raw.items()},
        "adjustments": {
            "decisions": "build-spec §9.2 and §9.8",
            "single_year_weeks": {str(week): year for week, year in SINGLE_YEAR_WEEKS.items()},
            "smoothed_weeks": {str(week): list(neighbours) for week, neighbours in SMOOTHED_WEEKS.items()},
            "rule": "in this order: each single-year week takes that year's count alone, over the raw "
            "average; each smoothed week takes the mean of its two neighbours (week 52's are the adjusted "
            "week 51 and week 1); the 52 values are rescaled to a mean of 1.0; week 53 takes week 52's value",
            "why": "UK bank holidays (weeks 22, 35) and a wholesaler's Christmas closure (week 52, and week "
            "51 of 2010) do not apply to an online consumer marketplace",
        },
        "index": {str(week): rounded(value) for week, value in index.items()},
    }


def basket(sales):
    with_customer = sales[sales["Customer ID"].notna()]
    units = with_customer.groupby("invoice")["Quantity"].sum()
    consumer_invoices = units[units <= CONSUMER_MAX_UNITS].index
    consumer = with_customer[with_customer["invoice"].isin(consumer_invoices)]
    products = consumer.groupby("invoice")["product"].nunique().value_counts().sort_index()
    quantities = consumer.groupby(["invoice", "product"])["Quantity"].sum().value_counts().sort_index()
    return {
        "method": [
            "consumer-like orders: sale lines of invoices with a Customer ID and "
            f"{CONSUMER_MAX_UNITS} units or fewer in total (the retailer sells mostly wholesale)",
            "products_per_order: number of invoices by count of distinct StockCodes",
            "units_per_product: number of (invoice, StockCode) pairs by summed Quantity",
            "sample from these counts, not from quantiles",
        ],
        "invoices_with_customer": int(units.size),
        "consumer_invoices": len(consumer_invoices),
        "products_per_order": {str(int(k)): int(n) for k, n in products.items()},
        "units_per_product": {str(int(k)): int(n) for k, n in quantities.items()},
    }


def main(xlsx, output):
    sales, sales_summary = load_sales(xlsx)
    calibration = {
        "description": "Calibration for the Albert's Marketplace order-history generator, "
        "measured on Online Retail II (docs/build-spec.md §5.4)",
        "source": {**SOURCE, "file": Path(xlsx).name, "sha256": sha256(xlsx)},
        "sales": sales_summary,
        "week_of_year": week_of_year(sales),
        "basket": basket(sales),
    }
    text = json.dumps(calibration, indent=2, ensure_ascii=False) + "\n"
    Path(output).write_text(text, encoding="utf-8", newline="\n")
    print(
        f"wrote {output}: {sales_summary['sale_lines']} sale lines, {sales_summary['invoices']} invoices, "
        f"sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: calibrate.py ONLINE_RETAIL_II_XLSX OUTPUT_JSON")
    main(sys.argv[1], sys.argv[2])
