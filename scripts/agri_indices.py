"""Parser for the ELSTAT national price indices of agriculture: DKT33 (annual indices of the compensation of the factors
of production) and DKT30 (monthly indices of output and input prices, annual indices of partial products).

These are national time series with a base year (2020=100), not regional statistics, so every table here has one row,
the country. The workbooks are overwritten by ELSTAT at every release and hold the whole history: each sheet becomes
one table per reference year, with the products of the sheet as columns. Month and annual values share a table:

    qualifier ""     the annual value of the source (the annual index, the "Μέσος Ετήσιος" column, the weight)
    qualifier "Mmm"  a month (M01 … M12); the annual mean of a year that is not complete is not imported

The unit of an index is "index_<base year>" (read from the sheet), so a rebase shows up as a unit change and cannot be
mixed with the old series. A zero in the partial-product table means that no price was recorded in that month
(seasonal products); it is stored as a missing value, never as an index of 0.

The sheets that repeat these figures (the transposed copy with product codes, the monthly evolution of the general
indices) are reported and not imported.
"""

import re

from agri_spg06 import LayoutError, fold, parse_cell, slug
from agri_xlsx import clean, load

TABLE_KEYS = {"ix_factors": "Δείκτες αμοιβής συντελεστών παραγωγής (ετήσιοι)", "ix_output": "Δείκτες τιμών εκροών (μηνιαίοι)",
              "ix_input": "Δείκτες τιμών εισροών (μηνιαίοι)", "ix_products": "Δείκτες τιμών εκροών μερικών προϊόντων"}
CATEGORIES = dict(TABLE_KEYS)
MONTHS = ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μαϊ", "Ιουν", "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"]
FACTORS = [("δεικτησ αμοιβησ συντελεστων", "general", "Γενικός δείκτης αμοιβής συντελεστών παραγωγής", True),
           ("εργασια", "labour", "Εργασία (ημερομίσθια)", False), ("γη", "land", "Γη (ενοίκια αγροκτημάτων)", False),
           ("κεφαλαιο", "capital", "Κεφάλαιο (αμοιβή κεφαλαίου)", False), ("τοκοι", "interest", "Τόκοι δανείων", False),
           ("ενοικια μηχανηματων", "machinery", "Ενοίκια μηχανημάτων", False)]
LATIN_TO_GREEK = str.maketrans("ABEHIKMNOPTXYZaeikoptxy", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖαεικορτχυ")


def mixed(word):
    """Latin letters typed inside a Greek word ('Toμάτες') are replaced by their Greek look-alikes."""
    return word.translate(LATIN_TO_GREEK) if re.search("[α-ωΑ-Ω]", word) and re.search("[A-Za-z]", word) else word


def tidy(text):
    return " ".join(mixed(w) for w in text.split())


def base_year(sheet, rows=14):
    for r in range(min(rows, sheet.nrows)):
        for c in range(min(sheet.ncols, 12)):
            m = re.search(r"(\d{4})\s*=\s*100", sheet.text(r, c))
            if m:
                return int(m.group(1))
    raise LayoutError("no base year (2020=100) on the sheet")


def factor_of(name):
    f = fold(re.sub(r"^[\d.()αβ]+\s*", "", name.replace("3.α)", "").replace("3.β)", "")).strip())
    f = re.sub(r"^(α|β)\)\s*", "", f)
    for key, code, label, total in FACTORS:
        if f.startswith(key):
            return code, label, total
    raise LayoutError(f"unknown factor of production: {name!r}")


def make_tables(sheet, table_key, title, units, by_year, stage, base, notes):
    """by_year: {year: [(product code, name, is_total, variable, unit, qualifier, status, value)]} -> one table per year."""
    tables = []
    for year in sorted(by_year, reverse=True):
        specs, cells = [], []
        for code, name, total, variable, unit, qualifier, status, value in by_year[year]:
            specs.append({"col": len(specs), "path": [name], "path_en": [], "marker": None, "notes": [], "measure": variable, "unit": unit,
                          "qualifier": qualifier, "product_path": [name], "source_path": [name], "product_code": f"{table_key}.{code}",
                          "is_total": total, "name_en": ""})
            cells.append((status, value))
        tables.append({"sheet": f"{sheet.name} · {year}", "source_table": "", "title": f"{title} · {year}", "title_en": "", "ref_year": year,
                       "table_key": table_key, "units": units, "legend": {}, "columns": specs,
                       "rows": [{"level": "country", "geo_code": "EL", "label": "Ελλάδα", "cells": cells}], "warnings": [],
                       "ref_year_stated": True, "fix": "", "skipped_columns": [], "stage": stage, "notes": notes})
    return tables


def parse_factors(sheet, edition):
    """DKT33 table 1: groups in rows, years in columns, with the weights."""
    header = next((r for r in range(min(sheet.nrows, 15)) if sheet.text(r, 0) == "ΟΜΑΔΕΣ"), None)
    if header is None:
        raise LayoutError("no header row (ΟΜΑΔΕΣ)")
    base = base_year(sheet)
    unit = f"index_{base}"
    years = {c: int(sheet.text(header, c)) for c in range(sheet.ncols) if re.fullmatch(r"\d{4}", sheet.text(header, c))}
    weight_col = next((c for c in range(sheet.ncols) if "Σταθμίσεις" in sheet.text(header, c)), None)
    by_year = {y: [] for y in years.values()}
    for r in range(header + 1, sheet.nrows):
        name = sheet.text(r, 0)
        if not name:
            continue
        code, label, total = factor_of(name)
        for c, y in years.items():
            status, value = parse_cell(sheet.get(r, c))
            by_year[y].append((code, label, total, "price_index", unit, "", status, value))
        if weight_col is not None:
            status, value = parse_cell(sheet.get(r, weight_col))
            by_year[max(years.values())].append((code, label, total, "weight", "weight", "", status, value))
    return make_tables(sheet, "ix_factors", "Ετήσιοι δείκτες αμοιβής συντελεστών παραγωγής", f"{base}=100", by_year, "unspecified", base,
                       ["the weights (Σταθμίσεις) are those of the base year and are stored under the latest year of the sheet"])


def parse_evolution(sheet, edition):
    """DKT33 table 2: per group an index and its annual change, years in rows."""
    header = next((r for r in range(min(sheet.nrows, 15)) if sheet.text(r, 0) == "Έτος"), None)
    if header is None:
        raise LayoutError("no header row (Έτος)")
    base = base_year(sheet)
    unit = f"index_{base}"
    groups = {}
    for c in range(1, sheet.ncols):
        if sheet.text(header, c):
            groups[c] = factor_of(sheet.text(header, c))
    by_year = {}
    for r in range(header + 2, sheet.nrows):
        label = sheet.text(r, 0)
        if not re.fullmatch(r"\d{4}", label):
            continue
        year = int(label)
        out = by_year.setdefault(year, [])
        for c, (code, name, total) in groups.items():
            for offset, variable, u in ((0, "price_index", unit), (1, "annual_change", "percent")):
                if sheet.text(header + 1, c + offset) == "" and offset:
                    continue
                status, value = parse_cell(sheet.get(r, c + offset))
                out.append((code, name, total, variable, u, "", status, value))
    return make_tables(sheet, "ix_factors", "Εξέλιξη ετήσιων δεικτών αμοιβής συντελεστών παραγωγής", f"{base}=100 και ετήσια μεταβολή (%)", by_year,
                       "unspecified", base, ["the annual change of the first year is empty in the source"])


def parse_monthly(sheet, edition, table_key):
    """DKT30 tables 04: blocks of one year each: code, description, weight, twelve months, annual mean."""
    base = base_year(sheet)
    unit = f"index_{base}"
    by_year, current, header = {}, None, None
    zeros = 0
    for r in range(sheet.nrows):
        text = sheet.text(r, 0)
        m = re.search(r"έτους\s+(\d{4})", text)
        if m:
            current, header = int(m.group(1)), None
            by_year.setdefault(current, [])
            continue
        if current is None:
            continue
        if text.startswith("Κωδικός"):
            header = r
            months = {c: i + 1 for c in range(sheet.ncols) for i, name in enumerate(MONTHS) if sheet.text(r, c) == name}
            mean_col = next((c for c in range(sheet.ncols) if sheet.text(r, c).startswith("Μέσος")), None)
            weight_col = next((c for c in range(sheet.ncols) if "Στάθμισης" in sheet.text(r, c)), None)
            if len(months) != 12 or mean_col is None:
                raise LayoutError(f"the header of the {current} block does not name twelve months and the annual mean")
            continue
        if header is None or not re.fullmatch(r"\d{6}", text):
            continue
        name = tidy(sheet.text(r, 1))
        total = "ΓΕΝΙΚΟΣ" in name.upper()
        cells = {c: parse_cell(sheet.get(r, c)) for c in list(months) + [mean_col] + ([weight_col] if weight_col is not None else [])}
        for c in list(months) + [mean_col]:
            if cells[c] == ("ok", 0) or cells[c] == ("ok", 0.0):
                cells[c] = ("blank", None)  # an index is never 0: the source writes 0 where no price was recorded
                zeros += 1
        for c, month in months.items():
            status, value = cells[c]
            by_year[current].append((f"c{text}", name, total, "price_index", unit, f"M{month:02d}", status, value))
        month_states = [cells[c][0] for c in months]
        status, value = cells[mean_col]
        if any(s != "ok" for s in month_states):
            status, value = "blank", None  # the mean of an unfinished year is not a mean of the year
        by_year[current].append((f"c{text}", name, total, "price_index", unit, "", status, value))
        if weight_col is not None:  # the blocks up to 2019 print no weights
            status, value = cells[weight_col]
            by_year[current].append((f"c{text}", name, total, "weight", "weight", "", status, value))
    if not by_year:
        raise LayoutError("no yearly blocks found")
    title = "Δείκτης τιμών εκροών" if table_key == "ix_output" else "Δείκτης τιμών εισροών"
    notes = (["cells with the value 0 (no price recorded) are stored as missing values, not as an index of 0"] if zeros else []) + ["the annual mean of a year with missing months is not imported", "weights are those printed in each yearly block from 2020 on (the scale of the weights is that of the source)"]
    return make_tables(sheet, table_key, title + " (μηνιαίοι)", f"{base}=100", by_year, "provisional", base, notes)


def parse_products(sheet, edition):
    """DKT30 table 01: blocks of up to 15 partial products in columns; years in rows (annual index) and, for the
    current year, months. Every block has its own header row ("Έτος και μήνας") and its own products."""
    base = base_year(sheet)
    unit = f"index_{base}"
    products, by_year, year, zeros, blocks = {}, {}, None, 0, 0
    for r in range(sheet.nrows):
        label = sheet.text(r, 0)
        if label.startswith("Έτος και") or label.startswith("Year and"):
            group = label.startswith("Year and")  # the last block holds product groups ("Σταφύλια" there is not the product "Σταφύλια")
            products = {c: (("g_" if group else "") + slug(tidy(sheet.text(r, c))), tidy(sheet.text(r, c)) + (" (ομάδα προϊόντων)" if group else ""))
                        for c in range(1, sheet.ncols) if sheet.text(r, c)}
            year, blocks = None, blocks + 1
            continue
        if not products:
            continue
        values = {c: parse_cell(sheet.get(r, c)) for c in products}
        if re.fullmatch(r"\d{4}", label):
            year = int(label)
            out = by_year.setdefault(year, [])
            if any(s == "ok" for s, _ in values.values()):
                for c, (code, name) in products.items():
                    status, value = values[c]
                    if status == "ok" and value == 0:
                        status, value, zeros = "blank", None, zeros + 1
                    out.append((code, name, False, "price_index", unit, "", status, value))
        elif label in MONTHS and year is not None:
            month = MONTHS.index(label) + 1
            for c, (code, name) in products.items():
                status, value = values[c]
                if status == "blank":
                    continue  # a month that has not been published yet
                if status == "ok" and value == 0:
                    status, value, zeros = "blank", None, zeros + 1
                by_year[year].append((code, name, False, "price_index", unit, f"M{month:02d}", status, value))
        elif label.startswith("Σημείωση"):
            products = {}
    if not blocks:
        raise LayoutError("no header row (Έτος και μήνας)")
    by_year = {y: rows for y, rows in by_year.items() if rows}
    names = [name for rows in by_year.values() for _c, name, *_r in rows]
    notes = ["cells with the value 0 (no price recorded in that month, seasonal products) are stored as missing values, not as an index of 0"] if zeros else []
    notes.append(f"the sheet holds {blocks} blocks of products, each with its own header")
    return make_tables(sheet, "ix_products", "Δείκτες τιμών εκροών μερικών προϊόντων (χωρίς επιδοτήσεις)", f"{base}=100", by_year, "provisional", base, notes)


def parse_sheet(sheet, edition):
    """(tables, skipped reason) of one sheet."""
    if sheet.nrows == 0:
        return [], None
    head = " ".join(sheet.text(r, c) for r in range(min(sheet.nrows, 14)) for c in range(min(sheet.ncols, 6)))
    if any(sheet.text(r, 0) == "ΟΜΑΔΕΣ" for r in range(min(sheet.nrows, 15))):
        return parse_factors(sheet, edition), None
    if any(sheet.text(r, 0) == "Έτος" and "Δείκτης" in " ".join(sheet.text(r + 1, c) for c in range(sheet.ncols)) for r in range(min(sheet.nrows - 1, 15))):
        return parse_evolution(sheet, edition), None
    if "Συντελεστές Στάθμισης" in head or any("Συντελεστές Στάθμισης" in sheet.text(r, 3) for r in range(sheet.nrows)):
        return parse_monthly(sheet, edition, "ix_input" if "Εισροών" in head else "ix_output"), None
    if any(sheet.text(r, 0).startswith("Έτος και") for r in range(min(sheet.nrows, 15))):
        return parse_products(sheet, edition), None
    if any(sheet.text(r, 0) == "ΚΩΔ" for r in range(min(sheet.nrows, 6))):
        return [], "the transposed copy with product codes of the annual indices repeats another sheet"
    if any(sheet.text(r, 0) == "Περίοδος" for r in range(min(sheet.nrows, 15))):
        return [], "the monthly evolution of the general indices (Excel dates, annual changes) repeats the monthly tables"
    raise LayoutError("a sheet with a layout this importer does not know")


def check_sums(table):
    return []


def parse_workbook(path, edition):
    """(tables, notes) like agri_spg06.parse_workbook."""
    tables, notes = [], []
    for sheet in load(path):
        try:
            parsed, skipped = parse_sheet(sheet, edition)
        except LayoutError as error:
            notes.append({"sheet": sheet.name, "severity": "error", "message": str(error)})
            continue
        tables.extend(parsed)
        if skipped:
            notes.append({"sheet": sheet.name, "severity": "warning", "message": f"sheet not imported: {skipped}"})
    return tables, notes
