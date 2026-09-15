"""Build places.json: the postcodes and regional populations behind generated addresses.

Downloads the GeoNames postal code files for the six countries, keeps postcode,
town and region, and gives each region its population from Eurostat, so the
history generator spreads addresses like the population (docs/build-spec.md
§5.2, §9.16). Both sources change over time, so the generator reads this
committed snapshot, not the live data.

    docker compose --profile build run --rm fetch-places
"""

import datetime as dt
import hashlib
import io
import itertools
import json
import urllib.request
import zipfile
from pathlib import Path

GEONAMES_URL = "https://download.geonames.org/export/zip/{country}.zip"
EUROSTAT_DATASET = "demo_r_pjanaggr3"
EUROSTAT_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
    f"{EUROSTAT_DATASET}?lang=EN&sex=T&age=TOTAL&lastTimePeriod=1&{{geos}}"
)
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

# The Eurostat NUTS regions behind each region name: NUTS 1 for France, Germany
# and Belgium, NUTS 2 for Italy, Spain and the Netherlands
NUTS = {
    "FR": {
        "Île-de-France": ["FR1"], "Centre-Val de Loire": ["FRB"], "Bourgogne-Franche-Comté": ["FRC"],
        "Normandie": ["FRD"], "Hauts-de-France": ["FRE"], "Grand Est": ["FRF"], "Pays de la Loire": ["FRG"],
        "Bretagne": ["FRH"], "Nouvelle-Aquitaine": ["FRI"], "Occitanie": ["FRJ"],
        "Auvergne-Rhône-Alpes": ["FRK"], "Provence-Alpes-Côte d'Azur": ["FRL"], "Corse": ["FRM"],
    },
    "DE": {
        "Baden-Württemberg": ["DE1"], "Bayern": ["DE2"], "Berlin": ["DE3"], "Brandenburg": ["DE4"],
        "Bremen": ["DE5"], "Hamburg": ["DE6"], "Hessen": ["DE7"], "Mecklenburg-Vorpommern": ["DE8"],
        "Niedersachsen": ["DE9"], "Nordrhein-Westfalen": ["DEA"], "Rheinland-Pfalz": ["DEB"], "Saarland": ["DEC"],
        "Sachsen": ["DED"], "Sachsen-Anhalt": ["DEE"], "Schleswig-Holstein": ["DEF"], "Thüringen": ["DEG"],
    },
    "IT": {
        "Piemonte": ["ITC1"], "Valle D'Aosta": ["ITC2"], "Liguria": ["ITC3"], "Lombardia": ["ITC4"],
        "Abruzzi": ["ITF1"], "Molise": ["ITF2"], "Campania": ["ITF3"], "Puglia": ["ITF4"], "Basilicata": ["ITF5"],
        "Calabria": ["ITF6"], "Sicilia": ["ITG1"], "Sardegna": ["ITG2"], "Trentino-Alto Adige": ["ITH1", "ITH2"],
        "Veneto": ["ITH3"], "Friuli-Venezia Giulia": ["ITH4"], "Emilia-Romagna": ["ITH5"], "Toscana": ["ITI1"],
        "Umbria": ["ITI2"], "Marche": ["ITI3"], "Lazio": ["ITI4"],
    },
    "ES": {
        "Galicia": ["ES11"], "Asturias": ["ES12"], "Cantabria": ["ES13"], "Pais Vasco": ["ES21"],
        "Navarra": ["ES22"], "La Rioja": ["ES23"], "Aragon": ["ES24"], "Madrid": ["ES30"],
        "Castilla - Leon": ["ES41"], "Castilla - La Mancha": ["ES42"], "Extremadura": ["ES43"],
        "Cataluna": ["ES51"], "Comunidad Valenciana": ["ES52"], "Baleares": ["ES53"], "Andalucia": ["ES61"],
        "Murcia": ["ES62"], "Ceuta": ["ES63"], "Melilla": ["ES64"], "Canarias": ["ES70"],
    },
    "NL": {
        "Groningen": ["NL11"], "Friesland": ["NL12"], "Drenthe": ["NL13"], "Overijssel": ["NL21"],
        "Gelderland": ["NL22"], "Flevoland": ["NL23"], "Noord-Holland": ["NL32"], "Zeeland": ["NL34"],
        "Utrecht": ["NL35"], "Zuid-Holland": ["NL36"], "Noord-Brabant": ["NL41"], "Limburg": ["NL42"],
    },
    "BE": {"Bruxelles-Capitale": ["BE1"], "Vlaanderen": ["BE2"], "Wallonie": ["BE3"]},
}

RULES = [
    "each place is a distinct [postcode, town, region]: GeoNames postal code, place name and admin name1",
    "postcodes with exactly the country's number of digits: drops French CEDEX business codes such as '75021 CEDEX 01'",
    "Germany: rows with a GeoNames accuracy only, which drops the large-customer postcodes whose place names are companies",
    "rows without a region are dropped",
    "German and Dutch region names are given in the country's language where GeoNames gives them in English; "
    "Spanish names stay as GeoNames writes them, without accents",
    "the Netherlands: GeoNames has only the four digits of each postcode; the history generator adds the two letters",
    "each region's population is the sum of its Eurostat NUTS regions (regions.nuts), on 1 January of the latest year",
]


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as response:
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


def fetch_populations(codes):
    data = json.loads(fetch(EUROSTAT_URL.format(geos="&".join(f"geo={code}" for code in codes))))
    ids = data["id"]
    categories = [sorted(data["dimension"][d]["category"]["index"].items(), key=lambda kv: kv[1]) for d in ids]
    populations, years = {}, set()
    for flat, combo in enumerate(itertools.product(*[[key for key, _ in c] for c in categories])):
        value = data["value"].get(str(flat))
        if value is not None:
            key = dict(zip(ids, combo))
            populations[key["geo"]] = int(value)
            years.add(key["time"])
    missing = sorted(set(codes) - set(populations))
    if missing:
        raise SystemExit(f"Eurostat has no population for {missing}")
    return populations, sorted(years), data.get("updated")


def write(snapshot, path):
    """JSON with one region set and one place per line, so the file stays readable and diffable."""
    out = ["{"]
    for key in ("description", "source", "rules"):
        out.append(f"  {json.dumps(key)}: {json.dumps(snapshot[key], ensure_ascii=False)},")
    out.append('  "regions": {')
    regions = list(snapshot["regions"].items())
    for i, (country, by_region) in enumerate(regions):
        comma = "," if i < len(regions) - 1 else ""
        out.append(f"    {json.dumps(country)}: {json.dumps(by_region, ensure_ascii=False)}{comma}")
    out.append("  },")
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
    today = dt.date.today().isoformat()
    files, countries = {}, {}
    for country in POSTCODE_DIGITS:
        archive_bytes = fetch(GEONAMES_URL.format(country=country))
        total, rows = places_of(country, archive_bytes)
        files[f"{country}.zip"] = {
            "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            "rows_in_file": total,
            "rows_kept": len(rows),
        }
        countries[country] = rows

    codes = sorted({code for by_region in NUTS.values() for nuts in by_region.values() for code in nuts})
    populations, years, updated = fetch_populations(codes)
    regions = {}
    for country, rows in countries.items():
        present = sorted({region for _, _, region in rows})
        unmapped = [region for region in present if region not in NUTS[country]]
        unused = [region for region in NUTS[country] if region not in present]
        if unmapped or unused:
            raise SystemExit(f"{country}: regions without NUTS codes {unmapped}, NUTS regions without places {unused}")
        regions[country] = {
            region: {"nuts": NUTS[country][region], "population": sum(populations[c] for c in NUTS[country][region])}
            for region in present
        }
        print(f"{country}: {len(rows)} of {files[country + '.zip']['rows_in_file']} rows, "
              f"{len({p for p, _, _ in rows})} postcodes, {len(present)} regions, "
              f"population {sum(r['population'] for r in regions[country].values())}")

    snapshot = {
        "description": "Places for the history generator's addresses: GeoNames postcodes as [postcode, town, region], "
        "and each region's Eurostat population (docs/build-spec.md §5.2, §9.16)",
        "source": {
            "geonames": {
                "dataset": "GeoNames postal code files",
                "url": "https://download.geonames.org/export/zip/",
                "licence": "CC BY 4.0",
                "credit": "GeoNames, https://www.geonames.org",
                "downloaded": today,
                "files": files,
            },
            "eurostat": {
                "dataset": f"Population on 1 January by broad age group, sex and NUTS 3 region ({EUROSTAT_DATASET})",
                "url": f"https://ec.europa.eu/eurostat/databrowser/view/{EUROSTAT_DATASET}/default/table",
                "filters": "sex = total, age = total",
                "year": years,
                "updated": updated,
                "credit": "Eurostat",
                "downloaded": today,
            },
        },
        "rules": RULES,
        "regions": regions,
        "countries": countries,
    }
    write(snapshot, OUTPUT)
    print(f"wrote {OUTPUT}: Eurostat year {years}, updated {updated}")


if __name__ == "__main__":
    main()
