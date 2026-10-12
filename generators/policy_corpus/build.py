"""Albert's Marketplace's help centre: the policy corpus release (policy-corpus-v1.0.0).

Builds, from this folder and the dataset release:
  sources/01-05*.md          the help centre and four product pages, written by hand
  06-product-catalogue.md    150 real products drawn from the dataset release (seed fixed)
into PDFs, the files students parse, plus CHECKSUMS.

Runs in a container, from the repository root:

  docker run --rm -v "$PWD:/repo" -w /repo python:3.12-slim sh -c \
    "apt-get update -qq && apt-get install -y -qq fonts-dejavu-core >/dev/null && \
     pip install -q fpdf2==2.8.9 markdown==3.11 && python generators/policy_corpus/build.py"

Writes data/policy-corpus/ (git-ignored, like every release asset).
"""

import csv
import datetime
import hashlib
import io
import json
import random
import re
import tarfile
from pathlib import Path

import markdown
from fpdf import FPDF

HERE = Path(__file__).parent
REPO = HERE.parents[1]
RELEASE = REPO / "data" / "release"
OUT = REPO / "data" / "policy-corpus"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

N, SEED = 150, 20261004
HANDWRITTEN = {"B00NT0AR7E", "B00UB6VSJA", "B01DTSS60A", "B08R1BFJG5"}  # the pages in 05-product-pages.md
DROP = {"UPC", "Package Dimensions", "Is Discontinued By Manufacturer", "Manufacturer"}
ASCII_PUNCT = str.maketrans({"（": "(", "）": ")", "，": ",", "【": "[", "】": "]", "：": ":", "；": ";"})


def catalogue() -> str:
    """150 products from the dataset release, the same every time."""
    tarball = RELEASE / "legacy_csv.tar.gz"
    expected = dict(reversed(l.split()) for l in (RELEASE / "CHECKSUMS").read_text().splitlines() if l.strip())
    assert hashlib.sha256(tarball.read_bytes()).hexdigest() == expected["legacy_csv.tar.gz"], "not the released file"
    csv.field_size_limit(10**8)
    with tarfile.open(tarball) as tar:
        def table(name):
            f = tar.extractfile(f"legacy_csv/{name}.csv")
            return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", newline="")))
        products = table("product")
        cats = {c["category_id"]: c["name"] for c in table("category")}
    pool = [p for p in products if p["p_name"].strip() and p["p_id"] not in HANDWRITTEN]
    chosen = sorted(random.Random(SEED).sample(pool, N), key=lambda p: p["p_name"].lower())
    lines = ["# Product catalogue: extract", "",
             "Albert's Marketplace · Product pages as listed · Extract of 1 October 2026", "",
             f"{N} products. Attributes are as the sellers entered them.", ""]
    for p in chosen:
        attrs = {k: v for k, v in json.loads(p["p_desc"]).items() if k not in DROP and str(v).strip()}
        lines += [f"## {p['p_name'].strip().translate(ASCII_PUNCT)}", "",
                  f"Product id {p['p_id']} · Category: {cats.get(p['category_id'], '')} · "
                  f"Price: €{float(p['price']):.2f}", ""]
        if attrs:
            lines += ["; ".join(f"{k}: {v}" for k, v in attrs.items()) + ".", ""]
    return "\n".join(lines)


class Doc(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("dejavu", size=8)
        self.set_text_color(110, 110, 110)
        self.cell(0, 8, f"Albert's Marketplace · page {self.page_no()}", align="C")


def pdf(text: str, title: str, out: Path):
    html = markdown.markdown(text, extensions=["tables"])
    # fpdf2 lays out no inline tags inside a table cell: keep their text, drop the tags
    html = re.sub(r"<td>(.*?)</td>", lambda m: "<td>" + re.sub(r"</?(strong|em|code)>", "", m.group(1)) + "</td>", html)
    doc = Doc(format="A4")
    doc.add_font("dejavu", "", FONT)
    doc.add_font("dejavu", "B", BOLD)
    doc.set_font("dejavu", size=10.5)
    doc.set_margins(20, 18, 20)
    doc.set_auto_page_break(True, margin=18)
    doc.set_title(title)
    doc.set_author("Albert's Marketplace")
    doc.set_creation_date(datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc))  # same bytes on every build
    doc.add_page()
    doc.write_html(html, font_family="dejavu")
    doc.output(str(out))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    docs = {p.stem: p.read_text(encoding="utf-8") for p in sorted((HERE / "sources").glob("0*.md"))}
    docs["06-product-catalogue"] = catalogue()
    for name, text in docs.items():
        pdf(text, name, OUT / f"{name}.pdf")
        print("written", f"{name}.pdf")
    card = REPO / "docs" / "policy-corpus-card.md"
    (OUT / "POLICY_CORPUS_CARD.md").write_bytes(card.read_bytes())
    sums = "".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n"
                   for f in sorted(OUT.iterdir()) if f.name != "CHECKSUMS")
    (OUT / "CHECKSUMS").write_text(sums, encoding="utf-8", newline="\n")
    print(sums, end="")
