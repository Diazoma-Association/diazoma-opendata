"""Parser for the ELSTAT regional economic accounts for agriculture (SEL61, 1995-2023).

One workbook per reference year, one sheet ("Βασικές Τιμές"), in millions of euro. Rows are the items of the
European economic accounts for agriculture (output by product, intermediate consumption, value added, income; the
code of an item is its position in the account, e.g. 01.11 soft wheat) and columns are the country, the four
geographic zones (NUTS 1) and the thirteen regions (NUTS 2): the opposite orientation to the survey tables, so the
parser turns the sheet around: every item becomes a column of the table (a product) and every area a row.

The items are split into four tables of the platform (crop output, livestock output, output of the sector, account
from intermediate consumption to entrepreneurial income). Values are published unrounded (1052.9299999999998); they
are stored with three decimals, i.e. to the thousand euro.

Provisional years are marked with an asterisk after the year ("Ετος 2022*"). The sheet says when it was updated
("Ενημέρωση, Νοέμβριος 2024" or "Ενημέρωση 15/11/2016"), which is the only publication date available.
"""

import re

import agri_geo
from agri_spg06 import LayoutError, fold, parse_cell, slug
from agri_xlsx import clean, load

TABLE_KEYS = {"eaa_crops": "Φυτική παραγωγή ανά προϊόν", "eaa_livestock": "Ζωική παραγωγή ανά προϊόν",
              "eaa_output": "Παραγωγή του γεωργικού κλάδου", "eaa_income": "Λογαριασμός: από την ενδιάμεση ανάλωση στο εισόδημα"}
CATEGORIES = dict(TABLE_KEYS)
UNIT = "eur_million"
LOOKALIKE = str.maketrans("ABEHIKMNOPTXYZ", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖ")
# Column headings -> geography. The labels are not the official names ("Ανατολική Μακεδονία, Θράκη").
COLUMNS = {
    "συνολο ελλαδοσ": "EL", "αττικη": "EL30", "νησια αιγαιου, κρητη": "EL4", "βορειο αιγαιο": "EL41", "νοτιο αιγαιο": "EL42",
    "κρητη": "EL43", "βορεια ελλαδα": "EL5", "ανατολικη μακεδονια, θρακη": "EL51", "κεντρικη μακεδονια": "EL52",
    "δυτικη μακεδονια": "EL53", "ηπειρος": "EL54", "κεντρικη ελλαδα": "EL6", "θεσσαλια": "EL61", "ιονια νησια": "EL62",
    "δυτικη ελλαδα": "EL63", "στερεα ελλαδα": "EL64", "πελοποννησος": "EL65",
}
COLUMNS = {fold(k): v for k, v in COLUMNS.items()}
LEVEL = {"EL": "country", "EL4": "zone", "EL5": "zone", "EL6": "zone"}
CODE = re.compile(r"^(\d{2})(?:\.(\d{1,2}))?$")
UPDATE = re.compile(r"Ενημέρωση[,\s]*(?:(\d{1,2})/(\d{1,2})/(\d{4})|(\w+)\s+(\d{4}))")
MONTHS = {"Ιανουάριος": 1, "Φεβρουάριος": 2, "Μάρτιος": 3, "Απρίλιος": 4, "Μάιος": 5, "Ιούνιος": 6, "Ιούλιος": 7, "Αύγουστος": 8,
          "Σεπτέμβριος": 9, "Οκτώβριος": 10, "Νοέμβριος": 11, "Δεκέμβριος": 12}
# Formula of the totals, in the source's own names: "ΦΥΤΙΚΗ ΠΑΡΑΓΩΓΗ (1 ΕΩΣ 9)", "ΖΩΙΚΗ ΠΑΡΑΓΩΓΗ (11+12)", "… (22-24+25)".
FORMULA = re.compile(r"\((\d{1,2}(?:\s*[+-]\s*\d{1,2})+|\d{1,2} ΕΩΣ \d{1,2})\)\s*$")


def group_of(code):
    n = int(code[:2])
    return "eaa_crops" if n <= 10 else "eaa_livestock" if n <= 13 else "eaa_output" if n <= 18 else "eaa_income"


def geo_of(label):
    return COLUMNS.get(fold(label.translate(LOOKALIKE)).replace("  ", " "))


def update_date(text):
    m = UPDATE.search(text)
    if not m:
        return ""
    if m.group(1):
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    month = next((n for name, n in MONTHS.items() if fold(name) == fold(m.group(4))), None)
    return f"{int(m.group(5)):04d}-{month:02d}" if month else ""


def parse_sheet(sheet, edition):
    header = next((r for r in range(min(sheet.nrows, 15)) if sheet.text(r, 0).startswith("ΚΑΤΗΓΟΡΙΕΣ")), None)
    if header is None:
        return None
    lines = [sheet.text(r, 0) for r in range(header) if sheet.text(r, 0)]
    title = " ".join(lines)
    name = next((t for t in lines if t.startswith("Οικονομικοί")), "")
    year_label = next((t for t in lines if t.startswith("Ετος")), "")
    year = re.search(r"Ετος\s+(\d{4})", year_label)
    if not year:
        raise LayoutError("no reference year (Ετος …)")
    ref_year = int(year.group(1))
    if "εκατομμυρια ευρω" not in fold(title):
        raise LayoutError(f"the unit line does not say millions of euro: {title!r}")
    columns = {}
    for c in range(2, sheet.ncols):
        label = sheet.text(header, c)
        if not label:
            continue
        code = geo_of(label)
        if code is None:
            raise LayoutError(f"unknown area in the header: {label!r}")
        columns[c] = code
    if len(columns) != len(COLUMNS) or set(columns.values()) != set(COLUMNS.values()):
        raise LayoutError(f"expected {len(COLUMNS)} areas, found {sorted(set(COLUMNS.values()) - set(columns.values()))} missing")

    items, notes = [], []
    for r in range(header + 1, sheet.nrows):
        code, name = sheet.text(r, 0), sheet.text(r, 1)
        if CODE.match(code) and name:
            items.append((r, code, name))
        elif name and not code:
            notes.append(name)
    tables = []
    for key in TABLE_KEYS:
        group = [(r, code, name) for r, code, name in items if group_of(code) == key]
        if not group:
            continue
        specs = []
        for i, (r, code, name) in enumerate(group):
            label = code + " " + " ".join(name.split())
            specs.append({"col": i, "row": r, "path": [label], "path_en": [], "marker": None, "notes": [], "measure": "amount",
                          "unit": UNIT, "qualifier": "", "product_path": [label], "source_path": [label],
                          "product_code": f"{key}.i{code.replace('.', '_')}", "is_total": "." not in code, "name_en": "", "item": code,
                          "formula": FORMULA.search(name).group(1) if FORMULA.search(name) else ""})
        rows = []
        for c, geo in columns.items():
            cells = [parse_cell(sheet.get(spec["row"], c)) for spec in specs]
            rows.append({"level": LEVEL.get(geo, "region"), "geo_code": geo, "label": sheet.text(header, c), "cells": cells})
        tables.append({
            "sheet": f"{sheet.name} · {TABLE_KEYS[key]}", "source_table": "", "title": f"{name} · {TABLE_KEYS[key]}",
            "title_en": "", "ref_year": ref_year, "table_key": key, "units": "Σε εκατομμύρια ευρώ", "legend": {}, "columns": specs,
            "rows": rows, "warnings": [], "ref_year_stated": True, "fix": "", "skipped_columns": [],
            "stage": "provisional" if re.search(r"Ετος\s+\d{4}\s*\*", year_label) else "unspecified",
            "update_date": update_date(" ".join(sheet.text(0, c) for c in range(sheet.ncols))), "formula_issues": formula_issues(sheet, header, columns, group), "notes": notes + (
                [f"the year label of the sheet reads «{year_label}»"] if re.search(r"Ετος\s+\d{4}\s*[^\s*]", year_label) else [])})
    if ref_year != edition:
        for t in tables:
            t["fix"] = f"the sheet states the year {ref_year} but belongs to the {edition} publication page; {ref_year} is used"
    return tables


def terms(formula):
    """[(sign, item code)] of a formula as the source prints it: '22-24+25' or '1 ΕΩΣ 9'."""
    m = re.fullmatch(r"(\d{1,2}) ΕΩΣ (\d{1,2})", formula)
    if m:
        return [(1, f"{n:02d}") for n in range(int(m.group(1)), int(m.group(2)) + 1)]
    return [(-1 if sign == "-" else 1, f"{int(n):02d}") for sign, n in re.findall(r"([+-]?)\s*(\d{1,2})", formula)]


def formula_issues(sheet, header, columns, group):
    """Items whose figure differs from the formula the source prints in their own name, per area."""
    values = {}
    for r in range(header + 1, sheet.nrows):
        code = sheet.text(r, 0)
        if CODE.match(code) and "." not in code:
            for c, geo in columns.items():
                status, value = parse_cell(sheet.get(r, c))
                if status == "ok":
                    values[(code, geo)] = value
    issues = []
    for i, (r, code, name) in enumerate(group):
        m = FORMULA.search(name)
        if "." in code or not m:
            continue
        for geo in columns.values():
            parts = [(sign, values.get((n, geo))) for sign, n in terms(m.group(1))]
            if (code, geo) not in values or any(v is None for _, v in parts):
                continue
            expected = sum(sign * v for sign, v in parts)
            if abs(values[(code, geo)] - expected) > max(0.002 * abs(expected), 0.01):
                issues.append({"col": i, "geo": geo, "column": code, "message": f"the formula ({m.group(1)}) gives {expected:g}, the table has {values[(code, geo)]:g}"})
    return issues


def check_sums(table, tolerance=0.002):
    """Published figures that do not follow from the others: country against regions, zones against their regions and,
    for the totals whose formula the source prints, the item against the items of its formula (country column)."""
    issues = list(table.get("formula_issues", []))
    rows = {r["geo_code"]: r for r in table["rows"]}
    specs = table["columns"]
    zones = agri_geo.zone_regions()

    def val(geo, i):
        s, v = rows[geo]["cells"][i] if geo in rows else ("blank", None)
        return v if s == "ok" else None

    def differs(a, b):
        return abs(a - b) > max(tolerance * max(abs(a), abs(b)), 0.01)

    for i, spec in enumerate(specs):
        label = spec["product_path"][0]
        regions = [g for g in rows if rows[g]["level"] == "region"]
        total = val("EL", i)
        parts = [val(g, i) for g in regions]
        if total is not None and all(p is not None for p in parts) and differs(total, sum(parts)):
            issues.append({"col": i, "geo": "EL", "column": label, "message": f"regions add up to {sum(parts):g}, country total is {total:g}"})
        for zone, members in zones.items():
            z, ps = val(zone, i), [val(g, i) for g in members]
            if z is not None and all(p is not None for p in ps) and differs(z, sum(ps)):
                issues.append({"col": i, "geo": zone, "column": label, "message": f"regions add up to {sum(ps):g}, zone total is {z:g}"})
    return issues


def item_formulas(path_table):
    """Not used by the importer; kept for tests: (item code, formula) of the totals of one table."""
    return [(s["item"], s["formula"]) for s in path_table["columns"] if s["formula"]]


def parse_workbook(path, edition):
    """(tables, notes) like agri_spg06.parse_workbook."""
    tables, notes = [], []
    for sheet in load(path):
        try:
            parsed = parse_sheet(sheet, edition)
        except LayoutError as error:
            notes.append({"sheet": sheet.name, "severity": "error", "message": str(error)})
            continue
        tables.extend(parsed or [])
    return tables, notes
