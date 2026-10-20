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
import agri_accounts  # noqa: E402
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
    "economy": {
        "html": ROOT / "agrifood" / "economy" / "index.html", "datasets": ["SEL61"],
        "levels": ("country", "region", "zone"), "map": MAP_KEYS[:3] + ("zones",),
        "categories": [(t, agri_accounts.CATEGORIES[t]) for t in ("eaa_output", "eaa_income", "eaa_crops", "eaa_livestock")], "variables": None,
    },
    "employment": {
        "html": ROOT / "agrifood" / "employment" / "index.html", "datasets": ["SPG12"],
        "levels": ("country", "region", "unit", "prefecture"), "map": MAP_KEYS + ("prefectures",),
        "categories": [(t, agri_survey.CATEGORIES[t]) for t in ("fs_employment", "fs_employment_family", "fs_holder_age", "fs_holder_sex")], "variables": None,
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


PRICES_HTML = ROOT / "agrifood" / "prices" / "index.html"
PRICES_BLOCK = re.compile(r'(<script id="agri-prices" type="application/json">)(.*?)(</script>)', re.S)
PRICE_TABLES = ["ix_output", "ix_input", "ix_products", "ix_factors"]


def build_prices():
    """Payload of the national price index page (no geography): items with their annual, monthly, change and weight values.

    tables  [[table_key, name, monthly?], …]
    items   [[product code, table index, name, total?], …]
    data    per item: {"a": {year: annual value}, "m": {year: [12 months, null where missing]}, "c": {year: annual change %}, "w": {year: weight}}
    tab     {table_key: {year: [edition, document id, stage, publication date, "", last update]}}
    """
    datasets = {"DKT30", "DKT33"}
    products = [p for p in read("agri_products.csv") if p["dataset"] in datasets]
    names = {"ix_output": "Εκροές (μηνιαίοι δείκτες)", "ix_input": "Εισροές (μηνιαίοι δείκτες)",
             "ix_products": "Μερικά προϊόντα εκροών (ετήσιοι δείκτες)", "ix_factors": "Αμοιβή συντελεστών παραγωγής (ετήσιοι δείκτες)"}
    tables = [t for t in PRICE_TABLES if any(p["table_key"] == t for p in products)]
    products.sort(key=lambda p: (tables.index(p["table_key"]), -int(p["is_total"]), p["product_code"] if p["table_key"] != "ix_factors" else str(["general", "labour", "land", "capital", "interest", "machinery"].index(p["product_code"].split(".")[1]))))
    index = {p["product_code"]: i for i, p in enumerate(products)}
    data = [{"a": {}, "m": {}, "c": {}, "w": {}} for _ in products]
    updated, units = {}, set()
    observations = [o for o in read("agri_observations.csv") if o["dataset"] in datasets]
    for o in observations:
        item = data[index[o["product_code"]]]
        y = o["ref_year"]
        units.add(o["unit"])
        value = number(o["value"]) if o["status"] == "ok" else None
        if o["variable"] == "price_index" and o["qualifier"]:
            item["m"].setdefault(y, [None] * 12)[int(o["qualifier"][1:]) - 1] = value
        else:
            item[{"price_index": "a", "annual_change": "c", "weight": "w"}[o["variable"]]][y] = value
        updated[(o["table_key"], y)] = max(updated.get((o["table_key"], y), ""), o["last_updated"])
    tab = defaultdict(dict)
    for p in read("agri_publications.csv"):
        if p["dataset"] in datasets:
            tab[p["table_key"]][p["ref_year"]] = [int(p["edition"]), p["doc_id"], p["stage"], p["publication_date"], p["dataset"], updated.get((p["table_key"], p["ref_year"]), "")]
    issues = sorted([i["dataset"], i["severity"], i["code"], i["message"]] for i in read("agri_import_issues.csv")
                    if i["dataset"] in datasets and i["code"] in ("skipped_sheet", "source_note"))
    seen, notes = set(), []
    for row in issues:
        if row[3] not in seen and re.search("[Ͱ-Ͽ]", row[3]):  # the notes of the ELSTAT sheets; the importer's own notes are in English
            seen.add(row[3])
            notes.append(row)
    payload = {"meta": {"datasets": sorted(datasets), "statistics": len(observations), "updated": max(updated.values()),
                        "units": sorted(units)},
               "tables": [[t, names[t], int(t in ("ix_output", "ix_input"))] for t in tables],
               "items": [[p["product_code"], tables.index(p["table_key"]), p["name_el"], int(p["is_total"] == "1")] for p in products],
               "data": data, "tab": tab, "notes": notes}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


PROFILE_HTML = ROOT / "agrifood" / "regional-profile" / "index.html"
PROFILE_BLOCK = re.compile(r'(<script id="agri-profile" type="application/json">)(.*?)(</script>)', re.S)
REGION_CODES = ["EL51", "EL52", "EL53", "EL54", "EL61", "EL62", "EL63", "EL64", "EL65", "EL30", "EL41", "EL42", "EL43"]
# (group, label, table, product, variable, unit label, kind) kind: amount (additive across regions: share of the country is shown), ratio
PROFILE_ROWS = [
    ("land", "Γεωργική γη και αγρανάπαυση", "land_use", "land_use.synolo", "area", "στρέμματα", "amount"),
    ("land", "Αρδευόμενες εκτάσεις", "irrigated", "irrigated.synolo", "area", "στρέμματα", "amount"),
    ("land", "Ελιές (έκταση)", "tree_areas", "tree_areas.elies", "area", "στρέμματα", "amount"),
    ("land", "Ελαιόλαδο (παραγωγή)", "secondary", "secondary.elaiolado", "production", "τόνοι", "amount"),
    ("holdings", "Εκμεταλλεύσεις (σύνολο)", "fs_farm_types", "fs_farm_types.synolo", "holdings", "εκμεταλλεύσεις", "amount"),
    ("holdings", "Χρησιμοποιούμενη γεωργική έκταση", "fs_land_use", "fs_land_use.chrisimopoioymeni_georgiki_ektasi", "area", "στρέμματα", "amount"),
    ("holdings", "Εκμεταλλεύσεις με ζώα", "fs_livestock_units", "fs_livestock_units.synolo", "holdings", "εκμεταλλεύσεις", "amount"),
    ("holdings", "Ζωικές μονάδες", "fs_livestock_units", "fs_livestock_units.synolo", "livestock_units", "ζωικές μονάδες", "amount"),
    ("livestock", "Πρόβατα (σύνολο)", "lv_stock", "lv_stock.provata.synolo", "animals", "κεφάλια", "amount"),
    ("livestock", "Αίγες (σύνολο)", "lv_stock", "lv_stock.aiges.synolo", "animals", "κεφάλια", "amount"),
    ("livestock", "Χοίροι (σύνολο)", "lv_stock", "lv_stock.choiroi.synolo", "animals", "κεφάλια", "amount"),
    ("livestock", "Βοοειδή (γενικό σύνολο)", "lv_stock", "lv_stock.moscharia_vodia_tayroi_damalia_kai_agelades.geniko_synolo", "animals", "κεφάλια", "amount"),
    ("livestock", "Όρνιθες συστηματικών πτηνοτροφείων", "lv_stock", "lv_stock.ornithes.systimatikon_ptinotrofeion", "animals", "κεφάλια", "amount"),
    ("livestock", "Κυψέλες μελισσών (ευρωπαϊκές)", "lv_stock", "lv_stock.kypseles_melisson.eyropaikes", "hives", "κυψέλες", "amount"),
    ("livestock", "Γάλα (γενικό σύνολο)", "lv_milk", "lv_milk.geniko_synolo_galaktos", "production", "τόνοι", "amount"),
    ("employment", "Απασχολούμενοι (σύνολο)", "fs_employment", "fs_employment.synolo", "persons", "πρόσωπα", "amount"),
    ("employment", "Ημέρες εργασίας (σύνολο)", "fs_employment", "fs_employment.synolo", "workdays", "ημέρες εργασίας", "amount"),
    ("economy", "Γεωργική παραγωγή (16)", "eaa_output", "eaa_output.i16", "amount", "εκατ. ευρώ", "amount"),
    ("economy", "Φυτική παραγωγή (10)", "eaa_crops", "eaa_crops.i10", "amount", "εκατ. ευρώ", "amount"),
    ("economy", "Ζωική παραγωγή (13)", "eaa_livestock", "eaa_livestock.i13", "amount", "εκατ. ευρώ", "amount"),
    ("economy", "Καθαρή προστιθέμενη αξία (22)", "eaa_income", "eaa_income.i22", "amount", "εκατ. ευρώ", "amount"),
    ("economy", "Επιχειρηματικό εισόδημα (31)", "eaa_income", "eaa_income.i31", "amount", "εκατ. ευρώ", "amount"),
]
# derived rows: (group, label, numerator row label, denominator row label, unit label, multiplier)
PROFILE_RATIOS = [
    ("holdings", "Μέση έκταση ανά εκμετάλλευση", "Χρησιμοποιούμενη γεωργική έκταση", "Εκμεταλλεύσεις (σύνολο)", "στρέμματα ανά εκμετάλλευση", 1),
    ("land", "Αρδευόμενες εκτάσεις ως ποσοστό της γεωργικής γης", "Αρδευόμενες εκτάσεις", "Γεωργική γη και αγρανάπαυση", "%", 100),
    ("economy", "Ζωική παραγωγή ως ποσοστό της γεωργικής παραγωγής", "Ζωική παραγωγή (13)", "Γεωργική παραγωγή (16)", "%", 100),
]
PROFILE_GROUPS = [
    ("land", "Γη και καλλιέργειες", "SPG06"), ("holdings", "Εκμεταλλεύσεις", "SPG32"), ("livestock", "Κτηνοτροφία", "SPK33"),
    ("employment", "Απασχόληση", "SPG12"), ("economy", "Οικονομικοί λογαριασμοί γεωργίας", "SEL61"),
]


def build_profile():
    """Payload of the regional profile page: a snapshot per region from the latest year of every source, each row with its
    own source, year and stage. Nothing is combined across sources except the explicit ratios, which stay inside one source."""
    obs = {}
    flagged = set()
    for o in read("agri_observations.csv"):
        if o["status"] == "ok" and o["geo_code"] in ["EL"] + REGION_CODES and o["qualifier"] == "":
            k = (o["table_key"], o["ref_year"], o["geo_code"], o["product_code"], o["variable"])
            obs[k] = float(o["value"])
            if "total_differs_from_parts" in o["flags"].split(";") and o["geo_code"] == "EL":
                flagged.add(k[:2] + k[3:])
    pubs = {(p["table_key"], p["ref_year"]): p for p in read("agri_publications.csv")}
    products = {p["product_code"]: p for p in read("agri_products.csv")}
    geos = ["EL"] + REGION_CODES

    def latest(table, product, variable):
        years = sorted({k[1] for k in obs if k[0] == table and k[2] == "EL" and k[3] == product and k[4] == variable
                        and (table, k[1], product, variable) not in flagged}, reverse=True)
        return years[0] if years else None

    rows, by_label = [], {}
    for group, label, table, product, variable, unit, kind in PROFILE_ROWS:
        year = latest(table, product, variable)
        pub = pubs.get((table, year)) if year else None
        row = {"group": group, "label": label, "unit": unit, "kind": kind, "year": int(year) if year else None,
               "src": pub["dataset"] if pub else "", "stage": pub["stage"] if pub else "", "pub": pub["publication_date"] if pub else "", "table": table,
               "code": product, "derived": False, "values": {g: obs.get((table, year, g, product, variable)) for g in geos} if year else {}}
        rows.append(row)
        by_label[label] = row
    for group, label, num, den, unit, mult in PROFILE_RATIOS:
        a, b = by_label[num], by_label[den]
        if a["year"] != b["year"] or a["src"] != b["src"]:
            continue
        values = {g: (a["values"][g] / b["values"][g] * mult if a["values"].get(g) is not None and b["values"].get(g) else None) for g in geos}
        rows.append({"group": group, "label": label, "unit": unit, "kind": "ratio", "year": a["year"], "src": a["src"], "stage": a["stage"], "pub": a["pub"],
                     "table": a["table"], "code": "", "derived": True, "values": values})
    # employment: women among the holders (the codes differ with the survey's wording, the holders do not)
    for year in ("2023", "2016"):
        root = "katochoi_kai_meli_tis_oikogeneias_toys" if year == "2023" else "katochoi_kai_meli_toy_noikokyrioy_toys"
        w, t = f"fs_holder_sex.{root}.gynaikes.katochoi", f"fs_holder_sex.{root}.synolo.katochoi"
        if all(("fs_holder_sex", year, "EL", c, "persons") in obs for c in (w, t)):
            pub = pubs[("fs_holder_sex", year)]
            rows.append({"group": "employment", "label": "Γυναίκες ανάμεσα στους κατόχους εκμεταλλεύσεων", "unit": "%", "kind": "ratio", "year": int(year),
                         "src": pub["dataset"], "stage": pub["stage"], "pub": pub["publication_date"], "table": "fs_holder_sex", "code": "", "derived": True,
                         "values": {g: (obs[("fs_holder_sex", year, g, w, "persons")] / obs[("fs_holder_sex", year, g, t, "persons")] * 100
                                        if ("fs_holder_sex", year, g, w, "persons") in obs and obs.get(("fs_holder_sex", year, g, t, "persons")) else None) for g in geos}})
            break
    # crops: the largest non-total, non-residual areas of the country in the latest year of the annual survey
    ay = max(y for (t, y, g, c, v) in obs if t == "land_use")
    crop_tables = ("cereals", "pulses_edible", "industrial", "vegetables", "melons_potatoes", "vineyards", "tree_areas")
    crops = []
    for (t, y, g, c, v), x in obs.items():
        if y == ay and g == "EL" and v == "area" and t in crop_tables and products[c]["is_total"] == "0" and products[c]["is_residual"] == "0" and x > 0:
            crops.append((x, c))
    crops = [c for _x, c in sorted(crops, reverse=True)[:18]]
    crop_rows = [{"name": products[c]["name_el"], "values": {g: obs.get((c.split(".")[0], ay, g, c, "area")) for g in geos}} for c in crops]
    land_codes = [("land_use.kalliergeies.arotraies", "Αροτραίες καλλιέργειες"), ("land_use.kalliergeies.dendrodeis", "Δενδρώδεις καλλιέργειες"),
                  ("land_use.kalliergeies.ampelia_kai_stafidampela", "Αμπέλια και σταφιδάμπελα"), ("land_use.kalliergeies.kipeytiki_gi", "Κηπευτική γη"),
                  ("land_use.agranapaysi", "Αγρανάπαυση")]
    land = [{"name": n, "values": {g: obs.get(("land_use", ay, g, c, "area")) for g in geos}} for c, n in land_codes]
    land_total = {g: obs.get(("land_use", ay, g, "land_use.synolo", "area")) for g in geos}
    pub = pubs[("land_use", ay)]
    # trend of the output of the agricultural industry
    sy = sorted({k[1] for k in obs if k[0] == "eaa_output" and k[2] == "EL" and k[3] == "eaa_output.i16"})
    trend = {"years": [int(y) for y in sy], "break": 2010, "unit": "εκατ. ευρώ", "label": "Γεωργική παραγωγή (16)",
             "series": {g: [obs.get(("eaa_output", y, g, "eaa_output.i16", "amount")) for y in sy] for g in geos}}
    # context from the other datasets of the platform (their own sources and definitions)
    context = []
    census = {r["nuts2"]: int(r["total"]) for r in csv.DictReader((ROOT / "data" / "census_2021_population_by_area.csv").open(encoding="utf-8")) if r["level"] == "region"}
    census["EL"] = next(int(r["total"]) for r in csv.DictReader((ROOT / "data" / "census_2021_population_by_area.csv").open(encoding="utf-8")) if r["level"] == "country")
    context.append({"label": "Πληθυσμός (Απογραφή 2021)", "unit": "κάτοικοι", "year": 2021, "src": "ΕΛΣΤΑΤ · Απογραφή Πληθυσμού 2021", "kind": "amount",
                    "values": {g: census.get(g) for g in geos}})
    gva = {}
    for r in csv.DictReader((ROOT / "data" / "economy_eurostat_gva_by_sector.csv").open(encoding="utf-8")):
        gva[(r["year"], r["nuts2"], r["sector_code"])] = float(r["gva_meur"])
    gy = max(y for (y, _g, _s) in gva)
    context.append({"label": "Ακαθάριστη προστιθέμενη αξία: γεωργία, δασοκομία, αλιεία", "unit": "εκατ. ευρώ", "year": int(gy), "src": "Eurostat · ΑΠΑ ανά κλάδο (NUTS 2)", "kind": "amount",
                    "values": {g: gva.get((gy, g, "A")) for g in geos}})
    context.append({"label": "Μερίδιο γεωργίας, δασοκομίας και αλιείας στη συνολική ΑΠΑ", "unit": "%", "year": int(gy), "src": "Eurostat · ΑΠΑ ανά κλάδο (NUTS 2)", "kind": "ratio",
                    "values": {g: (gva[(gy, g, "A")] / gva[(gy, g, "TOTAL")] * 100 if (gy, g, "A") in gva and gva.get((gy, g, "TOTAL")) else None) for g in geos}})
    names = {g[0]: g[2] for g in [(r["geo_code"], r["level"], r["name_el"]) for r in read("agri_geo.csv")]}
    payload = {"meta": {"geos": geos},
               "regions": [[g, names[g]] for g in REGION_CODES], "groups": [[g, t, d] for g, t, d in PROFILE_GROUPS],
               "rows": rows, "crops": {"year": int(ay), "src": "SPG06", "stage": pub["stage"], "pub": pub["publication_date"], "rows": crop_rows},
               "land": {"year": int(ay), "src": "SPG06", "stage": pub["stage"], "pub": pub["publication_date"], "rows": land, "total": land_total},
               "trend": trend, "context": context}
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
    if PROFILE_HTML.exists():
        document = PROFILE_HTML.read_text(encoding="utf-8")
        blocks = [(PROFILE_BLOCK, build_profile(), "agri-profile"), (GEO_BLOCK, geometry({"map": MAP_KEYS[:3]}), "agri-geo")]
        for pattern, generated, block in blocks:
            match = pattern.search(document)
            if not match:
                sys.exit(f"no {block} block found in {PROFILE_HTML}")
            if check:
                if match.group(2).strip() != generated:
                    sys.exit(f"{block} in {PROFILE_HTML.relative_to(ROOT)} is out of date with the CSV files; run scripts/build_agriculture_data.py")
            else:
                document = document[:match.start(2)] + generated + document[match.end(2):]
                match = None
        if check:
            print(f"OK: regional-profile: data in the page matches the CSVs ({len(blocks[0][1]):,} characters).")
        else:
            PROFILE_HTML.write_text(document, encoding="utf-8")
            print(f"regional-profile: wrote {len(blocks[0][1]):,} characters of data into {PROFILE_HTML.relative_to(ROOT)}")
    if PRICES_HTML.exists():
        document = PRICES_HTML.read_text(encoding="utf-8")
        generated = build_prices()
        match = PRICES_BLOCK.search(document)
        if not match:
            sys.exit(f"no agri-prices block found in {PRICES_HTML}")
        if check:
            if match.group(2).strip() != generated:
                sys.exit(f"agri-prices in {PRICES_HTML.relative_to(ROOT)} is out of date with the CSV files; run scripts/build_agriculture_data.py")
            print(f"OK: prices: data in the dashboard matches the CSVs ({len(generated):,} characters).")
        else:
            PRICES_HTML.write_text(document[:match.start(2)] + generated + document[match.end(2):], encoding="utf-8")
            print(f"prices: wrote {len(generated):,} characters of data into {PRICES_HTML.relative_to(ROOT)}")
    sys.exit(status)


if __name__ == "__main__":
    main()
