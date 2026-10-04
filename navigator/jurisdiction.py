"""Module B, part 1: resolve each address to its jurisdiction stack and building facts.

Jurisdiction comes from the U.S. Census Geocoder (Incorporated Places layer) when it is
reachable; results are cached in cache/geocode.json so the demo never depends on the
network. When the geocoder is unavailable, a postal-city table maps mailing names to legal
cities (e.g. Dorchester -> Boston, Van Nuys -> Los Angeles) and the stack is marked as
lower confidence.

Building facts: year_built and units come from the assessor row. Where units are blank we
read a unit range from the use code/description (NJ MOD-IV class strings like "3S-F-D-6U",
Boston "A5 Apartment 5 to 14 Units", county "5+ units" codes), so coverage tests can still
be decided when the range settles them.
"""
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import corpus

ADDRESSES = corpus.STARTER / "data" / "sample_addresses.csv"
GEOCACHE = corpus.ROOT / "cache" / "geocode.json"
STATES = {"CA": "California", "NJ": "New Jersey", "MA": "Massachusetts"}

# Mailing names that are neighborhoods of an in-scope city (legal city on the right).
POSTAL_TO_CITY = {
    ("MA", "boston"): "Boston", ("MA", "allston"): "Boston", ("MA", "brighton"): "Boston",
    ("MA", "dorchester"): "Boston", ("MA", "east boston"): "Boston", ("MA", "hyde park"): "Boston",
    ("MA", "jamaica plain"): "Boston", ("MA", "mattapan"): "Boston", ("MA", "roxbury"): "Boston",
    ("MA", "south boston"): "Boston", ("MA", "charlestown"): "Boston", ("MA", "roslindale"): "Boston",
    ("MA", "west roxbury"): "Boston", ("MA", "cambridge"): "Cambridge",
    ("CA", "los angeles"): "Los Angeles", ("CA", "van nuys"): "Los Angeles", ("CA", "north hollywood"): "Los Angeles",
    ("CA", "sherman oaks"): "Los Angeles", ("CA", "reseda"): "Los Angeles", ("CA", "canoga park"): "Los Angeles",
    ("CA", "san pedro"): "Los Angeles", ("CA", "wilmington"): "Los Angeles", ("CA", "hollywood"): "Los Angeles",
    ("CA", "tujunga"): "Los Angeles", ("CA", "sun valley"): "Los Angeles", ("CA", "panorama city"): "Los Angeles",
    ("CA", "san francisco"): "San Francisco", ("CA", "san diego"): "San Diego", ("CA", "san ysidro"): "San Diego",
    ("CA", "la jolla"): "San Diego", ("CA", "berkeley"): "Berkeley", ("CA", "santa ana"): "Santa Ana",
    ("NJ", "jersey city"): "Jersey City", ("NJ", "hoboken"): "Hoboken", ("NJ", "newark"): "Newark",
}
IN_SCOPE_CITIES = {"CA": {"Los Angeles", "San Francisco", "San Diego", "Berkeley", "Santa Ana"},
                   "NJ": {"Jersey City", "Hoboken", "Newark"}, "MA": {"Boston", "Cambridge"}}
ZIP_PREFIX = {"CA": ("9",), "NJ": ("07", "08"), "MA": ("01", "02")}


def load_addresses():
    return list(csv.DictReader(open(ADDRESSES, encoding="utf-8")))


def _int(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def unit_range(row):
    """(exact_units, min_units, max_units, basis) from the assessor row."""
    u = _int(row.get("units"))
    code, desc = row.get("use_code", ""), row.get("use_description", "")
    # NJ MOD-IV building class strings: "3S-F-D-6U-NH", "3B-7U/4B-24U-G" (sum over buildings)
    nj = re.findall(r"(\d+)\s*U(?![A-Z]{2,}\b)", desc) if row["state"] == "NJ" else []
    n = sum(int(x) for x in nj) if nj else None
    if row["state"] == "NJ" and code == "4C":
        # Property class 4C means 5+ units (2-4 family homes are class 2), so a smaller count on a 4C
        # parcel is a partial description (one building of several lots, or a commercial count).
        if n and n >= 5:
            return n, n, n, f"unit count parsed from MOD-IV class '{desc}'" + (f" (assessor units {u} ignored)" if u and u != n else "")
        if u and u >= 5:
            return u, u, u, "assessor unit count"
        if u or n:
            return None, 5, None, f"NJ property class 4C (5+ units); record shows {u or n}, read as a partial description"
    if u:
        return u, u, u, "assessor unit count"
    if n:
        return n, n, n, f"unit count parsed from MOD-IV class '{desc}'"
    m = re.search(r"(\d+)\s*(?:to|-)\s*(\d+)[- ]*UNIT", desc, re.I)
    if m:
        return None, int(m.group(1)), int(m.group(2)), f"range from use code '{code} {desc}'"
    m = re.search(r">\s*(\d+)[- ]*UNIT", desc, re.I)
    if m:
        return None, int(m.group(1)) + 1, None, f"range from use code '{code} {desc}'"
    m = re.search(r"(\d+)\s*(?:\+|or more)\s*(?:units|apartments)", desc, re.I) or \
        re.search(r"(five) or more apartments", desc, re.I)
    if m:
        n = 5 if m.group(1).lower() == "five" else int(m.group(1))
        return None, n, None, f"range from use code '{code} {desc}'"
    m = re.search(r"(\d+)\s*Units or more", desc, re.I)
    if m:
        return None, int(m.group(1)), None, f"range from use code '{code} {desc}'"
    if row["state"] == "NJ" and code == "4C":
        # Class 4C = apartment building; NJ assessors classify 5+ units as 4C (fewer is class 2).
        return None, 5, None, "NJ property class 4C (apartments, 5+ units)"
    if re.search(r"\bAPT|APARTMENT", desc, re.I):
        return None, 2, None, f"apartment use code '{code} {desc}'"
    return None, None, None, "no unit information"


def _geocode_one(addr):
    q = f"{addr['street_address']}, {addr['postal_city']}, {addr['state']} {addr['zip']}"
    params = urllib.parse.urlencode({"address": q, "benchmark": "Public_AR_Current", "vintage": "Current_Current",
                                     "layers": "Incorporated Places,Counties", "format": "json"})
    url = f"https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress?{params}"
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.load(r)
    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        return {"matched": False}
    g = matches[0]["geographies"]
    place = (g.get("Incorporated Places") or [{}])[0]
    county = (g.get("Counties") or [{}])[0]
    return {"matched": True, "matched_address": matches[0].get("matchedAddress"),
            "place": place.get("BASENAME"), "county": county.get("NAME"),
            "lon": matches[0]["coordinates"]["x"], "lat": matches[0]["coordinates"]["y"]}


def geocode_all(addresses, refresh=False):
    """Fill cache/geocode.json from the Census Geocoder. Safe to rerun; skips cached rows."""
    cache = json.loads(GEOCACHE.read_text(encoding="utf-8")) if GEOCACHE.exists() else {}
    todo = [a for a in addresses if refresh or a["address_id"] not in cache]
    for i, a in enumerate(todo):
        try:
            cache[a["address_id"]] = _geocode_one(a)
        except Exception as e:  # network blocked or service down
            print(f"geocoder unavailable ({e.__class__.__name__}); using postal-city fallback")
            break
        if i % 25 == 0:
            GEOCACHE.write_text(json.dumps(cache, indent=0), encoding="utf-8")
        time.sleep(0.05)
    GEOCACHE.parent.mkdir(parents=True, exist_ok=True)
    GEOCACHE.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    return cache


def resolve(addr, geocache):
    """Jurisdiction stack + facts for one address row."""
    st = addr["state"]
    g = geocache.get(addr["address_id"]) or {}
    notes = []
    if g.get("matched"):
        place = g.get("place")
        city = place if place in IN_SCOPE_CITIES[st] else None
        basis = f"Census Geocoder: {g.get('matched_address')} -> {place or 'unincorporated'}, {g.get('county')}"
        confidence = 0.95
        if not city:
            notes.append(f"Geocoder places this address in {place or 'an unincorporated area'}, outside the in-scope cities.")
    else:
        city = POSTAL_TO_CITY.get((st, addr["postal_city"].strip().lower()))
        basis = f"postal city '{addr['postal_city']}' mapped to legal city (geocoder not run)"
        confidence = 0.8 if city and city.lower() != addr["postal_city"].strip().lower() else 0.85
        if city and city.lower() != addr["postal_city"].strip().lower():
            notes.append(f"Mailing name '{addr['postal_city']}' is a neighborhood of {city}.")
    z = addr.get("zip", "")
    if z and not z.startswith(ZIP_PREFIX[st]):
        notes.append(f"ZIP {z} is not a {st} ZIP code; the assessor record may have a data error.")
        confidence = min(confidence, 0.7)
    exact, umin, umax, ubasis = unit_range(addr)
    stack = [{"level": "state", "name": STATES[st], "code": st}]
    if city:
        stack.append({"level": "city", "name": city, "code": f"{city}, {st}"})
    return {
        "address_id": addr["address_id"],
        "address": f"{addr['street_address']}, {addr['postal_city']}, {st} {z}",
        "state": st,
        "city": city,
        "stack": stack,
        "jurisdiction_basis": basis,
        "jurisdiction_confidence": confidence,
        "year_built": _int(addr.get("year_built")),
        "units": exact,
        "units_min": umin,
        "units_max": umax,
        "units_basis": ubasis,
        "use": f"{addr.get('use_code','')} {addr.get('use_description','')}".strip(),
        "source_dataset": addr.get("source_dataset"),
        "notes": notes,
    }


def resolve_all():
    addrs = load_addresses()
    cache = json.loads(GEOCACHE.read_text(encoding="utf-8")) if GEOCACHE.exists() else {}
    return [resolve(a, cache) for a in addrs]


if __name__ == "__main__":
    import collections
    addrs = load_addresses()
    geocode_all(addrs)
    res = resolve_all()
    print(collections.Counter((r["state"], r["city"]) for r in res))
    print(collections.Counter(r["units_basis"].split(" '")[0] for r in res))
