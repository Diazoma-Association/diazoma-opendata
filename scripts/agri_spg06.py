"""Parser for the ELSTAT Annual Agricultural Survey tables (SPG06).

The workbooks are formatted for reading, not for processing: bilingual titles, headers over several merged rows,
one sheet per table (sometimes with stale or helper sheets), geography given by indentation and the measure of
a column given by a numeric marker explained in a footnote ("1=εκτάσεις, 2=παραγωγή"). Nothing is assumed from
the position of a column: the header of every table is read, the marker legend is read from the footnotes and the
unit is checked against the unit line above the header. A table whose layout is not understood is reported, not
guessed.

parse_workbook() returns one dict per data sheet with its columns (product, measure, unit) and its rows (one per
geographic unit, with the published values). Table numbers differ between years (2γ in one year is 2δ in the
next), so tables are identified by `table_key`, derived from the title, and the published number is kept as
`source_table`.
"""

import re
import unicodedata
from pathlib import Path

import agri_geo
import agri_products
from agri_xlsx import clean, load

GREEK = re.compile("[Ͱ-Ͽἀ-῿]")
LATIN = re.compile("[A-Za-z]")
DASHES = {"—", "―", "–", "-", "−"}
UNITS_LINE = re.compile(r"στρέμμα|τόνν?ους", re.I)
FOOTNOTE = re.compile(r"\s*\(\d+\)")
MARKER = re.compile(r"^(\d)([αβ]?)(?:\s*-\s*\d[ab])?(?:\s*\(\d+\))?$")
TITLE_ID = re.compile(r"^(?:Πίνακας\s+)?(\d{1,2}\s*[α-ωά-ώ]{0,2})\s*[.:]\s*", re.I)

# Title keywords (accents and case removed) -> table_key. The first match wins.
TABLE_KEYS = [
    ("κατηγοριες εκτασεων", "land_use"), ("εκτασεις καλλιεργειων και αγραναπαυσης", "land_use"),
    ("σιτηρα", "cereals"), ("βρωσιμα οσπρια", "pulses_edible"), ("κτηνοτροφικα οσπρια", "pulses_fodder"),
    ("βιομηχανικα", "industrial"), ("για σανο", "fodder_hay"), ("χλωρο χορτο", "fodder_green"),
    ("γρασιδια", "fodder_grazing"), ("για βοσκη", "fodder_grazing"), ("πεπονοειδη", "melons_potatoes"),
    ("κηπευτικη γη", "horticulture"), ("λαχανικα", "vegetables"), ("αμπελια", "vineyards"),
    ("αριθμος δενδρων", "trees"), ("εκτασεις δενδρωνων", "tree_areas"), ("εκτασεις συνεχων", "tree_areas"),
    ("ποτιστικες", "irrigated"), ("ελαιολαδου", "secondary"), ("δευτερογενων", "secondary"),
]
CATEGORIES = {
    "land_use": "Χρήση γεωργικής γης", "cereals": "Σιτηρά", "pulses_edible": "Βρώσιμα όσπρια",
    "pulses_fodder": "Κτηνοτροφικά όσπρια", "industrial": "Βιομηχανικά φυτά", "fodder_hay": "Κτηνοτροφικά φυτά για σανό",
    "fodder_green": "Κτηνοτροφικά φυτά για χλωρό χόρτο", "fodder_grazing": "Κτηνοτροφικά φυτά για βοσκή",
    "melons_potatoes": "Πεπονοειδή και πατάτες", "vegetables": "Λαχανικά", "horticulture": "Κηπευτική γη και καλλωπιστικά",
    "vineyards": "Αμπέλια και σταφιδάμπελα", "tree_areas": "Δενδρώδεις καλλιέργειες (εκτάσεις)",
    "trees": "Δενδρώδεις καλλιέργειες (δένδρα και παραγωγή)", "irrigated": "Ποτιστικές εκτάσεις",
    "secondary": "Ελαιόλαδο και μούστος",
}
UNIT_OF = {"area": "stremma", "production": "tonne", "trees_total": "tree", "trees_regular": "tree"}
STATUS_STAGE = {"final": "final", "provisional": "provisional", "unspecified": "unspecified"}


# Corrections of defects in single ELSTAT sheets, each checked against the data and the press release of the same
# publication (see data/README.md). Key: (publication year, document id) -> sheet name -> correction.
SOURCE_FIXES = {
    ("2011", "206119"): {"ΠΙΝΑΚΑΣ 2(η)": {
        "group_label": (6, 13, "Πατάτες συγκομιζόμενες"),
        "reason": "the group header «Πατάτες συγκομιζόμενες» is merged over two columns only, not the eight it covers"}},
    ("2019", "444307"): {"Sheet1": {
        "ref_year": 2019,
        "reason": "the title says 2018, but the olive production totals 3.240,1 thousand tonnes, the 2019 figure of the "
                  "2019 press release (2018: 2.764,6, which is the 2018 publication's table)"}},
    ("2020", "503804"): {"Sheet1": {
        "ref_year": 2020,
        "reason": "the title says 2021, but the values equal the 2020 garden land of table 1 in the same publication"}},
    ("2014", "350091"): {"Sheet2": {
        "skip": True, "reason": "values in kilograms (1000 × Sheet1) although the unit line says tonnes; Sheet1 is the same table in tonnes"}},
    ("2015", "356929"): {"Sheet2": {
        "skip": True, "reason": "the 2014 table with values in kilograms although the unit line says tonnes; the 2014 publication has it in tonnes"}},
}


class LayoutError(Exception):
    pass


def fold(text):
    """Lower case without accents: used to compare Greek labels."""
    text = unicodedata.normalize("NFD", str(text).lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("ς", "σ")


def greekness(text):
    greek, latin = len(GREEK.findall(text)), len(LATIN.findall(text))
    return greek / (greek + latin) if greek + latin else 0.5


def split_bilingual(text):
    """(Greek, English) parts of a header cell; older tables write both languages in one cell ('Σόργο Sorghum')."""
    tokens = text.split(" ")
    for i, token in enumerate(tokens):
        if LATIN.search(token) and greekness(token) < 0.5:
            return " ".join(tokens[:i]).strip(" -–"), " ".join(tokens[i:]).strip()
    return text, ""


def split_total(label):
    """'Πατάτες Σύνολο Εκτάσεων' -> ['Πατάτες', 'Σύνολο']; other labels unchanged."""
    m = re.match(r"^(.+?)\s+(Σύνολο)\b.*$", label)
    return [m.group(1), "Σύνολο"] if m else [label]


def clean_label(text):
    """Header label without footnote marks, line-break hyphens or trailing punctuation."""
    text = FOOTNOTE.sub("", text)
    text = re.sub(r"(?<=[α-ωά-ώ])-(?=[α-ωά-ώ])", "", text)
    return re.sub(r"\s+", " ", text).strip(" .:,;-–")


TRANSLIT = {"α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th", "ι": "i", "κ": "k", "λ": "l",
            "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "τ": "t", "υ": "y", "φ": "f", "χ": "ch",
            "ψ": "ps", "ω": "o"}


def slug(text):
    """ASCII identifier from a Greek label (σιτάρι -> sitari)."""
    out = "".join(TRANSLIT.get(c, c) for c in fold(text))
    return re.sub(r"[^a-z0-9]+", "_", out).strip("_")


def parse_cell(value):
    """(status, number): ok with the number, dash for a dash, blank for an empty cell, text for anything else."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "blank", None
    if isinstance(value, bool):
        return "text", None
    if isinstance(value, (int, float)):
        return "ok", value
    text = clean(value)
    if text in DASHES:
        return "dash", None
    try:
        return "ok", float(text.replace(".", "").replace(",", ".")) if re.fullmatch(r"[\d.]+,\d+|\d{1,3}(\.\d{3})+", text) else float(text)
    except ValueError:
        return "text", None


def find_start(sheet):
    """Row and column of the 'Σύνολο Ελλάδας' line that opens the data of a table."""
    for r in range(sheet.nrows):
        for c in range(min(3, len(sheet.cells[r]))):
            if sheet.text(r, c).startswith("Σύνολο Ελλάδας"):
                return r, c
    return None


def header_cells(sheet, top, start):
    """Header rows with merged cells repeated over their whole range."""
    grid = [[sheet.text(r, c) for c in range(sheet.ncols)] for r in range(top, start)]
    for r0, r1, c0, c1 in sheet.merges:
        if r1 < top or r0 >= start:
            continue
        value = sheet.text(r0, c0)
        for r in range(max(r0, top), min(r1, start - 1) + 1):
            for c in range(c0, min(c1, sheet.ncols - 1) + 1):
                grid[r - top][c] = value
    return grid


def last_data_column(sheet, start, label_col):
    """The English label column ('Greece Total') closes the data; the value columns are the ones before it."""
    for c in range(len(sheet.cells[start]) - 1, label_col, -1):
        if "Greece" in sheet.text(start, c):
            return c - 1
    raise LayoutError("no 'Greece Total' label column")


def dedupe(items):
    out = []
    for item in items:
        if not out or out[-1] != item:
            out.append(item)
    return out


def split_legend(text):
    """{'1': 'εκτάσεις', '2': 'παραγωγή'} from '1=εκτάσεις, 2=παραγωγή'."""
    return {m.group(1): m.group(2).strip(" ,;") for m in
            re.finditer(r"(\d[αβ]?)\s*=\s*(.+?)(?=,\s*\d[αβ]?\s*=|$)", text)}


def legend_measure(text):
    t = fold(text)
    if "αριθμοσ" in t and "δενδρ" in t:
        return "trees_total"
    if "κανονικων δενδρωνων" in t:
        return "trees_regular"
    if "παραγωγη" in t:
        return "production"
    if "εκτασ" in t:
        return "area"
    return None


def title_info(sheet, top, pub_year):
    """Published table number, title lines and reference year from the rows above the header.

    Returns (table number, Greek title, English title, reference year, all Greek title lines)."""
    greek, english, lines = "", "", []
    for r in range(top):
        for c in range(min(4, sheet.ncols)):
            text = sheet.text(r, c)
            if len(text) < 6 or greekness(text) < 0.5 and not (GREEK.search(text) or "Table" in text):
                continue
            if greekness(text) < 0.5 and "Table" in text:
                english = english or text
            elif GREEK.search(text) and text not in lines:
                lines.append(text)
                if TITLE_ID.match(text) and re.search(r"Εκτάσ|Παραγωγ|Αριθμ", text):
                    greek = text
    m = TITLE_ID.match(greek)
    source_table = re.sub(r"\s+", "", m.group(1)) if m else ""
    years = re.findall(r"\b(20\d\d)\b", greek) or re.findall(r"\b(20\d\d)\b", " ".join(lines))
    return source_table, greek, english, int(years[-1]) if years else None, lines


def classify(title):
    folded = fold(title)
    folded = re.sub(r"^(πινακας\s+)?\d+\s*[α-ω]{0,2}\s*[.:]\s*", "", folded)
    for keyword, key in TABLE_KEYS:
        if fold(keyword) in folded:
            return key
    return None


# The legend names the two kinds of olive production differently in early years.
QUALIFIERS = {"βρώσιμων": "βρώσιμων ελιών", "ελαιοποίησης": "για ελαιοποίηση"}


def column_specs(sheet, top, start, label_col, last_col, units, legend, legend_text, table_key, fix=None):
    header = header_cells(sheet, top, start)
    specs = []
    for c in range(label_col + 1, last_col + 1):
        greek, english, marker = [], [], None
        for row in header:
            value = row[c]
            if not value:
                continue
            m = MARKER.match(value)
            if m:
                marker = m.group(1) + m.group(2)
            elif greekness(value) >= 0.5 or GREEK.search(value) and not LATIN.search(value[:3]):
                label, label_en = split_bilingual(value)
                if label:
                    greek.append(clean_label(label))
                if label_en:
                    english.append(clean_label(label_en))
            else:
                english.append(clean_label(value))
        path = [part for label in dedupe(greek) if label for part in split_total(label)]
        spec = {"col": c, "path": path, "path_en": dedupe(english), "marker": marker, "notes": []}
        if fix and "group_label" in fix and fix["group_label"][0] <= c <= fix["group_label"][1]:
            if not spec["path"] or fold(spec["path"][0]) != fold(fix["group_label"][2]):
                spec["path"].insert(0, fix["group_label"][2])
        if not spec["path"] and marker and specs and specs[-1]["marker"] != marker and specs[-1]["path"]:
            # a merged header whose second cell was not merged in the file: same product as the column on its left
            spec["path"], spec["path_en"] = list(specs[-1]["path"]), list(specs[-1]["path_en"])
            spec["notes"].append(f"column {c}: label taken from column {specs[-1]['col']} (header cell not merged in the source)")
        specs.append(spec)
    any_marker = any(spec["marker"] for spec in specs)
    has_area = bool(re.search(r"εκτάσ", units, re.I))
    has_prod = bool(re.search(r"παραγωγ|τόνν?ους", units, re.I))
    def resolve(spec):
        path, marker, qualifier, measure = list(spec["path"]), spec["marker"], "", None
        if not path:
            raise LayoutError(f"column {spec['col']} has no Greek label (English: {' > '.join(spec['path_en'])!r})")
        if marker:
            base = marker[0]
            if base not in legend:
                raise LayoutError(f"marker {marker!r} is not explained in the footnotes")
            measure = legend_measure(legend[base])
            if len(marker) > 1:  # 5α / 5β: parts of the production column, named in the legend
                part = re.search(re.escape(marker) + r"[\s=]+([^,)]+)", legend_text)
                qualifier = part.group(1).strip() if part else marker
                qualifier = QUALIFIERS.get(qualifier, qualifier)
        elif any_marker and not fold(path[-1]).startswith("συνολο"):
            raise LayoutError(f"column {spec['col']} ({' > '.join(path)}) has no marker although the table numbers its measures")
        else:
            for i, element in enumerate(path):
                if fold(element) == fold("Εκτάσεις") and len(path) > 1:
                    measure = "area"
                    path.pop(i)
                    break
                if fold(element).startswith("παραγωγη") and len(path) > 1:
                    measure = "production"
                    qualifier = " – ".join(path[i + 1:])
                    path = path[:i]
                    break
            if measure is None:
                if has_area and not has_prod:
                    measure = "area"
                elif has_prod and not has_area:
                    measure = "production"
                elif fold(path[-1]).startswith("συνολο"):
                    measure = "area"  # the total column of a table with areas and production is the area
                else:
                    raise LayoutError(f"cannot tell the measure of column {spec['col']}: {' > '.join(spec['path'])}")
        qualifier = agri_products.canonical_qualifier(qualifier)
        if measure is None:
            raise LayoutError(f"marker {marker!r} means {legend[marker[0]]!r}, which is not a known measure")
        if measure == "area" and not re.search(r"στρέμμα", units, re.I):
            raise LayoutError(f"area column without a stremma unit line ({units!r})")
        if measure == "production" and not re.search(r"τόνν?ους", units, re.I):
            raise LayoutError(f"production column without a tonne unit line ({units!r})")
        if not path:
            raise LayoutError(f"column {spec['col']} has no label")
        total = fold(path[-1]).startswith("συνολο") or fold(path[0]) == "γενικο συνολο"
        if total:
            path[-1] = "Σύνολο"
        product_path = agri_products.canonical_path(table_key, path)
        code = table_key + "." + ".".join(slug(p) for p in product_path)
        spec.update(measure=measure, unit=UNIT_OF[measure], qualifier=qualifier, product_path=product_path,
                    source_path=list(path), product_code=code, is_total=total,
                    name_en=" – ".join(spec["path_en"]) if len(spec["path_en"]) == len(spec["path"]) else "")

    for spec in specs:
        try:
            resolve(spec)
        except LayoutError as error:
            spec["skip"] = str(error)  # the column is reported and left out; the rest of the table is still imported
    return specs


def _flag_combined(rows, specs, host, gone, tolerance=0.002):
    """When a region row is missing, the preceding region's total sometimes already includes its units.

    Where the host total equals its own units plus the units of the missing region (and not its own alone), the
    cell is marked 'combined': the published number is kept but is not the value of the host region alone."""
    host_row = next((r for r in rows if r["geo_code"] == host), None)
    if host_row is None:
        return
    own = [r for r in rows if r["level"] == "unit" and agri_geo.unit_region(r["geo_code"][2:]) == host]
    other = [r for r in rows if r["level"] == "unit" and agri_geo.unit_region(r["geo_code"][2:]) == gone]
    for i in range(len(specs)):
        status, total = host_row["cells"][i]
        if status != "ok":
            continue
        num = lambda r: r["cells"][i][1] if r["cells"][i][0] == "ok" else 0.0
        a, b = sum(num(r) for r in own), sum(num(r) for r in other)
        near = lambda x, y: abs(x - y) <= max(tolerance * abs(y), 1.0)
        if b and not near(total, a) and near(total, a + b):
            host_row["cells"][i] = ("combined", total)


def parse_sheet(sheet, pub_year, doc_id=""):
    found = find_start(sheet)
    if not found:
        return None
    start, label_col = found
    units_row = next((r for r in range(start) if UNITS_LINE.search(sheet.text(r, 0)) and len(sheet.text(r, 0)) < 90), None)
    if units_row is None:
        raise LayoutError("no unit line (στρέμματα / τόνοι) above the header")
    units = sheet.text(units_row, 0)
    top = units_row + 1
    source_table, title, title_en, ref_year, lines = title_info(sheet, units_row, pub_year)
    table_key = classify(title) or next((k for k in (classify(line) for line in reversed(lines)) if k), None)
    if not table_key:
        if any("Συνέχεια" in line for line in lines) or not lines:
            return {"ignored": "continuation sheet of a table that is already complete in the workbook"}
        raise LayoutError(f"unknown table: {title!r}")
    fix = SOURCE_FIXES.get((str(pub_year), str(doc_id)), {}).get(sheet.name)
    if fix and fix.get("skip"):
        return {"ignored": fix["reason"]}
    if fix and "ref_year" in fix:
        ref_year = fix["ref_year"]
    ref_year_stated = ref_year is not None
    if ref_year is None:
        ref_year = pub_year  # some titles omit the year; the survey is annual, so the publication year is used
    last_col = last_data_column(sheet, start, label_col)
    legend, legend_lines = {}, []
    for r in range(start, sheet.nrows):
        text = sheet.text(r, label_col)
        if re.match(r"^\d[αβ]?\s*=", text):
            legend.update(split_legend(text))
            legend_lines.append(text)
    specs = column_specs(sheet, top, start, label_col, last_col, units, legend, " ".join(legend_lines), table_key, fix)
    rows, region, warnings, missing = [], None, [], {}
    for r in range(start, sheet.nrows):
        label = sheet.text(r, label_col)
        cells = [parse_cell(sheet.get(r, c)) for c in range(label_col + 1, last_col + 1)]
        if re.match(r"^(\(.{1,2}\)|\d[αβ]?\s*=)", label):
            break  # footnotes: nothing after them is data
        if not label or all(status == "blank" for status, _ in cells):
            continue
        if label.startswith("Σύνολο Ελλάδας"):
            level, code = "country", "EL"
        elif label.startswith("Περιφέρεια"):
            level, code = "region", agri_geo.region_code(label)
            region = code
            if not code:
                raise LayoutError(f"unknown region: {label!r}")
        else:
            number = agri_geo.unit_number(label)
            if not number:
                raise LayoutError(f"unknown regional unit: {label!r}")
            level, code = "unit", "PE" + number
            if region != agri_geo.unit_region(number):
                # ELSTAT left out a region row in some early tables; the unit still belongs to its own region
                missing.setdefault(agri_geo.unit_region(number), region)
        rows.append({"level": level, "geo_code": code, "label": label, "cells": cells})
    for gone, host in missing.items():
        warnings.append(f"the row of region {gone} is missing; its units follow the row of {host}")
        _flag_combined(rows, specs, host, gone)
    keep = [i for i, spec in enumerate(specs) if "skip" not in spec]
    skipped = [{"col": spec["col"], "path": spec["path"], "reason": spec["skip"]} for spec in specs if "skip" in spec]
    specs = [specs[i] for i in keep]
    for row in rows:
        row["cells"] = [row["cells"][i] for i in keep]
    return {"sheet": sheet.name, "source_table": source_table, "title": title, "title_en": title_en, "ref_year": ref_year,
            "table_key": table_key, "units": units, "legend": legend, "columns": specs, "rows": rows,
            "warnings": sorted(set(warnings)), "ref_year_stated": ref_year_stated, "fix": (fix or {}).get("reason", ""),
            "skipped_columns": skipped}


def parse_workbook(path, pub_year):
    """(tables, notes): the parsed data sheets of a workbook and what was skipped or could not be read."""
    tables, notes = [], []
    doc_id = Path(path).stem
    for sheet in load(path):
        try:
            table = parse_sheet(sheet, pub_year, doc_id)
        except LayoutError as error:
            notes.append({"sheet": sheet.name, "severity": "error", "message": str(error)})
            continue
        if table is None:
            continue
        if "ignored" in table:
            notes.append({"sheet": sheet.name, "severity": "warning", "message": table["ignored"]})
            continue
        if table["ref_year"] is None:
            notes.append({"sheet": sheet.name, "severity": "error", "message": "no reference year in the title"})
        elif table["ref_year"] not in (pub_year, pub_year - 1):
            notes.append({"sheet": sheet.name, "severity": "warning",
                          "message": f"sheet is for {table['ref_year']} in the {pub_year} publication; ignored as a stale sheet"})
        else:
            tables.append(table)
    # «Πίνακας4α (1)» and «(2)» are copies of the table split in two parts; the complete sheet is used when it exists
    complete = {t["table_key"] for t in tables if not re.search(r"\(\d\)\s*$", t["sheet"])}
    for table in [t for t in tables if re.search(r"\(\d\)\s*$", t["sheet"]) and t["table_key"] in complete]:
        tables.remove(table)
        notes.append({"sheet": table["sheet"], "severity": "warning",
                      "message": "continuation sheet: part of a table that is complete in another sheet of the workbook"})
    return tables, notes


def check_sums(table, tolerance=0.002):
    """Published totals that differ from the sum of their parts (units -> region -> country).

    Returns [{'col': column index, 'geo': geo_code, 'message': ...}]. Only published numbers are compared: a
    dash or an empty cell is skipped. ELSTAT rounds to the stremma / kilogram, so small differences are normal."""
    issues = []
    by_geo = {row["geo_code"]: row for row in table["rows"]}
    regions = [r for r in table["rows"] if r["level"] == "region"]
    for i, spec in enumerate(table["columns"]):
        absolute = 0.01 if spec["measure"] == "production" else 1.0

        def differs(total, summed):
            return abs(total - summed) > max(tolerance * abs(total), absolute)

        def number(row):
            status, value = row["cells"][i]
            return value if status in ("ok", "combined") else 0.0

        label = " > ".join(spec["product_path"]) + f" [{spec['measure']}]"
        for region in regions:
            if region["cells"][i][0] != "ok":
                continue  # no published region total to compare with
            parts = [r for r in table["rows"] if r["level"] == "unit" and agri_geo.unit_region(r["geo_code"][2:]) == region["geo_code"]]
            if parts and differs(number(region), sum(number(p) for p in parts)):
                issues.append({"col": i, "geo": region["geo_code"], "column": label,
                               "message": f"units add up to {sum(number(p) for p in parts):g}, region total is {number(region):g}"})
        country = by_geo.get("EL")
        if country and regions and country["cells"][i][0] == "ok" and all(r["cells"][i][0] in ("ok", "combined") for r in regions):
            if differs(number(country), sum(number(r) for r in regions)):
                issues.append({"col": i, "geo": "EL", "column": label,
                               "message": f"regions add up to {sum(number(r) for r in regions):g}, country total is {number(country):g}"})
    return issues
