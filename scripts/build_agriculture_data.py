#!/usr/bin/env python3
"""Generate the embedded data of the agriculture dashboards from the CSV tables in data/agriculture/.

Usage:
    python3 scripts/build_agriculture_data.py           # rewrite the data blocks of every dashboard page (PAGES below)
    python3 scripts/build_agriculture_data.py --check   # verify the pages and the CSV files agree, change nothing

The CSV files (see scripts/import_agriculture_data.py) are the source of truth. Two
<script type="application/json"> blocks of each dashboard page are generated: "agri-data" with the statistics of the
publications the page shows, in the compact layout described below, and "agri-geo" with the map geometries
(data/agriculture/geo/greece_units.json).

agri-data layout (indexes refer to the arrays of the same document):
    geo     [[geo_code, level, name, parent_code], …]             country, regions, regional units (and prefectures)
    cats    [[table_key, name], …]                                 categories (the tables of the source)
    prods   [[code, cat index, name, subcategory, kind, continues, breaks, name_en], …]
            kind: 1 total of its group, 2 residual ("Λοιπά"); continues: index of the product it continues or -1
    vars    [[variable, label, unit code, unit label], …]
    series  [[product index, variable index, qualifier], …]
    years   reference years
    vals    per series, per year: null (no data in that year) or one number per geo entry; -1 is a dash of the
            source (published as "—"), null inside the list is a cell the source left empty or combined with another
    tab     {table_key: {year: [edition (ELSTAT page year), document id, stage, publication date, source table, last update]}}
    flags   [[series index, year index, geo index, flag], …]        cells with a caveat (see data/README.md)
    issues  [[table_key, reference year, severity, code, message], …]
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agri_livestock  # noqa: E402
import agri_survey  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "agriculture"
GEO_JSON = DATA / "geo" / "greece_units.json"
DATA_BLOCK = re.compile(r'(<script id="agri-data" type="application/json">)(.*?)(</script>)', re.S)
GEO_BLOCK = re.compile(r'(<script id="agri-geo" type="application/json">)(.*?)(</script>)', re.S)
PLANT_CATEGORIES = [
    ("land_use", "Χρήση γεωργικής γης"), ("cereals", "Σιτηρά"), ("pulses_edible", "Βρώσιμα όσπρια"), ("industrial", "Βιομηχανικά φυτά"),
    ("vegetables", "Λαχανικά"), ("melons_potatoes", "Πεπονοειδή και πατάτες"), ("vineyards", "Αμπέλια και σταφιδάμπελα"),
    ("tree_areas", "Δενδρώδεις καλλιέργειες: εκτάσεις"), ("trees", "Δενδρώδεις καλλιέργειες: δένδρα και παραγωγή"),
    ("secondary", "Ελαιόλαδο και μούστος"), ("irrigated", "Ποτιστικές εκτάσεις"), ("horticulture", "Κηπευτική γη και καλλωπιστικά"),
    ("pulses_fodder", "Κτηνοτροφικά όσπρια"), ("fodder_hay", "Κτηνοτροφικά φυτά για σανό"),
    ("fodder_green", "Κτηνοτροφικά φυτά για χλωρό χόρτο"), ("fodder_grazing", "Κτηνοτροφικά φυτά για βοσκή"),
]
PLANT_VARIABLES = {"area": "Έκταση", "production": "Παραγωγή", "trees_total": "Δένδρα (σύνολο)", "trees_regular": "Δένδρα κανονικών δενδρώνων"}
SURVEY_TABLES = ["fs_farm_types", "fs_land_use", "fs_arable", "fs_cereals", "fs_tree_crops", "fs_vineyards", "fs_irrigation",
                 "fs_livestock", "fs_livestock_units", "fs_organic_livestock"]
LIVESTOCK_TABLES = ["lv_stock", "lv_births", "lv_breeding", "lv_milked", "lv_milk", "lv_meat", "lv_other", "lv_secondary"]
MAP_KEYS = ("source", "viewBox", "regions", "units")
PAGES = {
    "plant-production": {
        "html": ROOT / "agrifood" / "plant-production" / "index.html", "datasets": ["SPG06"],
        "levels": ("country", "region", "unit"), "map": MAP_KEYS, "categories": PLANT_CATEGORIES, "variables": PLANT_VARIABLES,
    },
    "holdings": {
        "html": ROOT / "agrifood" / "holdings" / "index.html", "datasets": ["SPG32", "SPK12"],
        "levels": ("country", "region", "unit", "prefecture"), "map": MAP_KEYS + ("prefectures",),
        "categories": [(t, agri_survey.CATEGORIES[t]) for t in SURVEY_TABLES], "variables": None,
    },
    "livestock": {
        "html": ROOT / "agrifood" / "livestock" / "index.html", "datasets": ["SPK33"],
        "levels": ("country", "region", "unit"), "map": MAP_KEYS,
        "categories": [(t, agri_livestock.CATEGORIES[t]) for t in LIVESTOCK_TABLES], "variables": None,
    },
}


def read(name):
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(text):
    value = float(text)
    return int(value) if value.is_integer() else value


def build(page):
    datasets = set(page["datasets"])
    geo_rows = [g for g in read("agri_geo.csv") if g["level"] in page["levels"]]
    geo_index = {g["geo_code"]: i for i, g in enumerate(geo_rows)}
    geo = [[g["geo_code"], g["level"], g["name_el"], g["parent_code"]] for g in geo_rows]

    products = [p for p in read("agri_products.csv") if p["dataset"] in datasets]
    names = dict(page["categories"])
    tables = [t for t, _ in page["categories"] if any(p["table_key"] == t for p in products)]
    cats = [[t, names[t]] for t in tables]
    products.sort(key=lambda p: (tables.index(p["table_key"]), -int(p["is_total"]), p["path"]))
    prod_index = {p["product_code"]: i for i, p in enumerate(products)}

    def kind(p):
        return 1 if p["is_total"] == "1" else 2 if p["is_residual"] == "1" else 0

    prods = [[p["product_code"], tables.index(p["table_key"]), p["name_el"], p["subcategory"], kind(p),
              prod_index.get(p["continues"], -1), [int(y) for y in p["series_breaks"].split(";") if y], p["name_en"]]
             for p in products]

    observations = [o for o in read("agri_observations.csv") if o["dataset"] in datasets]
    registry = {v["variable"]: v for v in read("agri_variables.csv")}
    present = {o["variable"] for o in observations}
    variables = [v for v in (page["variables"] or registry) if v in present]
    labels = page["variables"] or {v: registry[v]["label_el"] for v in variables}
    vars_ = [[v, labels[v], registry[v]["unit"], registry[v]["unit_label_el"]] for v in variables]

    years = sorted({int(o["ref_year"]) for o in observations})
    year_index = {y: i for i, y in enumerate(years)}
    series_keys = sorted({(o["product_code"], o["variable"], o["qualifier"]) for o in observations},
                         key=lambda k: (prod_index[k[0]], variables.index(k[1]), k[2]))
    series_index = {k: i for i, k in enumerate(series_keys)}
    series = [[prod_index[k[0]], variables.index(k[1]), k[2]] for k in series_keys]
    vals = [[None] * len(years) for _ in series]
    flags = []
    tab = defaultdict(dict)
    updated = {}
    for o in observations:
        s, y, g = series_index[(o["product_code"], o["variable"], o["qualifier"])], year_index[int(o["ref_year"])], geo_index[o["geo_code"]]
        if vals[s][y] is None:
            vals[s][y] = [None] * len(geo)
        if o["status"] == "ok":
            vals[s][y][g] = number(o["value"])
        elif o["status"] == "dash":
            vals[s][y][g] = -1
        else:
            flags.append([s, y, g, o["status"]])
        for flag in filter(None, o["flags"].split(";")):
            flags.append([s, y, g, flag])
        key = (o["table_key"], o["ref_year"])
        updated[key] = max(updated.get(key, ""), o["last_updated"])
    publications = {(p["table_key"], p["ref_year"]): p for p in read("agri_publications.csv") if p["dataset"] in datasets}
    source_of = {}
    for (table, year), p in publications.items():
        tab[table][year] = [int(p["edition"]), p["doc_id"], p["stage"], p["publication_date"], p["source_table"], updated.get((table, year), "")]
        source_of[table] = p["dataset"]
    flags.sort()

    docs = {(p["doc_id"], p["sheet"]): (p["table_key"], p["ref_year"]) for p in publications.values()}
    doc_tables = defaultdict(list)
    for (doc, sheet), key in docs.items():
        doc_tables[doc].append((sheet, key))
    issues = []
    for i in read("agri_import_issues.csv"):
        if i["dataset"] not in datasets or (i["severity"] == "info" and i["code"] == "label_inherited"):
            continue
        targets = [key for sheet, key in doc_tables.get(i["doc_id"], []) if not i["sheet"] or sheet == i["sheet"]]
        for table, year in targets or [("", "")]:
            if table:
                issues.append([table, int(year), i["severity"], i["code"], i["message"]])
    issues.sort()
    payload = {"meta": {"datasets": sorted(datasets), "source_of": source_of, "statistics": len(observations), "updated": max(updated.values())},
               "geo": geo, "cats": cats, "prods": prods, "vars": vars_, "series": series, "years": years,
               "vals": vals, "tab": tab, "flags": flags, "issues": issues}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def geometry(page):
    full = json.loads(GEO_JSON.read_text(encoding="utf-8"))
    return json.dumps({k: full[k] for k in page["map"]}, ensure_ascii=False, separators=(",", ":"))


def main():
    check = "--check" in sys.argv
    status = 0
    for name, page in PAGES.items():
        html = page["html"]
        if not html.exists():
            continue
        document = html.read_text(encoding="utf-8")
        blocks = [(DATA_BLOCK, build(page), "agri-data"), (GEO_BLOCK, geometry(page), "agri-geo")]
        for pattern, _, block in blocks:
            if not pattern.search(document):
                sys.exit(f"no {block} block found in {html}")
        if check:
            for pattern, generated, block in blocks:
                if pattern.search(document).group(2).strip() != generated:
                    sys.exit(f"{block} in {html.relative_to(ROOT)} is out of date with the CSV files; run scripts/build_agriculture_data.py")
            print(f"OK: {name}: data in the dashboard matches the CSVs ({len(blocks[0][1]):,} + {len(blocks[1][1]):,} characters).")
            continue
        for pattern, generated, _ in blocks:
            match = pattern.search(document)
            document = document[:match.start(2)] + generated + document[match.end(2):]
        html.write_text(document, encoding="utf-8")
        print(f"{name}: wrote {len(blocks[0][1]):,} + {len(blocks[1][1]):,} characters of data into {html.relative_to(ROOT)}")
    sys.exit(status)


if __name__ == "__main__":
    main()
