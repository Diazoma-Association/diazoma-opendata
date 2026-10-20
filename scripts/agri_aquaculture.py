"""Parser for the ELSTAT annual aquaculture survey (SPA06).

The survey publishes national totals only (the title of every table says "Σύνολο χώρας" or says nothing about regions): there
is no regional or prefecture breakdown, so the platform shows the country and nothing below it.

Tables imported (every edition is a set of workbooks with one table each):

    aq_production   quantity (kg) and value (euro) of the reared species, by water type (total, fresh, brackish, sea)
    aq_juveniles    juveniles released from hatcheries and farms, in thousands, by species and water type
    aq_employment   permanent and part-time personnel and number of wages, by water type

Not imported: the table of facilities (methods, water volume, area; its row labels span several lines and the method
groups change from year to year) and the quantity and value by rearing method (it repeats the species table by method).
They are reported for every edition.

The rows of the species tables are flat lists of species with a few group lines (fish, crustaceans, molluscs, aquatic
plants). The platform stores every published row as its own product; spellings (plural and singular, accents, a misspelt
"Λαυράκια") are unified, but combined categories of the early years ("Κέφαλοι-Κυπρίνοι", "Πέστροφα-Σολομός") stay as
published, and a category is never split or added to another. Group lines are stored as the "Σύνολο" of their group.
"""

import re

from agri_spg06 import LayoutError, fold, header_cells, parse_cell, slug
from agri_xlsx import clean, load

CATEGORIES = {"aq_production": "Ποσότητα και αξία εκτρεφόμενων ειδών", "aq_juveniles": "Παραγωγή γόνου",
              "aq_employment": "Απασχολούμενοι στις υδατοκαλλιέργειες"}
WATER = {"συνολο": "total", "γλυκα": "fresh", "υφαλμυρα": "brackish", "θαλασσια": "sea"}
WATER_NAME = {"total": "σύνολο", "fresh": "γλυκά ύδατα", "brackish": "υφάλμυρα ύδατα", "sea": "θαλάσσια ύδατα"}
GROUPS = [("Ψάρια", ("ψαρια",)), ("Καρκινοειδή", ("καρκινοειδη",)), ("Μαλάκια", ("οστρακοειδη", "μαλακια", "διθυρα μαλακια", "οστρακοειδη (διβαλβα μαλακια)")),
          ("Υδρόβια φυτά και φύκη", ("υδροβια φυτα-φυκη", "υδροβια φυτα φυκη"))]
GROUP_BY_LABEL = {key: name for name, keys in GROUPS for key in keys}
# prefix of the folded label -> published name; first match wins
SPECIES = [("γλωσσ", "Γλώσσα", "Ψάρια"), ("κεφαλ", "Κέφαλος", "Ψάρια"), ("κρανι", "Κρανιός", "Ψάρια"), ("κυπριν", "Κυπρίνος", "Ψάρια"),
           ("λαβρακ", "Λαβράκι", "Ψάρια"), ("λαυρακ", "Λαβράκι", "Ψάρια"), ("λιθριν", "Λιθρίνι", "Ψάρια"), ("λυθριν", "Λιθρίνι", "Ψάρια"),
           ("μυλοκοπ", "Μυλοκόπι", "Ψάρια"), ("μυτακ", "Μυτάκι", "Ψάρια"), ("πεστροφ", "Πέστροφα", "Ψάρια"), ("σαργ", "Σαργός", "Ψάρια"),
           ("σολομ", "Σολομός", "Ψάρια"), ("σολωμ", "Σολομός", "Ψάρια"), ("συκι", "Συκιός", "Ψάρια"), ("συναγρ", "Συναγρίδα", "Ψάρια"),
           ("τσιπουρ", "Τσιπούρα", "Ψάρια"), ("φαγκρ", "Φαγκρί", "Ψάρια"), ("χελι", "Χέλι", "Ψάρια"), ("οξυριγχ", "Οξύρρυγχος", "Ψάρια"),
           ("οξυρρυγχ", "Οξύρρυγχος", "Ψάρια"), ("μαγιατικ", "Μαγιάτικο", "Ψάρια"), ("γαριδ", "Γαρίδες", "Καρκινοειδή"), ("καβουρ", "Καβούρια", "Καρκινοειδή"),
           ("μυδι", "Μύδια", "Μαλάκια"), ("στρειδ", "Στρείδια", "Μαλάκια"), ("κυδωνι", "Κυδώνια", "Μαλάκια"), ("σπιρουλιν", "Σπιρουλίνα", "Υδρόβια φυτά και φύκη"),
           ("αυγοταραχ", "Αυγοτάραχο", "Υδρόβια φυτά και φύκη")]
OTHERS = [("λοιπα ψαρι", "Λοιπά ψάρια", "Ψάρια"), ("λοιπα μαλακι", "Λοιπά μαλάκια", "Μαλάκια"), ("λοιπα οστρακοειδ", "Λοιπά οστρακοειδή", None),
          ("λοιπα καρκινοειδ", "Λοιπά καρκινοειδή", "Καρκινοειδή")]
TOTAL = ("γενικο συνολο", "γενικο αθροισμα", "συνολο")
NOTES = re.compile(r"^(Επισημάνσεις|Σημείωση|Notes?\b|\d\.\s|\*)", re.I)


def label_of(text):
    return re.sub(r"[*\s]+$", "", re.sub(r"\s+", " ", text)).strip()


def classify(label, group):
    """(group, name, is_group_total) of a published row label; `group` is the group of the previous row."""
    f = fold(label_of(label))
    if f in TOTAL:
        return "", "Γενικό σύνολο", False
    if f in GROUP_BY_LABEL:
        return GROUP_BY_LABEL[f], "Σύνολο ομάδας", True
    for key, name, g in OTHERS:
        if f.startswith(key):
            return g or group, name, False
    if f == "λοιπα":
        return group, "Λοιπά", False
    if "-" not in f:
        for key, name, g in SPECIES:
            if f.startswith(key):
                return g, name, False
    return group, label_of(label), False


def despace(text):
    tokens = text.split(" ")
    return "".join(tokens) if len(tokens) >= 3 and sum(len(t) == 1 for t in tokens) >= 0.8 * len(tokens) else text


def cell_of(value):
    if isinstance(value, str):
        value = re.sub(r"[*\s]+$", "", value.strip())
        if value == ".":
            return "text", None
    return parse_cell(value)


def kind_of(sheet):
    head = " ".join(sheet.text(r, c) for r in range(min(sheet.nrows, 6)) for c in range(min(sheet.ncols, 4)))
    f = fold(head)
    if "γονου" in f:
        return "aq_juveniles"
    if "απασχολουμενοι" in f or "employment" in f or "employees" in f:
        return "aq_employment"
    if "μεθοδο" in f and "ποσοτητα" in f:
        return None
    if "ποσοτητα και αξια" in f:
        return "aq_production"
    return None


def data_start(sheet, first_col):
    for r in range(3, sheet.nrows):
        cells = [cell_of(sheet.get(r, c)) for c in range(first_col, min(sheet.ncols, first_col + 3))]
        if any(s in ("ok", "dash", "confidential") for s, _ in cells) and any(re.search("[Ͱ-Ͽ]", sheet.text(r, c)) for c in range(first_col)):
            return r
    return None


def parse_sheet(sheet, edition, key):
    # the label column holds Greek text on the data rows; the numbers start right after it
    label_col = next((c for c in range(3) if any(re.search("[Ͱ-Ͽ]", sheet.text(r, c)) and re.match(r"^(Γενικ|Ψάρια|Σε |Σύνολο)", sheet.text(r, c)) for r in range(sheet.nrows))), None)
    if label_col is None:
        raise LayoutError("no label column (Γενικό σύνολο / Ψάρια)")
    first = label_col + 1
    start = data_start(sheet, first)
    if start is None:
        raise LayoutError("no data rows")
    top = next((r for r in range(start) if re.search("Εκτρεφ|Είδος|Νερά|Νερ", sheet.text(r, 0)) or any(w in fold(sheet.text(r, c)) for c in range(first, sheet.ncols) for w in ("συνολο", "γλυκα", "μονιμο"))), 2)
    grid = header_cells(sheet, top, start)
    units = " ".join(sheet.text(r, 0) for r in range(top)) + " " + " ".join(sheet.text(r, c) for r in range(top, start) for c in range(0, first))
    last = max(c for c in range(first, sheet.ncols) if any(cell_of(sheet.get(r, c))[0] in ("ok", "dash", "confidential") for r in range(start, sheet.nrows)))
    unit_text = fold(units)

    def column_text(c):
        return [despace(re.sub(r"\s+", " ", row[c])).strip() for row in grid if row[c]]

    specs = []
    if key == "aq_employment":
        for c in range(first, last + 1):
            parts = column_text(c)
            greek = [p for p in parts if re.search("[Ͱ-Ͽ]", p)]
            if not greek:
                continue
            raw = " ".join(greek)
            # permanent personnel (total, university degree holders, others), part-time personnel, number of wages
            f = fold(raw)
            if "ημερομισθι" in f:
                var, unit, name = "wage_days", "wage_day", "Αριθμός ημερομισθίων"
            elif "εκτακτο" in f or "αριθμοσ ατομων" in f:
                var, unit, name = "persons", "person", "Έκτακτο προσωπικό"
            elif "πτυχι" in f:
                var, unit, name = "persons", "person", "Μόνιμο προσωπικό – κάτοχοι πανεπιστημιακού ή ειδικού πτυχίου"
            elif "λοιπ" in f:
                var, unit, name = "persons", "person", "Μόνιμο προσωπικό – λοιποί μόνιμοι"
            elif "συνολο" in f:
                var, unit, name = "persons", "person", "Μόνιμο προσωπικό – σύνολο"
            else:
                raise LayoutError(f"unknown column of the employment table: {raw!r}")
            specs.append((c, var, unit, name, ""))
        rows_label = lambda text: ("", "Γενικό σύνολο") if fold(text) in TOTAL and "γενικο" in fold(text) else None
    else:
        if "κιλα" not in unit_text and key == "aq_production":
            raise LayoutError(f"the unit line does not say kilograms: {units!r}")
        if "ιχθιδια" not in unit_text and key == "aq_juveniles":
            raise LayoutError(f"the unit line does not say thousand juveniles: {units!r}")
        for c in range(first, last + 1):
            parts = [despace(p) for p in column_text(c)]
            f = [fold(p) for p in parts]
            water = next((v for t in f for w, v in (("γλυκα", "fresh"), ("υφαλμυρα", "brackish"), ("θαλασσι", "sea")) if w in t), None) \
                or next(("total" for t in f if t.startswith("συνολο")), None)
            measure = "quantity_kg" if any(t.startswith("ποσοτητα") for t in f) else "value_eur" if any(t.startswith("αξια") for t in f) else None
            if key == "aq_juveniles":
                measure = "juveniles"
            if water is None or measure is None:
                if any(re.search("[Ͱ-Ͽ]", p) for p in parts):
                    raise LayoutError(f"column {c} has a header this parser does not know: {parts!r}")
                continue
            unit = {"quantity_kg": "kg", "value_eur": "eur", "juveniles": "thousand_juveniles"}[measure]
            specs.append((c, measure, unit, "", water))
    if not specs:
        raise LayoutError("no data columns")

    cells = {}
    group, order = "", []
    for r in range(start, sheet.nrows):
        label = sheet.text(r, label_col)
        if not label:
            continue
        if NOTES.match(label) and not re.search(r"\d", "".join(sheet.text(r, c) for c in range(first, last + 1))):
            break
        values = [cell_of(sheet.get(r, c)) for c, *_ in specs]
        if key == "aq_employment":
            water_row = {"σε γλυκα νερα": "fresh", "σε υφαλμυρα νερα": "brackish", "σε θαλασσια νερα": "sea"}.get(fold(label))
            if fold(label).startswith("γενικο"):
                water_row = "total"
            if water_row is None:
                continue
            for (c, var, unit, name, _), cell in zip(specs, values):
                cells[((name,), water_row, var, unit)] = cell
            continue
        if all(s == "blank" for s, _ in values):
            continue
        group, name, is_group = classify(label, group)
        for (c, var, unit, _n, water), cell in zip(specs, values):
            path = (group, name) if group else (name,)
            cells[(path, water, var, unit)] = cell
    if not cells:
        raise LayoutError("no rows")
    return cells


def make_table(sheet, edition, key, cells, title):
    products, order = {}, []
    for (path, water, var, unit), cell in cells.items():
        p = (key, path, var, unit, water)
        order.append((p, cell))
    specs, row_cells = [], []
    seen = set()
    for (key_, path, var, unit, water), cell in order:
        pcode = key + "." + ".".join(slug(p) for p in path if p)
        ident = (pcode, var, water)
        if ident in seen:
            raise LayoutError(f"two rows have the same product {pcode} ({path})")
        seen.add(ident)
        name_path = list(path) if len(path) > 1 else [path[0]]
        if water in WATER_NAME and key != "aq_employment":
            pass
        specs.append({"col": len(specs), "path": name_path, "path_en": [], "marker": None, "notes": [], "measure": var, "unit": unit,
                      "qualifier": water, "product_path": name_path, "source_path": name_path, "product_code": pcode,
                      "is_total": path[-1] in ("Γενικό σύνολο", "Σύνολο ομάδας") or path[-1].startswith("Μόνιμο προσωπικό – σύνολο"), "name_en": ""})
        row_cells.append(cell)
    return {"sheet": f"{sheet.name} · {CATEGORIES[key]}", "source_table": "", "title": title, "title_en": "", "ref_year": edition, "table_key": key,
            "units": "", "legend": {}, "columns": specs, "rows": [{"level": "country", "geo_code": "EL", "label": "Ελλάδα", "cells": row_cells}],
            "warnings": [], "ref_year_stated": False, "fix": "", "skipped_columns": [], "notes": []}


def check_sums(table, tolerance=0.002):
    """Total water type against the sum of fresh, brackish and sea water for every product and measure."""
    issues = []
    cells = {}
    for i, spec in enumerate(table["columns"]):
        status, value = table["rows"][0]["cells"][i]
        cells[(spec["product_code"], spec["measure"], spec["qualifier"])] = (i, status, value)
    for (code, measure, water), (i, status, value) in cells.items():
        if water != "total" or status != "ok" or table["table_key"] == "aq_employment":
            continue
        parts = [cells.get((code, measure, w)) for w in ("fresh", "brackish", "sea")]
        if any(p is None for p in parts) or any(p[1] != "ok" for p in parts):
            continue
        s = sum(p[2] for p in parts)
        if abs(value - s) > max(tolerance * abs(value), 1.0):
            issues.append({"col": i, "geo": "EL", "column": f"{code} [{measure}]", "message": f"fresh, brackish and sea water add up to {s:g}, the total is {value:g}"})
    return issues


def parse_workbook(path, edition):
    """(tables, notes) like agri_spg06.parse_workbook."""
    tables, notes = [], []
    for sheet in load(path):
        if sheet.nrows == 0:
            continue
        key = kind_of(sheet)
        if key is None:
            notes.append({"sheet": sheet.name, "severity": "warning", "message": "sheet not imported: the table of facilities or of the rearing methods"})
            continue
        try:
            cells = parse_sheet(sheet, edition, key)
            title = " ".join(sheet.text(r, 0) for r in range(3) if sheet.text(r, 0))
            tables.append(make_table(sheet, edition, key, cells, title))
        except LayoutError as error:
            notes.append({"sheet": sheet.name, "severity": "error", "message": str(error)})
    return tables, notes
