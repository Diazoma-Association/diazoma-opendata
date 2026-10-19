#!/usr/bin/env python3
"""Check the agriculture statistics tables in data/agriculture/ for consistency and against published figures.

Usage:
    python3 scripts/verify_agriculture_data.py              # structure and anchor values (reads only the CSV files)
    python3 scripts/verify_agriculture_data.py --reparse    # also re-reads the source spreadsheets and checks that
                                                            # importing them again changes nothing (needs openpyxl, xlrd)

Checks: no statistic is stored twice; every row points to a known publication, geography, product and variable; the
unit matches the variable; a value exists only for published numbers and is never a zero made of a dash; and the
totals agree with figures printed in the ELSTAT press releases of the same publications.
"""

import csv
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "agriculture"
UNITS = {"area": "stremma", "production": "tonne", "trees_total": "tree", "trees_regular": "tree"}
STATUSES = {"ok", "dash", "blank", "combined", "text"}

# (table, reference year, geography, product, variable, qualifier or None for the sum of all qualifiers, value, tolerance, source)
ANCHORS = [
    ("land_use", 2024, "EL", "land_use.synolo", "area", "", 27061208, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2024, πίνακας 1: 27.061,2 χιλ. στρέμματα"),
    ("land_use", 2024, "EL", "land_use.kalliergeies.arotraies", "area", "", 15894909, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2024, πίνακας 1: 15.894,9 χιλ. στρέμματα"),
    ("land_use", 2024, "EL", "land_use.agranapaysi", "area", "", 1046383, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2024, πίνακας 1: 1.046,4 χιλ. στρέμματα"),
    ("trees", 2018, "EL", "trees.elies", "production", None, 2764600, 50, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2018 και 2019: 2.764,6 χιλ. τόνοι ελιών"),
    ("trees", 2019, "EL", "trees.elies", "production", None, 3240100, 50, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2019: 3.240,1 χιλ. τόνοι ελιών"),
    ("trees", 2017, "EL", "trees.elies", "production", None, 2837800, 50, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2018: 2.837,8 χιλ. τόνοι ελιών"),
]


def read(name):
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    problems = []

    def fail(message):
        problems.append(message)

    geo = {g["geo_code"]: g for g in read("agri_geo.csv")}
    products = {p["product_code"]: p for p in read("agri_products.csv")}
    publications = read("agri_publications.csv")
    docs = {p["doc_id"] for p in publications}
    with (DATA / "spg06" / "manifest.csv").open(newline="", encoding="utf-8") as handle:
        manifest = {r["doc_id"]: r for r in csv.DictReader(handle)}
    for p in publications:
        if p["doc_id"] not in manifest:
            fail(f"publication {p['doc_id']} is not in the manifest")
        elif manifest[p["doc_id"]]["sha256"] != p["sha256"]:
            fail(f"checksum of {p['doc_id']} differs between manifest and publications")
    for doc, row in manifest.items():
        if not (DATA / "spg06" / row["edition"] / row["filename"]).exists():
            fail(f"source file of {doc} is missing")

    observations = read("agri_observations.csv")
    keys = Counter()
    by_key = {}
    for o in observations:
        key = (o["table_key"], o["ref_year"], o["geo_code"], o["product_code"], o["variable"], o["qualifier"])
        keys[key] += 1
        by_key[key] = o
        if o["geo_code"] not in geo:
            fail(f"unknown geography {o['geo_code']}")
        if o["product_code"] not in products:
            fail(f"unknown product {o['product_code']}")
        if o["source_doc"] not in docs:
            fail(f"unknown source document {o['source_doc']}")
        if UNITS.get(o["variable"]) != o["unit"]:
            fail(f"unit {o['unit']} does not fit variable {o['variable']}")
        if o["status"] not in STATUSES:
            fail(f"unknown status {o['status']}")
        if (o["value"] != "") != (o["status"] in ("ok", "combined")):
            fail(f"value {o['value']!r} with status {o['status']} ({key})")
        if o["value"] != "" and float(o["value"]) < 0:
            fail(f"negative value ({key})")
        if not re.fullmatch(r"20\d\d-\d\d-\d\d", o["last_updated"]):
            fail(f"bad last_updated {o['last_updated']!r}")
    duplicates = [k for k, n in keys.items() if n > 1]
    if duplicates:
        fail(f"{len(duplicates)} statistics are stored more than once, e.g. {duplicates[0]}")

    for table, year, g, product, variable, qualifier, expected, tolerance, source in ANCHORS:
        values = [float(o["value"]) for k, o in by_key.items()
                  if k[0] == table and k[1] == str(year) and k[2] == g and k[3] == product and k[4] == variable
                  and (qualifier is None or k[5] == qualifier) and o["status"] == "ok"]
        got = sum(values)
        if not values or abs(got - expected) > tolerance:
            fail(f"{product} {year}: found {got:g}, expected {expected:g} ({source})")

    if "--reparse" in sys.argv:
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "import_agriculture_data.py"), "--dry-run"],
                             capture_output=True, text=True)
        print(out.stdout.strip().splitlines()[0] if out.stdout else out.stderr.strip())
        m = re.search(r"(\d+) new, (\d+) updated, (\d+) unchanged, (\d+) duplicates, (\d+) kept as revision, (\d+) rejected", out.stdout)
        if out.returncode or not m or m.group(1) != "0" or m.group(2) != "0" or m.group(5) != "0" or m.group(6) != "0":
            fail("importing the source files again would change the stored statistics")

    if problems:
        for message in problems[:30]:
            print("FAIL", message)
        sys.exit(f"{len(problems)} problems")
    print(f"OK: {len(observations):,} statistics, {len(products)} products, {len(publications)} source tables, "
          f"{len(ANCHORS)} anchor values agree with the ELSTAT press releases.")


if __name__ == "__main__":
    main()
