"""Build places.json, the GeoNames postal-code snapshot behind generated addresses.

Downloads the GeoNames postal code files for the six countries, keeps postcode,
town and region, and writes them with their source and licence
(docs/build-spec.md §5.2, §9.16). GeoNames updates its files daily, so the
history generator reads this committed snapshot, not the live files.

    docker compose --profile build run --rm fetch-places
"""

import datetime as dt
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

SOURCE_URL = "https://download.geonames.org/export/zip/{country}.zip"
OUTPUT = Path(__file__).with_name("places.json")
POSTCODE_DIGITS = {"FR": 5, "DE": 5, "IT": 5, "ES": 5, "NL": 4, "BE": 4}

# Region names in the country's own language, where GeoNames gives them in English
REGION_NAMES = {
    "DE": {
        "Bavaria": "Bayern",
        "Lower Saxony": "Niedersachsen",
        "Saxony": "Sachsen",
        "Saxony-Anhalt": "Sachsen-Anhalt",
        "Thuringia": "Thüringen",
        "Mecklenburg-Western Pomerania": "Mecklenburg-Vorpommern",
        "Land Berlin": "Berlin",
    },
    "NL": {
        "North Brabant": "Noord-Brabant",
        "North Holland": "Noord-Holland",
        "South Holland": "Zuid-Holland",
        "Guelders": "Gelderland",
    },
}

RULES = [
    "each row is a distinct [postcode, town, region]: GeoNames postal code, place name and admin name1",
    "postcodes with exactly the country's number of digits: drops French CEDEX business codes such as '75021 CEDEX 01'",
    "Germany: rows with a GeoNames accuracy only, which drops the large-customer postcodes whose place names are companies",
    "rows without a region are dropped",
    "German and Dutch region names are given in the country's language where GeoNames gives them in English; "
    "Spanish names stay as GeoNames writes them, without accents",
    "the Netherlands: GeoNames has only the four digits of each postcode; the history generator adds the two letters",
]


def fetch(country):
    with urllib.request.urlopen(SOURCE_URL.format(country=country), timeout=120) as response:
        return response.read()


def places_of(country, archive_bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        text = archive.read(f"{country}.txt").decode("utf-8")
    lines = [line.split("\t") for line in text.splitlines() if line]
    kept = set()
    for fields in lines:
        postcode, town, region, accuracy = fields[1], fields[2], fields[3], fields[11]
        if len(postcode) != POSTCODE_DIGITS[country] or not postcode.isdigit():
            continue
        if not region or (country == "DE" and not accuracy):
            continue
        kept.add((postcode, town, REGION_NAMES.get(country, {}).get(region, region)))
    return len(lines), sorted(kept)


def write(snapshot, path):
    """JSON with one place per line, so the file stays readable and diffable."""
    out = ["{"]
    for key in ("description", "source", "rules"):
        out.append(f"  {json.dumps(key)}: {json.dumps(snapshot[key], ensure_ascii=False)},")
    out.append('  "countries": {')
    countries = list(snapshot["countries"].items())
    for i, (country, rows) in enumerate(countries):
        out.append(f"    {json.dumps(country)}: [")
        out.extend(
            f"      {json.dumps(list(row), ensure_ascii=False)}{',' if j < len(rows) - 1 else ''}"
            for j, row in enumerate(rows)
        )
        out.append("    ]" + ("," if i < len(countries) - 1 else ""))
    out.append("  }")
    out.append("}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def main():
    files, countries = {}, {}
    for country in POSTCODE_DIGITS:
        archive_bytes = fetch(country)
        total, rows = places_of(country, archive_bytes)
        files[f"{country}.zip"] = {
            "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            "rows_in_file": total,
            "rows_kept": len(rows),
        }
        countries[country] = rows
        regions = sorted({region for _, _, region in rows})
        print(f"{country}: {len(rows)} of {total} rows, {len({p for p, _, _ in rows})} postcodes, {len(regions)} regions: {regions}")

    snapshot = {
        "description": "GeoNames postal codes for the history generator's addresses, as [postcode, town, region] "
        "(docs/build-spec.md §5.2, §9.16)",
        "source": {
            "dataset": "GeoNames postal code files",
            "url": "https://download.geonames.org/export/zip/",
            "licence": "CC BY 4.0",
            "credit": "GeoNames, https://www.geonames.org",
            "downloaded": dt.date.today().isoformat(),
            "files": files,
        },
        "rules": RULES,
        "countries": countries,
    }
    write(snapshot, OUTPUT)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
