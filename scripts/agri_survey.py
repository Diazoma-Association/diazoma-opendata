"""Parser for the ELSTAT farm structure survey tables (SPG32 holdings and areas, SPK12 livestock holdings).

These workbooks differ from the annual survey (SPG06): geography is the region and the prefecture (νομός; in Attica
the nomarchy) with a code column before the name, headers are bilingual and often written letter-spaced
("Σ Ι Τ Η Ρ Α   Γ Ι Α   Κ Α Ρ Π Ο"), every column group has a pair "holdings / area" or "holdings / animals", and
suppressed values are marked "x". The measure of a column is read from its own header (ΕΚΜΕΤΑΛΛΕΥΣΕΙΣ = holdings,
ΕΚΤΑΣΗ = area, ΑΡΙΘΜΟΣ ΖΩΩΝ = animals, ΖΩΙΚΕΣ ΜΟΝΑΔΕΣ = livestock units); a column whose header says none of
these is reported and left out.

The surveys are not annual: they are samples or censuses of different years (the 2023 survey follows a new
regulation) and their series are not joined. Each edition is stored under its own reference year.
"""

import re
from pathlib import Path

import agri_geo
from agri_spg06 import (LayoutError, clean_label, dedupe, fold, greekness, parse_cell, slug, split_bilingual, GREEK, LATIN)
from agri_xlsx import clean, load

TABLE_KEYS = [
    ("διακριση σε μεικτεσ", "fs_farm_types"), ("βιολογικησ εκτροφησ", "fs_organic_livestock"),
    ("ζωικεσ μοναδεσ", "fs_livestock_units"), ("αριθμοσ ζωων", "fs_livestock"),
    ("βασικεσ κατηγοριεσ χρησησ", "fs_land_use"), ("αροτραιεσ καλλιεργειεσ", "fs_arable"), ("ετησιεσ καλλιεργειεσ", "fs_arable"), ("σιτηρα", "fs_cereals"),
    ("δενδρωδεισ", "fs_tree_crops"), ("αμπελια", "fs_vineyards"), ("αρδευθεισεσ", "fs_irrigation"),
]
CATEGORIES = {
    "fs_farm_types": "Εκμεταλλεύσεις ανά τύπο (μεικτές, γεωργικές, κτηνοτροφικές)", "fs_land_use": "Χρήση γεωργικής γης",
    "fs_arable": "Αροτραίες καλλιέργειες", "fs_cereals": "Σιτηρά για καρπό", "fs_tree_crops": "Δενδρώδεις καλλιέργειες",
    "fs_vineyards": "Αμπέλια", "fs_irrigation": "Αρδευθείσες εκτάσεις", "fs_livestock": "Εκμεταλλεύσεις και ζώα ανά είδος",
    "fs_livestock_units": "Εκμεταλλεύσεις και ζωικές μονάδες ανά είδος", "fs_organic_livestock": "Βιολογική κτηνοτροφία",
}
UNIT_OF = {"holdings": "holding", "area": "stremma", "animals": "head", "livestock_units": "livestock_unit", "hives": "hive"}

# Display names of the (upper case, unaccented, often letter-spaced) labels of the tables. Keys are the Greek letters of
# the label only, so spacing, hyphens and the English text that shares the cell do not matter.
NAMES = {
    "ΑΜΠΕΛΙΑ ΓΙΑ": "", "ΟΙΝΟΥΣ ΟΝΟΜΑΣΙΑΣ ΠΡΟΕΛΕΥΣΗΣ": "Οίνοι ονομασίας προέλευσης", "ΟΙΝΟΥΣ ΓΕΩΓΡΑΦΙΚΗΣ ΕΝΔΕΙΞΗΣ": "Οίνοι γεωγραφικής ένδειξης",
    "ΛΟΙΠΟΥΣ ΟΙΝΟΥΣ": "Λοιποί οίνοι", "ΕΠΙΤΡΑΠΕΖΙΑ ΣΤΑΦΥΛΙΑ": "Επιτραπέζια σταφύλια", "ΣΤΑΦΙΔΑ ΞΕΡΗ (ΣΟΥΛΤΑΝΙΝΑ": "Ξερή σταφίδα (σουλτανίνα ή κορινθιακή)",
    "ΠΟΛΥΕΤΕΙΣ (ΔΕΝΔΡΩΔΕΙΣ) ΚΑΛΛΙΕΡΓΕΙΕΣ": "", "ΕΛΑΙΩΝΕΣ": "Ελαιώνες", "ΕΛΑΙΟΠΟΙΗΣΗΣ": "για ελαιοποίηση", "ΕΠΙΤΡΑΠΕΖΙΑΣ ΧΡΗΣΗΣ": "επιτραπέζιας χρήσης",
    "ΟΠΩΡΟΦΟΡΑ ΔΕΝΔΡΑ ΕΥΚΡΑΤΩΝ ΚΑΛΛΙΕΡΓΕΙΩΝ (ΠΥΡΗΝΟΚΑΡΠΑ ΚΑΙ ΜΗΛΟΕΙΔΗ)": "Οπωροφόρα δένδρα εύκρατων καλλιεργειών (πυρηνόκαρπα και μηλοειδή)",
    "ΟΠΩΡΟΦΟΡΑ ΔΕΝΔΡΑ ΥΠΟΤΡΟΠΙΚΗΣ ΚΑΙ ΤΡΟΠΙΚΗΣ ΠΡΟΕΛΕΥΣΗΣ (ΑΚΤΙΝΙΔΙΑ Κ.Λ.Π.)": "Οπωροφόρα δένδρα υποτροπικής και τροπικής προέλευσης (ακτινίδια κ.λπ.)",
    "ΔΕΝΔΡΑ ΓΙΑ ΚΑΡΠΟΥΣ ΜΕ ΚΕΛΥΦΟΣ (ΑΜΥΓΔΑΛΙΕΣ Κ.Λ.Π.)": "Δένδρα για καρπούς με κέλυφος (αμυγδαλιές κ.λπ.)",
    "ΕΣΠΕΡΙΔΟΕΙΔΗ (ΠΟΡΤΟΚΑΛΙΕΣ Κ.Λ.Π.)": "Εσπεριδοειδή (πορτοκαλιές κ.λπ.)",
    "ΛΟΙΠΕΣ ΔΕΝΔΡΩΔΕΙΣ ΚΑΛΛΙΕΡΓΕΙΕΣ ΚΑΙ ΜΟΝΙΜΕΣ ΚΑΛΛΙΕΡΓΕΙΕΣ ΣΕ ΘΕΡΜΟΚΗΠΙΑ": "Λοιπές δενδρώδεις και μόνιμες καλλιέργειες σε θερμοκήπια",
    "ΣΙΤΗΡΑ ΓΙΑ": "", "ΣΙΤΑΡΙ ΜΑΛΑΚΟ ΚΑΙ ΗΜΙΣΚΛΗΡΟ": "Σιτάρι μαλακό και ημίσκληρο", "ΣΙΤΑΡΙ ΣΚΛΗΡΟ": "Σιτάρι σκληρό", "ΣΙΚΑΛΗ": "Σίκαλη",
    "ΚΡΙΘΑΡΙ": "Κριθάρι", "ΒΡΩΜΗ": "Βρώμη", "ΑΡΑΒΟΣΙΤΟΣ ΓΙΑ ΚΑΡΠΟ (ΑΜΙΓΗΣ)": "Αραβόσιτος για καρπό (αμιγής)",
    "ΑΛΛΑ ΣΙΤΗΡΑ ΓΙΑ ΚΑΡΠΟ (ΣΟΡΓΟ, ΚΕΧΡΙ Κ.Λ.Π.)": "Άλλα σιτηρά για καρπό (σόργο, κεχρί κ.λπ.)", "ΡΥΖΙ": "Ρύζι",
    "ΑΡΟΤΡΑΙΕΣ ΚΑΛΛΙΕΡΓΕΙΕΣ": "Αροτραίες καλλιέργειες", "ΣΙΤΗΡΑ ΓΙΑ ΤΗΝ ΠΑΡΑΓΩΓΗ ΚΑΡΠΟΥ": "Σιτηρά για καρπό", "ΟΣΠΡΙΑ ΓΙΑ ΞΗΡΟ ΚΑΡΠΟ": "Όσπρια για ξηρό καρπό",
    "ΠΑΤΑΤΕΣ": "Πατάτες", "ΖΑΧΑΡΟΤΕΥΤΛΑ": "Ζαχαρότευτλα", "ΚΤΗΝΟΤΡΟΦΙΚΑ ΦΥΤΑ ΜΕ ΡΙΖΩΜΑΤΑ, ΒΟΛΒΟΥΣ Ή ΚΟΝΔΥΛΟΥΣ": "Κτηνοτροφικά φυτά με ριζώματα, βολβούς ή κονδύλους",
    "ΒΙΟΜΗΧΑΝΙΚΑ ΦΥΤΑ": "Βιομηχανικά φυτά", "ΝΩΠΑ ΛΑΧΑΝΙΚΑ, ΠΕΠΟΝΟΕΙΔΗ, ΦΡΑΟΥΛΕΣ": "Νωπά λαχανικά, πεπονοειδή, φράουλες",
    "ΑΝΘΗ ΚΑΙ ΔΙΑΚΟΣΜΗΤΙΚΑ ΦΥΤΑ": "Άνθη και διακοσμητικά φυτά", "ΚΑΛΛΙΕΡΓΕΙΕΣ ΚΤΗΝΟΤΡΟΦΙΚΩΝ ΦΥΤΩΝ": "Καλλιέργειες κτηνοτροφικών φυτών",
    "ΦΥΤΕΙΕΣ ΣΠΟΡΟΠΑΡΑΓΩΓΗΣ ΚΑΙ ΣΠΟΡΟΦΥΤΑ": "Φυτείες σποροπαραγωγής και σπορόφυτα", "ΛΟΙΠΕΣ ΑΡΟΤΡΑΙΕΣ ΚΑΛΛΙΕΡΓΕΙΕΣ": "Λοιπές αροτραίες καλλιέργειες",
    "ΑΓΡΑΝΑΠΑΥΣΕΙΣ": "Αγραναπαύσεις", "ΑΠΟ ΤΙΣ ΟΠΟΙΕΣ": "", "ΜΕ ΧΡΗΣΙΜΟΠΟΙΟΥΜΕΝΗ ΓΕΩΡΓΙΚΗ ΕΚΤΑΣΗ": "Με χρησιμοποιούμενη γεωργική έκταση",
    "Χρησιμοποιούμενη γεωργική έκταση": "Χρησιμοποιούμενη γεωργική έκταση", "ΠΟΛΥΕΤΕΙΣ (ΔΕΝΔΡΩΔΕΙΣ) ΚΑΛΛΙΕΡΓΕΙΕΣ ": "Πολυετείς (δενδρώδεις) καλλιέργειες",
    "ΑΜΠΕΛΙΑ": "Αμπέλια", "ΚΑΛΛΙΕΡΓΕΙΕΣ ΣΕ ΘΕΡΜΟΚΗΠΙΑ": "Καλλιέργειες σε θερμοκήπια", "ΜΟΝΙΜΑ ΛΙΒΑΔΙΑ ΚΑΙ ΒΟΣΚΟΤΟΠΟΙ": "Μόνιμα λιβάδια και βοσκότοποι",
    "ΛΟΙΠΕΣ ΚΑΛΛΙΕΡΓΟΥΜΕΝΕΣ ΕΚΤΑΣΕΙΣ": "Λοιπές καλλιεργούμενες εκτάσεις", "ΟΙΚΟΓΕΝΕΙΑΚΟΙ ΛΑΧΑΝΟΚΗΠΟΙ": "Οικογενειακοί λαχανόκηποι",
    "ΦΥΤΩΡΙΑ ΥΠΑΙΘΡΙΑ ΚΑΙ ΑΛΛΕΣ ΠΟΛΥΕΤΕΙΣ ΦΥΤΕΙΕΣ": "Φυτώρια υπαίθρια και άλλες πολυετείς φυτείες",
    "ΜΕΙΚΤΕΣ": "Μεικτές εκμεταλλεύσεις",
    # 2016 survey: other classification of land use, quality wines and tree crops than 2023; kept under its own names
    "ΕΤΗΣΙΕΣ ΚΑΛΛΙΕΡΓΕΙΕΣ": "Ετήσιες καλλιέργειες", "ΔΕΝΔΡΩΔΕΙΣ ΚΑΛΛΙΕΡΓΕΙΕΣ": "Δενδρώδεις καλλιέργειες",
    "ΦΥΤΩΡΙΑ ΚΑΡΠΟΦΟΡΩΝ ΔΕΝΔΡΩΝ": "Φυτώρια καρποφόρων δένδρων", "ΟΙΝΟΙ ΠΟΙΟΤΗΤΑΣ": "Οίνοι ποιότητας", "ΛΟΙΠΟΙ ΟΙΝΟΙ": "Λοιποί οίνοι",
    "ΟΠΩΡΟΦΟΡΑ ΔΕΝΔΡΑ ΕΥΚΡΑΤΩΝ ΚΑΛΛΙΕΡΓΕΙΩΝ (ΡΟΔΑΚΙΝΙΕΣ Κ.Λ.Π.)": "Οπωροφόρα δένδρα εύκρατων καλλιεργειών (ροδακινιές κ.λπ.)",
    "ΟΠΩΡΟΦΟΡΑ ΔΕΝΔΡΑ ΥΠΟΤΡΟΠΙΚΗΣ ΠΡΟΕΛΕΥΣΗΣ (ΑΚΤΙΝΙΔΙΑ Κ.Λ.Π.)": "Οπωροφόρα δένδρα υποτροπικής προέλευσης (ακτινίδια κ.λπ.)",
    "ΕΚΜΕΤΑΛΛΕΥΣΕΙΣ ΜΕ ΑΡΔΕΥΘΕΙΣΕΣ ΕΚΤΑΣΕΙΣ": "Σύνολο", "ΑΡΔΕΥΘΕΙΣΕΣ ΕΚΤΑΣΕΙΣ ΚΑΤΑ ΕΙΔΟΣ ΚΑΛΛΙΕΡΓΕΙΑΣ": "",
    "ΠΟΛΥΕΤΕΙΣ ΜΟΝΙΜΕΣ (ΔΕΝΔΡΩΔΕΙΣ)": "Πολυετείς (δενδρώδεις) καλλιέργειες", "ΑΜΠΕΛΙΑ ΚΑΙ ΣΤΑΦΙΔΑΜΠΕΛΑ": "Αμπέλια και σταφιδάμπελα", "ΑΜΙΓΩΣ ΓΕΩΡΓΙΚΕΣ": "Αμιγώς γεωργικές εκμεταλλεύσεις", "ΑΜΙΓΩΣ ΚΤΗΝΟΤΡΟΦΙΚΕΣ": "Αμιγώς κτηνοτροφικές εκμεταλλεύσεις",
    "ΒΙΟΛΟΓΙΚΑ ΒΟΟΕΙΔΗ": "Βιολογικά βοοειδή", "ΒΙΟΛΟΓΙΚΑ ΒΟΥΒΑΛΙΑ": "Βιολογικά βουβάλια", "ΒΙΟΛΟΓΙΚΟΙ ΧΟΙΡΟΙ": "Βιολογικοί χοίροι",
    "ΒΙΟΛΟΓΙΚΑ ΠΡΟΒΑΤΟΕΙΔΗ": "Βιολογικά προβατοειδή", "ΒΙΟΛΟΓΙΕΣ ΑΙΓΕΣ": "Βιολογικές αίγες", "ΒΙΟΛΟΓΙΚΑ ΠΟΥΛΕΡΙΚΑ": "Βιολογικά πουλερικά",
    "ΒΟΟΕΙΔΗ": "Βοοειδή", "ΘΗΛΥΚΑ": "θηλυκά", "ΒΟΥΒΑΛΙΑ": "Βουβάλια", "ΧΟΙΡΟΙ": "Χοίροι", "ΠΡΟΒΑΤΟΕΙΔΗ": "Προβατοειδή", "ΑΙΓΕΣ": "Αίγες",
    "ΠΟΥΛΕΡΙΚΑ": "Πουλερικά", "ΚΟΥΝΕΛΙΑ": "Κουνέλια", "ΙΠΠΟΕΙΔΗ ΚΑΙ ΟΝΟΙ": "Ιπποειδή και όνοι", "ΚΥΨΕΛΕΣ ΜΕΛΙΣΣΩΝ": "Κυψέλες μελισσών", "ΑΛΛΑ ΖΩΑ": "Άλλα ζώα",
}


_LOOKALIKE = str.maketrans("ABEHIKMNOPTXYZ", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖ")  # Latin capitals typed inside Greek words (ΜEΙΚΤΕΣ)


def gkey(text):
    return "".join(ch for ch in fold(text.translate(_LOOKALIKE)) if "α" <= ch <= "ω")


_NAMES = {gkey(k): v for k, v in NAMES.items()}
_DROP_ROOT = {"fs_cereals", "fs_vineyards", "fs_tree_crops", "fs_arable", "fs_land_use", "fs_irrigation"}


def display_path(table_key, path):
    out = []
    if table_key in _DROP_ROOT and len(path) > 1:
        path = path[1:]  # the first header level only repeats the category of the table
    for element in path:
        key = gkey(element)
        if fold(element).startswith("συνολο"):
            out.append("Σύνολο")
        elif key in _NAMES:
            if _NAMES[key]:
                out.append(_NAMES[key])
        else:
            out.append(element)
    return out or ["Σύνολο"]
LABEL_ROW = re.compile(r"ΚΩΔΙΚΟΙ|CODES", re.I)
COUNTRY = re.compile(r"^ΣΥΝΟΛΟ (ΧΩΡΑΣ|ΕΛΛΑΔΑΣ)")


def raw_text(sheet, r, c):
    """Cell text with line breaks removed and runs of spaces (word breaks of letter-spaced titles) marked '|'."""
    value = sheet.get(r, c)
    if value is None:
        return ""
    return re.sub(r"[ \t]{2,}", "|", re.sub(r"[\r\n]+", " ", str(value))).strip()


def despace(text):
    """'Σ Ι Τ Η Ρ Α|Γ Ι Α' -> 'ΣΙΤΗΡΑ ΓΙΑ'; other text unchanged except for the '|' markers."""
    words = []
    for part in text.split("|"):
        tokens = part.split(" ")
        if len(tokens) >= 3 and sum(len(t) == 1 for t in tokens) >= 0.8 * len(tokens):
            part = "".join(tokens)
        words.append(part.strip())
    return " ".join(w for w in words if w)


def tidy(label):
    label = re.sub(r"(?<=[Α-Ω])-\s?(?=[Α-Ω])", "", label)  # line-break hyphens (ΕΚΜΕΤΑΛ-ΛΕΥΣΕΙΣ)
    return clean_label(label)


def measure_of(path):
    """(variable, remaining path) from the header path of a column."""
    folded = [fold(p) for p in path]
    if folded and folded[0].startswith("εκμεταλλευσεισ") and not folded[0].startswith("εκμεταλλευσεισ με"):
        return "holdings", [p for p in path[1:] if not fold(p).startswith("συνολο") or len(path) > 2] or ["Σύνολο"]
    for i in range(len(path) - 1, -1, -1):
        f = folded[i]
        rest = path[:i] + path[i + 1:]
        if f.startswith("εκμεταλλευσεισ") or f.startswith("εκμ/σεισ") or f.startswith("εκμ/σεισ"):
            return "holdings", rest
        if f.startswith("αριθμοσ ζωων"):
            return "animals", rest
        if f.startswith("ζωικεσ μοναδεσ"):
            return "livestock_units", rest
        if f.startswith("αριθμοσ κυψελων"):
            return "hives", rest
        if f == "αρδευθεισεσ εκτασεισ" and i == len(path) - 1 and i > 0:
            return "area", path[:i]  # 2016 irrigation table: the second column under "holdings with irrigated area"
        if f == "εκτασησ" or f == "εκτασι" or f.startswith("εκτασησ") or f == "εκτασε" or f == "εκτασι":
            return "area", rest
        if f.startswith("εκτασ") and i == len(path) - 1 and len(f) <= 7:
            return "area", rest
    if len(path) == 1 and folded[0].startswith("χρησιμουμενη γεωργικη εκτασ"):
        return "area", ["Χρησιμοποιούμενη γεωργική έκταση"]
    return None, path


def find_start(sheet):
    """(row, label column) of the country line; the code columns come before the label."""
    for r in range(sheet.nrows):
        for c in range(4):
            if COUNTRY.match(sheet.text(r, c)):
                return r, c
    return None


def parse_sheet(sheet, edition):
    found = find_start(sheet)
    if not found:
        return None
    start, label_col = found
    label_row = next((r for r in range(start) if any(LABEL_ROW.search(sheet.text(r, c)) for c in range(label_col))), None)
    if label_row is None:
        raise LayoutError("no header row (ΚΩΔΙΚΟΙ / CODES)")
    first = label_col + 1
    # the English name of the area closes the line (COUNTRY TOTAL, ELLADA); the values are the columns before it
    last = next((c - 1 for c in range(label_col + 1, sheet.ncols) if LATIN.search(sheet.text(start, c)) and not GREEK.search(sheet.text(start, c))), None)
    if last is None or last < label_col + 1:
        raise LayoutError("no English area name closing the country line")
    title_row = next((r for r in range(label_row) for c in range(2) if re.match(r"^Πίνακας", sheet.text(r, c))), None)
    title, source_table = "", ""
    if title_row is not None:
        c0 = next(c for c in range(2) if re.match(r"^Πίνακας", sheet.text(title_row, c)))
        title = next((sheet.text(title_row, c) for c in range(c0 + 1, c0 + 3) if sheet.text(title_row, c)), "")
        source_table = re.sub(r"^Πίνακας\s*|[\s.]+$", "", sheet.text(title_row, c0))
    heading = " ".join(sheet.text(r, c) for r in range(label_row) for c in range(4) if GREEK.search(sheet.text(r, c)) or re.search(r"Survey|Statistics", sheet.text(r, c)))
    year = re.search(r"\b(20\d\d)\b", heading)
    ref_year = int(year.group(1)) if year else None
    table_key = next((key for kw, key in TABLE_KEYS if kw in fold(title)), None)
    if not table_key:
        raise LayoutError(f"unknown table: {title!r}")
    units_row = next((r for r in range(label_row) for c in range(label_col)
                      if re.search(r"στρέμμα|Αριθμός|ΑΡΙΘΜΟΣ|Ζωικές", sheet.text(r, c)) and len(sheet.text(r, c)) < 60), None)
    units = ""
    if units_row is not None:
        units = next(sheet.text(units_row, c) for c in range(label_col + 1) if sheet.text(units_row, c))

    from agri_spg06 import header_cells
    grid = header_cells(sheet, label_row, start, lambda r, c: raw_text(sheet, r, c))
    specs, skipped = [], []
    for c in range(first, last + 1):
        greek = []
        for row in grid:
            value = row[c]
            if not value or re.fullmatch(r"\d+(\.0)?", value):
                continue
            label, _ = split_bilingual(despace(value))
            label = tidy(label)
            if label and not label.startswith("ΚΑΤΑΝΟΜΗ ΤΩΝ ΕΚΤΑΣΕΩΝ"):
                greek.append(label)
        path = dedupe(greek)
        variable, rest = measure_of(path) if path else (None, [])
        if variable is None:
            skipped.append({"col": c, "path": path, "reason": "the header names no measure (holdings, area, animals, livestock units)"})
            specs.append(None)
            continue
        if variable == "area" and not re.search(r"στρέμμα", units):
            skipped.append({"col": c, "path": path, "reason": f"area column without a stremma unit line ({units!r})"})
            specs.append(None)
            continue
        rest = display_path(table_key, [p for p in rest if p])
        total = fold(rest[-1]) == "συνολο"
        if total:
            rest[-1] = "Σύνολο"
        specs.append({"col": c, "path": path, "path_en": [], "marker": None, "notes": [], "measure": variable,
                      "unit": UNIT_OF[variable], "qualifier": "", "product_path": rest, "source_path": list(rest),
                      "product_code": table_key + "." + ".".join(slug(p) for p in rest), "is_total": total, "name_en": ""})

    rows, region = [], None
    for r in range(start, sheet.nrows):
        label = sheet.text(r, label_col)
        if any(re.match(r"^\(\d\)", sheet.text(r, c)) for c in range(label_col + 1)):
            break
        cells = [parse_cell(sheet.get(r, c)) for c in range(first, last + 1)]
        if not label or all(s == "blank" for s, _ in cells):
            continue
        if COUNTRY.match(label):
            level, code = "country", "EL"
        elif re.match(r"^(ΒΟΡΕΙΑ|ΚΕΝΤΡΙΚΗ) ΕΛΛΑΔΑ|^ΑΤΤΙΚΗ$|^ΝΗΣΙΑ ΑΙΓΑΙΟΥ", label):
            continue  # NUTS 1 groups of the 2016 tables; not part of the platform's geography
        elif re.match(r"^ΠΕΡΙΦΕΡΕΙΑ ", label):
            code = agri_geo.region_code(label)
            if not code:
                raise LayoutError(f"unknown region: {label!r}")
            level, region = "region", code
        elif re.match(r"^ΠΕΡΙΦΕΡΕΙΑΚΗ ΕΝΟΤΗΤΑ", label):
            number = agri_geo.unit_number(re.sub(r"\s*\(\d\)\s*$", "", re.sub(r"^ΠΕΡΙΦΕΡΕΙΑΚΗ ΕΝΟΤΗΤΑ\s+", "", label)))
            if not number:
                raise LayoutError(f"unknown regional unit: {label!r}")
            if agri_geo.unit_region(number) != region:
                raise LayoutError(f"{label!r} is listed under {region}, expected {agri_geo.unit_region(number)}")
            level, code = "unit", "PE" + number
        else:
            pref = agri_geo.prefecture_code(label)
            if not pref:
                raise LayoutError(f"unknown prefecture: {label!r}")
            if agri_geo.prefecture_region(pref) != region:
                raise LayoutError(f"{label!r} is listed under {region}, expected {agri_geo.prefecture_region(pref)}")
            level, code = "prefecture", "NO" + pref
        rows.append({"level": level, "geo_code": code, "label": label, "cells": cells})
    keep = [i for i, s in enumerate(specs) if s]
    for row in rows:
        row["cells"] = [row["cells"][i] for i in keep]
    return {"sheet": sheet.name, "source_table": source_table, "title": title, "title_en": "", "ref_year": ref_year,
            "table_key": table_key, "units": units, "legend": {}, "columns": [specs[i] for i in keep], "rows": rows,
            "warnings": [], "ref_year_stated": ref_year is not None, "fix": "", "skipped_columns": skipped}


def parse_workbook(path, edition):
    """(tables, notes) like agri_spg06.parse_workbook."""
    tables, notes = [], []
    for sheet in load(path):
        try:
            table = parse_sheet(sheet, edition)
        except LayoutError as error:
            notes.append({"sheet": sheet.name, "severity": "error", "message": str(error)})
            continue
        if table is None:
            continue
        if table["ref_year"] is None or table["ref_year"] not in (edition, edition - 1):
            table["ref_year"] = edition
            table["ref_year_stated"] = False
        tables.append(table)
    return tables, notes


def check_sums(table, tolerance=0.002):
    """Published totals that differ from the sum of their parts: prefectures -> region -> country."""
    issues = []
    rows = table["rows"]
    by_geo = {r["geo_code"]: r for r in rows}
    regions = [r for r in rows if r["level"] == "region"]
    for i, spec in enumerate(table["columns"]):
        def number(row):
            status, value = row["cells"][i]
            return value if status == "ok" else 0.0

        def differs(total, summed):
            return abs(total - summed) > max(tolerance * abs(total), 1.0)

        label = " > ".join(spec["product_path"]) + f" [{spec['measure']}]"
        for region in regions:
            if region["cells"][i][0] != "ok":
                continue
            parts = [r for r in rows if r["level"] == "prefecture" and agri_geo.prefecture_region(r["geo_code"][2:]) == region["geo_code"]]
            parts += [r for r in rows if r["level"] == "unit" and agri_geo.unit_region(r["geo_code"][2:]) == region["geo_code"]]
            if parts and all(p["cells"][i][0] in ("ok", "dash") for p in parts) and differs(number(region), sum(number(p) for p in parts)):
                issues.append({"col": i, "geo": region["geo_code"], "column": label,
                               "message": f"parts add up to {sum(number(p) for p in parts):g}, region total is {number(region):g}"})
        country = by_geo.get("EL")
        if country and regions and country["cells"][i][0] == "ok" and all(r["cells"][i][0] == "ok" for r in regions):
            if differs(number(country), sum(number(r) for r in regions)):
                issues.append({"col": i, "geo": "EL", "column": label,
                               "message": f"regions add up to {sum(number(r) for r in regions):g}, country total is {number(country):g}"})
    return issues
