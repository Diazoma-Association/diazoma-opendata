#!/usr/bin/env python3
"""Check the agriculture statistics tables in data/agriculture/ for consistency and against published figures.

Usage:
    python3 scripts/verify_agriculture_data.py              # structure and anchor values (reads only the CSV files)
    python3 scripts/verify_agriculture_data.py --reparse    # also re-reads the source spreadsheets and checks that
                                                            # importing them again changes nothing (needs openpyxl, xlrd)

Checks: no statistic is stored twice; every row points to a known publication, geography, product and variable; the
unit matches the variable; a value exists only for published numbers and is never a zero made of a dash; and the
totals agree with figures printed in the ELSTAT press releases of the same publications (SPG06 annual crops, SPG32
and SPK12 farm structure survey). SPK33 has no press release; its tables are checked for internal consistency by the
importer (regions against units, country against regions) and unusual jumps are listed as warnings.
"""

import csv
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agri_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "agriculture"
STATUSES = {"ok", "dash", "blank", "combined", "text", "confidential"}

# (table, reference year, geography, product, variable, qualifier or None for the sum of all qualifiers, value, tolerance, source)
ANCHORS = [
    ("land_use", 2024, "EL", "land_use.synolo", "area", "", 27061208, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2024, πίνακας 1: 27.061,2 χιλ. στρέμματα"),
    ("land_use", 2024, "EL", "land_use.kalliergeies.arotraies", "area", "", 15894909, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2024, πίνακας 1: 15.894,9 χιλ. στρέμματα"),
    ("land_use", 2024, "EL", "land_use.agranapaysi", "area", "", 1046383, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2024, πίνακας 1: 1.046,4 χιλ. στρέμματα"),
    ("trees", 2018, "EL", "trees.elies", "production", None, 2764600, 50, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2018 και 2019: 2.764,6 χιλ. τόνοι ελιών"),
    ("trees", 2019, "EL", "trees.elies", "production", None, 3240100, 50, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2019: 3.240,1 χιλ. τόνοι ελιών"),
    ("trees", 2017, "EL", "trees.elies", "production", None, 2837800, 50, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΓΕ 2018: 2.837,8 χιλ. τόνοι ελιών"),
    ("fs_farm_types", 2023, "EL", "fs_farm_types.synolo", "holdings", "", 527186, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: 527.186 εκμεταλλεύσεις"),
    ("fs_land_use", 2023, "EL", "fs_land_use.me_chrisimopoioymeni_georgiki_ektasi", "holdings", "", 519764, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: 519.764 εκμεταλλεύσεις με ΧΓΕ"),
    ("fs_farm_types", 2023, "EL", "fs_farm_types.synolo", "area", "", 28570000, 500, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: ΧΓΕ 28.570 χιλ. στρέμματα"),
    ("fs_farm_types", 2023, "EL", "fs_farm_types.amigos_georgikes_ekmetalleyseis", "holdings", "", 447371, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: 447.371 αμιγώς γεωργικές"),
    ("fs_farm_types", 2023, "EL", "fs_farm_types.meiktes_ekmetalleyseis", "holdings", "", 65746, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: 65.746 μεικτές"),
    ("fs_farm_types", 2023, "EL", "fs_farm_types.amigos_ktinotrofikes_ekmetalleyseis", "holdings", "", 14069, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: 14.069 αμιγώς κτηνοτροφικές"),
    ("fs_farm_types", 2016, "EL", "fs_farm_types.synolo", "holdings", "", 684902, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: 684.902 εκμεταλλεύσεις"),
    ("fs_farm_types", 2016, "EL", "fs_farm_types.synolo", "area", "", 31526000, 500, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: ΧΓΕ 31.526 χιλ. στρέμματα"),
    ("fs_farm_types", 2016, "EL", "fs_farm_types.amigos_georgikes_ekmetalleyseis", "holdings", "", 562965, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: 562.965 αμιγώς γεωργικές"),
    ("fs_farm_types", 2016, "EL", "fs_farm_types.meiktes_ekmetalleyseis", "holdings", "", 105709, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: 105.709 μεικτές"),
    ("fs_irrigation", 2016, "EL", "fs_irrigation.synolo", "area", "", 10749000, 500, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: αρδευθείσα έκταση 10.749 χιλ. στρέμματα"),
    ("ix_factors", 2025, "EL", "ix_factors.general", "annual_change", "", 4.5, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΑΣΠ 2025: Γενικός Δείκτης +4,5%"),
    ("ix_factors", 2024, "EL", "ix_factors.general", "annual_change", "", 5.7, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΑΣΠ 2025: Γενικός Δείκτης 2024 +5,7%"),
    ("ix_factors", 2025, "EL", "ix_factors.labour", "annual_change", "", 7.6, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΑΣΠ 2025: Δείκτης Αμοιβής Εργασίας +7,6%"),
    ("ix_factors", 2025, "EL", "ix_factors.land", "annual_change", "", 2.6, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΑΣΠ 2025: Δείκτης Ενοικίων Γης +2,6%"),
    ("ix_factors", 2025, "EL", "ix_factors.capital", "annual_change", "", 1.5, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΑΣΠ 2025: Δείκτης Αμοιβής Κεφαλαίου +1,5%"),
    ("ix_factors", 2025, "EL", "ix_factors.interest", "annual_change", "", -1.6, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΑΣΠ 2025: δείκτης τόκων δανείων −1,6%"),
    ("fs_livestock", 2023, "EL43", "fs_livestock.provatoeidi", "animals", "", 2379775, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Κρήτη, 2.379.775 προβατοειδή"),
    ("fs_livestock", 2023, "EL63", "fs_livestock.provatoeidi", "animals", "", 1526053, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Δυτική Ελλάδα, 1.526.053 προβατοειδή"),
    ("fs_livestock", 2023, "EL43", "fs_livestock.aiges", "animals", "", 553066, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Κρήτη, 553.066 αιγοειδή"),
    ("fs_livestock", 2023, "EL54", "fs_livestock.choiroi", "animals", "", 168664, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Ήπειρος, 168.664 χοίροι"),
    ("fs_livestock", 2023, "EL54", "fs_livestock.poylerika", "animals", "", 11318800, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Ήπειρος, 11.318.800 πουλερικά"),
    ("fs_livestock", 2023, "EL52", "fs_livestock.vooeidi.synolo", "animals", "", 142860, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Κεντρική Μακεδονία, 142.860 βοοειδή"),
    ("fs_livestock_units", 2023, "EL43", "fs_livestock_units.synolo", "livestock_units", "", 312008, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Κρήτη, 312.008 ζωικές μονάδες"),
    ("fs_livestock_units", 2023, "EL63", "fs_livestock_units.synolo", "livestock_units", "", 276615, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Δυτική Ελλάδα, 276.615 ζωικές μονάδες"),
    ("fs_livestock_units", 2023, "EL52", "fs_livestock_units.synolo", "livestock_units", "", 267609, 0, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: Κεντρική Μακεδονία, 267.609 ζωικές μονάδες"),
    ("aq_production", 2024, "EL", "aq_production.geniko_synolo", "quantity_kg", "total", 127495100, 50000, "ΕΛΣΤΑΤ, δελτίο τύπου Έρευνας Υδατοκαλλιεργειών 2024: 127.495,1 τόνοι"),
    ("aq_production", 2024, "EL", "aq_production.geniko_synolo", "value_eur", "total", 689461000, 50000, "ΕΛΣΤΑΤ, δελτίο τύπου Έρευνας Υδατοκαλλιεργειών 2024: 689.461,0 χιλ. ευρώ"),
    ("aq_production", 2024, "EL", "aq_production.psaria.synolo_omadas", "quantity_kg", "total", 114805300, 50000, "ΕΛΣΤΑΤ, δελτίο τύπου Έρευνας Υδατοκαλλιεργειών 2024: ψάρια 114.805,3 τόνοι"),
    ("aq_production", 2024, "EL", "aq_production.psaria.lavraki", "quantity_kg", "total", 48042700, 50000, "ΕΛΣΤΑΤ, δελτίο τύπου Έρευνας Υδατοκαλλιεργειών 2024: λαβράκι 48.042,7 τόνοι"),
]

# Shares printed in the press releases of the farm structure survey (SPG12 employment): numerator, denominator (a total
# minus the listed parts), expected percent, tolerance in percentage points. In 2023 the press release leaves the
# mutual-aid category out of its total, which the table includes.
T = "fs_employment"
FAMILY16 = "fs_employment.katochoi_kai_meli_toy_noikokyrioy_toys_poy_ergastikan_stin_ekmetalleysi"
FAMILY23 = "fs_employment.katochoi_kai_meli_tis_oikogeneias_toys_poy_apascholithikan_stin_ekmetalleysi"
AID = "fs_employment.apascholisi_sto_plaisio_allilovoitheias_ton_georgon"
SEASONAL, PERMANENT = "fs_employment.epochikoi_ergates", "fs_employment.taktika_apascholoymenoi"
RATIO_ANCHORS = [
    (2016, "persons", SEASONAL, [], 30.9, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: οι εποχικοί εργάτες είναι το 30,9% των απασχολουμένων"),
    (2016, "persons", PERMANENT, [], 1.2, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: οι μόνιμοι εργάτες είναι το 1,2% των απασχολουμένων"),
    (2016, "workdays", SEASONAL, [], 10.2, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: οι εποχικοί εργάτες κάνουν το 10,2% των ημερών εργασίας"),
    (2016, "workdays", PERMANENT, [], 5.6, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2016: οι μόνιμοι εργάτες κάνουν το 5,6% των ημερών εργασίας"),
    (2023, "persons", FAMILY23, [AID], 37.1, 0.1, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: το οικογενειακό εργατικό δυναμικό είναι το 37,1% των απασχολουμένων"),
    (2023, "persons", SEASONAL, [AID], 39.7, 0.1, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: οι εποχικοί εργάτες είναι το 39,7% των απασχολουμένων"),
    (2023, "workdays", FAMILY23, [AID], 78.1, 0.1, "ΕΛΣΤΑΤ, δελτίο τύπου ΕΔΓΚΕ 2023: το οικογενειακό εργατικό δυναμικό κάνει το 78,1% των ημερών εργασίας"),
]


# Year-on-year changes of a monthly index printed in the press release of the month (table, product, month, year, expected %, tolerance).
# Only the input index is used: the output index of the same month has been revised since the release (-8,0% then, -7,5% now).
YEAR_ON_YEAR = [
    ("ix_input", "ix_input.c220000", "M08", 2025, -0.8, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου Δεικτών Τιμών Εισροών και Εκροών Αυγούστου 2025: Γενικός Δείκτης Εισροών −0,8%"),
    ("ix_input", "ix_input.c220000", "M08", 2024, -1.9, 0.05, "ΕΛΣΤΑΤ, δελτίο τύπου Δεικτών Τιμών Εισροών και Εκροών Αυγούστου 2025: Γενικός Δείκτης Εισροών Αυγούστου 2024 −1,9%"),
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
    manifest = {}
    for dataset in agri_sources.SOURCES:
        with agri_sources.manifest_path(dataset).open(newline="", encoding="utf-8") as handle:
            for r in csv.DictReader(handle):
                manifest[r["doc_id"]] = dict(r, dataset=dataset)
    units = {v["variable"]: v["unit"] for v in read("agri_variables.csv")}
    datasets_of_doc = {p["doc_id"]: p["dataset"] for p in publications}
    for p in publications:
        if p["doc_id"] not in manifest:
            fail(f"publication {p['doc_id']} is not in the manifest")
        elif manifest[p["doc_id"]]["sha256"] != p["sha256"]:
            fail(f"checksum of {p['doc_id']} differs between manifest and publications")
        elif manifest[p["doc_id"]]["dataset"] != p["dataset"]:
            fail(f"{p['doc_id']} belongs to {manifest[p['doc_id']]['dataset']} in the manifest and to {p['dataset']} in the publications")
    for doc, row in manifest.items():
        if not (agri_sources.raw_dir(row["dataset"]) / row["edition"] / row["filename"]).exists():
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
        if o["dataset"] != datasets_of_doc.get(o["source_doc"]):
            fail(f"dataset {o['dataset']} of a statistic differs from the dataset of its source document {o['source_doc']}")
        if units.get(o["variable"]) != o["unit"]:
            fail(f"unit {o['unit']} does not fit variable {o['variable']}")
        if o["status"] not in STATUSES:
            fail(f"unknown status {o['status']}")
        if (o["value"] != "") != (o["status"] in ("ok", "combined")):
            fail(f"value {o['value']!r} with status {o['status']} ({key})")
        if o["value"] != "" and float(o["value"]) < 0 and o["unit"] != "percent":
            fail(f"negative value ({key})")
        if o["table_key"] in ("ix_output", "ix_input", "ix_products") and not re.fullmatch(r"|M(0[1-9]|1[0-2])", o["qualifier"]):
            fail(f"qualifier {o['qualifier']!r} is not a month ({key})")
        if o["variable"] == "price_index" and o["status"] == "ok" and float(o["value"]) <= 0:
            fail(f"an index of {o['value']} ({key}): a zero of the source means missing")
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

    for year, variable, part, minus, expected, tolerance, source in RATIO_ANCHORS:
        def one(product):
            o = by_key.get(("fs_employment", str(year), "EL", product, variable, ""))
            return float(o["value"]) if o and o["status"] == "ok" else None
        whole = one("fs_employment.synolo")
        numerator = one(part)
        parts = [one(m) for m in minus]
        if whole is None or numerator is None or None in parts:
            fail(f"{part} {year}: the figures for the ratio are missing ({source})")
        else:
            got = numerator / (whole - sum(parts)) * 100
            if abs(got - expected) > tolerance:
                fail(f"{part} {year} {variable}: found {got:.2f}%, expected {expected}% ({source})")

    for table, product, month, year, expected, tolerance, source in YEAR_ON_YEAR:
        now = by_key.get((table, str(year), "EL", product, "price_index", month))
        before = by_key.get((table, str(year - 1), "EL", product, "price_index", month))
        if not now or not before or now["status"] != "ok" or before["status"] != "ok":
            fail(f"{product} {month} {year}: the index values are missing ({source})")
        else:
            got = (float(now["value"]) / float(before["value"]) - 1) * 100
            if abs(got - expected) > tolerance:
                fail(f"{product} {month} {year}: found {got:.2f}%, expected {expected}% ({source})")

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
          f"{len(ANCHORS) + len(RATIO_ANCHORS) + len(YEAR_ON_YEAR)} anchor values agree with the ELSTAT press releases.")


if __name__ == "__main__":
    main()
