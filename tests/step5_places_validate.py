"""Step 5: the localised customers, addresses, phones and billing addresses."""
import collections
import json
import re
import subprocess
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
snapshot = json.load(open(REPO + r"\generators\history\places.json", encoding="utf-8"))
PLACES = {cc: {tuple(row) for row in rows} for cc, rows in snapshot["countries"].items()}
CODE = {"France": "FR", "Germany": "DE", "Italy": "IT", "Spain": "ES", "Netherlands": "NL", "Belgium": "BE"}
POPULATION = {"FR": 69112309, "DE": 83467117, "IT": 58942828, "ES": 49590099, "NL": 18130208, "BE": 11955308}
PHONE = {
    "FR": r"0[67][0-9]{8}", "DE": r"01[567][0-9]{8,9}", "IT": r"3[0-9]{9}",
    "ES": r"[67][0-9]{8}", "NL": r"06[0-9]{8}", "BE": r"04[0-9]{8}",
}


def query(sql):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "marketplace", "-XAt", "-F", "\t", "-c", sql],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode:
        raise SystemExit(out.stderr)
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def ok(label, bad, total=None):
    print(f"{'ok  ' if bad == 0 else 'FAIL'} {label}: {bad}" + (f" of {total}" if total is not None else ""))


print("snapshot:", {cc: len(rows) for cc, rows in snapshot["countries"].items()},
      "| GeoNames downloaded", snapshot["source"]["geonames"]["downloaded"],
      "| Eurostat year", snapshot["source"]["eurostat"]["year"], "updated", snapshot["source"]["eurostat"]["updated"])

buyers = query("""
    SELECT c.c_id, c.phone, s.country FROM customer c
    JOIN customer_shipping cs ON cs.c_id = c.c_id AND cs.is_default = '1'
    JOIN shipping_details s USING (address_id)""")
per_country = collections.Counter(CODE[country] for _, _, country in buyers)
total_pop = sum(POPULATION.values())
tvd = 0.5 * sum(abs(per_country[cc] / len(buyers) - POPULATION[cc] / total_pop) for cc in POPULATION)
print(f"buyers by country (default address) vs population: TVD {tvd:.4f} | "
      + ", ".join(f"{cc} {per_country[cc] / len(buyers):.3f}/{POPULATION[cc] / total_pop:.3f}" for cc in POPULATION))

ok("buyers with addresses in more than one country",
   int(query("SELECT count(*) FROM (SELECT cs.c_id FROM customer_shipping cs JOIN shipping_details s USING (address_id) GROUP BY cs.c_id HAVING count(DISTINCT s.country) > 1) x")[0][0]))
ok("addresses whose phone is not their customer's",
   int(query("SELECT count(*) FROM customer_shipping cs JOIN shipping_details s USING (address_id) JOIN customer c USING (c_id) WHERE s.phone <> c.phone")[0][0]))
ok("buyer phones not matching their country's mobile format",
   sum(not re.fullmatch(PHONE[CODE[country]], phone) for _, phone, country in buyers), len(buyers))
sellers = query("SELECT c.phone FROM customer c JOIN seller s ON s.seller_id = c.c_id")
ok("seller phones matching no country's format", sum(not any(re.fullmatch(p, phone) for p in PHONE.values()) for (phone,) in sellers), len(sellers))
ok("duplicate customer phones", int(query("SELECT count(*) - count(DISTINCT phone) FROM customer")[0][0]))
zero = collections.Counter(CODE[country] for _, phone, country in buyers if phone.startswith("0"))
print("     buyer phones with a leading 0 (pandas drops it):", dict(zero), "| phone lengths:",
      dict(sorted(collections.Counter(len(phone) for _, phone, _ in buyers).items())))

addresses = query("SELECT address_id, street_address, city, state, zip, country FROM shipping_details")
unknown, nl_format, nl_forbidden = 0, 0, 0
regions = collections.defaultdict(collections.Counter)
towns = collections.defaultdict(collections.Counter)
for _, street, city, state, zip_code, country in addresses:
    cc = CODE[country]
    postcode = zip_code
    if cc == "NL":
        match = re.fullmatch(r"([1-9][0-9]{3}) ([A-Z]{2})", zip_code)
        if not match:
            nl_format += 1
            continue
        postcode = match.group(1)
        nl_forbidden += match.group(2) in {"SS", "SD", "SA"}
    unknown += (postcode, city, state) not in PLACES[cc]
    regions[cc][state] += 1
    towns[cc][city] += 1
ok("addresses whose (postcode, town, region) is not in the snapshot", unknown, len(addresses))
ok("Dutch postcodes not in '1234 AB' form", nl_format)
ok("Dutch postcodes with SS, SD or SA", nl_forbidden)
print("     longest street, town, region, postcode:", [max(len(a[i]) for a in addresses) for i in (1, 2, 3, 4)])

french = re.compile(r"(?i)\b(rue|avenue|boulevard|chemin|place|impasse|all[ée]e|quai|route)\b")
belgian = [a for a in addresses if a[5] == "Belgium"]
for region in ("Wallonie", "Vlaanderen", "Bruxelles-Capitale"):
    rows = [a for a in belgian if a[3] == region]
    if rows:
        print(f"     Belgium, {region}: {len(rows)} addresses, French street words in {sum(bool(french.search(a[1])) for a in rows) / len(rows):.0%}")

ok("billing addresses that are not the default address glued",
   int(query("""
       SELECT count(*) FROM customer_payment cp
       JOIN payment_details p USING (payment_id)
       JOIN customer_shipping cs ON cs.c_id = cp.c_id AND cs.is_default = '1'
       JOIN shipping_details s ON s.address_id = cs.address_id
       WHERE p.billing_address <> s.street_address || s.city || s.state || s.zip""")[0][0]))
ok("addresses still in the United States", int(query("SELECT count(*) FROM shipping_details WHERE country = 'United States of America'")[0][0]))

print("region shares of addresses / of population, by country:")
for cc in POPULATION:
    total = sum(regions[cc].values())
    pop = snapshot["regions"][cc]
    pop_total = sum(r["population"] for r in pop.values())
    tvd = 0.5 * sum(abs(regions[cc][name] / total - pop[name]["population"] / pop_total) for name in pop)
    ordered = sorted(pop, key=lambda name: -pop[name]["population"])
    print(f"  {cc} (TVD {tvd:.4f}): " + "; ".join(
        f"{name} {regions[cc][name] / total:.1%}/{pop[name]['population'] / pop_total:.1%}" for name in ordered))
print("most frequent towns:", {cc: towns[cc].most_common(3) for cc in POPULATION})
print("samples:")
for cc in POPULATION:
    for a in [a for a in addresses if CODE[a[5]] == cc][:2]:
        print("  ", a[1:])
print("billing samples:", query("SELECT billing_address FROM payment_details ORDER BY payment_id LIMIT 3"))
