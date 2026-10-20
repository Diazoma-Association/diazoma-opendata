"""Parser for the ELSTAT annual livestock survey tables (SPK33, from 2011).

Every workbook is one table: rows are the country, the regions (NUTS 2) and their regional units, columns are
animals or products. The header has up to five bilingual levels and merged cells; the path of a column is read from
all header levels (Greek part only). What a column counts is decided by the table it belongs to:

    lv_stock      livestock on 31 December (tables 1-4)             head; beehives are counted in hives
    lv_births     animals born during the year (table 5)            head
    lv_breeding   animals that gave birth during the year (6a)      head
    lv_milked     animals milked during the year (6, 6b)            head
    lv_milk       milk production for human consumption (7a)       tonnes
    lv_meat       meat production (7b): animals slaughtered, head, and carcass weight, tonnes
    lv_other      eggs, skins, wool, hair, lard, honey, wax, cocoons (7c): the unit is read from the column
    lv_secondary  cheese, butter, myzithra, cream, … (table 8)     tonnes

A column whose measure cannot be read is reported and left out, never guessed.
"""

import re

import agri_geo
from agri_spg06 import (GREEK, LATIN, LayoutError, _flag_combined, clean_label, dedupe, fold, parse_cell, slug, split_bilingual)
from agri_xlsx import clean, load

COUNTRY = re.compile(r"^Σύνολο (Ελλάδας|Χώρας)", re.I)
TABLE_KEYS = [
    ("ιπποι, ημιονοι", "lv_stock"), ("ιπποι ", "lv_stock"), ("βοδια", "lv_stock"), ("μοσχαρια", "lv_stock"),
    ("προβατα, αιγεσ", "lv_stock"), ("πουλερικα", "lv_stock"),
    ("γεννηθηκαν", "lv_births"), ("γεννησαν", "lv_breeding"), ("αρμεχτηκαν", "lv_milked"),
    ("γαλακτοσ", "lv_milk"), ("κρεατοσ", "lv_meat"), ("λοιπων κτηνοτροφικων", "lv_other"), ("δευτερογενων", "lv_secondary"),
]
CATEGORIES = {
    "lv_stock": "Ζωικό κεφάλαιο (31 Δεκεμβρίου)", "lv_births": "Ζώα που γεννήθηκαν", "lv_breeding": "Ζώα που γέννησαν",
    "lv_milked": "Ζώα που αρμέχτηκαν", "lv_milk": "Γάλα", "lv_meat": "Κρέας", "lv_other": "Λοιπά πρωτογενή προϊόντα",
    "lv_secondary": "Δευτερογενή κτηνοτροφικά προϊόντα",
}
UNIT_OF = {"animals": "head", "hives": "hive", "births": "head", "breeding": "head", "milked": "head", "slaughtered": "head",
           "carcass_weight": "tonne", "production": "tonne", "production_kpieces": "thousand_pieces"}
VARIABLE_OF = {"lv_stock": "animals", "lv_births": "births", "lv_breeding": "breeding", "lv_milked": "milked",
               "lv_milk": "production", "lv_secondary": "production"}
FOOTNOTE_END = re.compile(r"\s*\(\s*\d\s*\)\s*$")
UNIT_NOTE = re.compile(r"\s*\((χιλιάδες )?τεμάχια\)", re.I)
# The same animal under another name in different years.
LABEL_ALIASES = {"ινδιανοι (γαλοπουλεσ)": "Γαλοπούλες"}
TITLE = re.compile(r"^(?:Πίνακας|ΠΙΝΑΚΑΣ)\s*(\d{1,2}\s*[α-ωά-ώ]{0,2})\s*[.:]?\s*(.*)$", re.I)


def tidy(label):
    label = FOOTNOTE_END.sub("", label)
    label = re.sub(r"(?<=[Α-Ωα-ω])-\s(?=[Α-Ωα-ω])", "", label)
    return clean_label(label)


def find_start(sheet):
    for r in range(sheet.nrows):
        if COUNTRY.match(sheet.text(r, 0)):
            return r
    return None


def parse_sheet(sheet, edition):
    start = find_start(sheet)
    if start is None:
        return None
    label_row = next((r for r in range(start - 1, -1, -1) if re.match(r"^Περιφέρει", sheet.text(r, 0))), None)
    if label_row is None:
        raise LayoutError("no header row (Περιφέρειες και Περιφερειακές Ενότητες)")
    last = next((c - 1 for c in range(1, sheet.ncols) if LATIN.search(sheet.text(start, c)) and not GREEK.search(sheet.text(start, c))), None)
    if last is None or last < 1:
        raise LayoutError("no English area name closing the country line")

    title = source_table = ""
    for r in range(label_row):
        for c in range(min(sheet.ncols, 24)):
            m = TITLE.match(sheet.text(r, c))
            if m and not title and GREEK.search(m.group(2)):
                source_table, title = m.group(1).replace(" ", ""), m.group(2).strip()
    if not title:
        raise LayoutError("no table title")
    table_key = next((key for kw, key in TABLE_KEYS if kw in fold(title) + " "), None)
    if not table_key:
        raise LayoutError(f"unknown table: {title!r}")
    units = " ".join(sheet.text(r, c) for r in range(label_row) for c in range(3)
                     if re.search(r"Κεφάλια|κεφαλών|τόνν?ους|τόνν?οι|τεμάχια|Αριθμός|Βάρος", sheet.text(r, c)) and len(sheet.text(r, c)) < 90)
    stated = re.findall(r"\b(20\d\d)\b", title)
    # the survey of a year is published under that year's ELSTAT page; a title that names another year is a typo
    ref_year, fix = edition, ""
    if stated and int(stated[0]) != edition:
        fix = f"the title of the sheet states {stated[0]}, the publication page is the {edition} survey; {edition} is used"

    from agri_spg06 import header_cells
    grid = header_cells(sheet, label_row, start)
    specs, skipped = [], []
    for c in range(1, last + 1):
        greek = []
        for row in grid:
            value = row[c]
            if not value or re.fullmatch(r"\d+(\.0)?", value):
                continue
            label, _ = split_bilingual(value)
            label = tidy(label)
            if label and GREEK.search(label):
                greek.append(label)
        path = dedupe(greek)
        if not path:
            skipped.append({"col": c, "path": [], "reason": "empty header"})
            specs.append(None)
            continue
        variable, unit, problem = measure(table_key, path, units)
        if variable is None:
            skipped.append({"col": c, "path": path, "reason": problem})
            specs.append(None)
            continue
        rest = [UNIT_NOTE.sub("", LABEL_ALIASES.get(fold(p), p)).strip() for p in path if not is_measure_word(table_key, p)] or ["Σύνολο"]
        total = fold(rest[-1]).startswith(("συνολο", "γενικο συνολο"))
        specs.append({"col": c, "path": path, "path_en": [], "marker": None, "notes": [], "measure": variable, "unit": unit,
                      "qualifier": "", "product_path": rest, "source_path": list(path),
                      "product_code": table_key + "." + ".".join(slug(p) for p in rest), "is_total": total, "name_en": ""})

    rows, region, warnings, missing = [], None, [], {}
    for r in range(start, sheet.nrows):
        label = sheet.text(r, 0)
        if re.match(r"^\(\d\)", label):
            break
        cells = [parse_cell(sheet.get(r, c)) for c in range(1, last + 1)]
        if not label or all(s == "blank" for s, _ in cells):
            continue
        label = FOOTNOTE_END.sub("", label)
        if COUNTRY.match(label):
            level, code = "country", "EL"
        elif re.match(r"^Περιφέρεια ", label, re.I):
            code = agri_geo.region_code(label)
            if not code:
                raise LayoutError(f"unknown region: {label!r}")
            level, region = "region", code
        else:
            number = agri_geo.unit_number(label)
            if not number:
                raise LayoutError(f"unknown regional unit: {label!r}")
            if agri_geo.unit_region(number) != region:
                # ELSTAT left out a region row in the early tables; the unit still belongs to its own region
                missing.setdefault(agri_geo.unit_region(number), region)
            level, code = "unit", "PE" + number
        rows.append({"level": level, "geo_code": code, "label": label, "cells": cells})
    for gone, host in missing.items():
        warnings.append(f"the row of region {gone} is missing; its units follow the row of {host}")
        _flag_combined(rows, [s for s in specs if s], host, gone)
    keep = [i for i, s in enumerate(specs) if s]
    for row in rows:
        row["cells"] = [row["cells"][i] for i in keep]
    return {"sheet": sheet.name, "source_table": source_table, "title": title, "title_en": "", "ref_year": ref_year,
            "table_key": table_key, "units": units, "legend": {}, "columns": [specs[i] for i in keep], "rows": rows,
            "warnings": warnings, "ref_year_stated": True, "fix": fix, "skipped_columns": skipped}


MEASURE_WORDS = re.compile(r"^(αριθμοσ κεφαλων|βαροσ)$")


def is_measure_word(table_key, label):
    return table_key == "lv_meat" and bool(MEASURE_WORDS.match(fold(label)))


def measure(table_key, path, units):
    """(variable, unit, problem) of a column from its header path and the unit line of the table."""
    f = " ".join(fold(p) for p in path)
    if table_key == "lv_stock":
        if "κυψελ" in f:
            return "hives", "hive", None
        return "animals", "head", None
    if table_key in VARIABLE_OF:
        variable = VARIABLE_OF[table_key]
        return variable, UNIT_OF[variable], None
    if table_key == "lv_meat":
        if fold(path[-1]) == "βαροσ":
            return "carcass_weight", "tonne", None
        if fold(path[-1]) == "αριθμοσ κεφαλων":
            return "slaughtered", "head", None
        return None, None, "the header names neither a head count nor a weight"
    if table_key == "lv_other":
        text = " ".join(path)
        if re.search(r"χιλιάδες τεμάχια", text):
            return "production_kpieces", "thousand_pieces", None
        if re.search(r"\(τεμάχια\)", text):
            # The header of 2011-2021 says "pieces", but the figures of those years alternate between pieces and thousand
            # pieces (e.g. small-animal skins in Greece: 22 119 811 in 2011, 21 239 in 2012, 8 009 in 2013, 6 602 364 in
            # 2014). Neither reading is certain, so these columns are not imported.
            return None, None, "skins: the header says pieces but the figures alternate between pieces and thousand pieces from year to year"
        if re.search(r"αυγα|δερματα", f):  # the unit line above the header: "Αυγά και δέρματα σε χιλιάδες τεμάχια"
            if re.search(r"χιλιάδες τεμάχια", units):
                return "production_kpieces", "thousand_pieces", None
            return None, None, "eggs or skins without a unit in the header or the unit line"
        return "production", "tonne", None
    return None, None, "unknown table"


def check_sums(table, tolerance=0.002):
    """Published totals that differ from the sum of their parts: regional units -> region -> country."""
    issues = []
    rows = table["rows"]
    by_geo = {r["geo_code"]: r for r in rows}
    regions = [r for r in rows if r["level"] == "region"]
    for i, spec in enumerate(table["columns"]):
        def number(row):
            status, value = row["cells"][i]
            return value if status == "ok" else 0.0

        def differs(total, summed):
            return abs(total - summed) > max(tolerance * abs(total), 1.0 if spec["unit"] in ("head", "hive") else 0.01)

        label = " > ".join(spec["product_path"]) + f" [{spec['measure']}]"
        for region in regions:
            if region["cells"][i][0] != "ok":
                continue
            parts = [r for r in rows if r["level"] == "unit" and agri_geo.unit_region(r["geo_code"][2:]) == region["geo_code"]]
            if parts and all(p["cells"][i][0] in ("ok", "dash") for p in parts) and differs(number(region), sum(number(p) for p in parts)):
                issues.append({"col": i, "geo": region["geo_code"], "column": label,
                               "message": f"parts add up to {sum(number(p) for p in parts):g}, region total is {number(region):g}"})
        country = by_geo.get("EL")
        if country and regions and country["cells"][i][0] == "ok" and all(r["cells"][i][0] == "ok" for r in regions):
            if differs(number(country), sum(number(r) for r in regions)):
                issues.append({"col": i, "geo": "EL", "column": label,
                               "message": f"regions add up to {sum(number(r) for r in regions):g}, country total is {number(country):g}"})
    return issues


def parse_workbook(path, edition):
    """(tables, notes) like agri_spg06.parse_workbook."""
    tables, notes = [], []
    for sheet in load(path):
        try:
            table = parse_sheet(sheet, edition)
        except LayoutError as error:
            notes.append({"sheet": sheet.name, "severity": "error", "message": str(error)})
            continue
        if table is not None:
            tables.append(table)
    return tables, notes
