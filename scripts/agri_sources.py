"""The ELSTAT publications the agriculture tables are built from, and where their files live.

One entry per publication: the code of the ELSTAT page (…/publication/<code>/<year>), the folder with the
downloaded spreadsheets and their manifest, the parser module, and which editions are imported. Everything that
handles several publications (fetch, import, verification, dashboards) reads this list.
"""

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "agriculture"
PAGE = "https://www.statistics.gr/el/statistics/-/publication/{code}"

SOURCES = {
    "SPG06": {
        "dir": "spg06", "module": "agri_spg06", "title": "Ετήσια Γεωργική Στατιστική Έρευνα", "frequency": "Ετήσια",
        "description": "Εκτάσεις και παραγωγή καλλιεργειών ανά Περιφέρεια και Περιφερειακή Ενότητα.",
        "first_year": 2011, "editions": None, "release": lambda title: "Ετήσια Γεωργική Στατιστική Έρευνα" in title,
    },
    "SPG32": {
        "dir": "spg32", "module": "agri_survey", "title": "Έρευνα Διάρθρωσης Γεωργικών και Κτηνοτροφικών Εκμεταλλεύσεων: εκμεταλλεύσεις και εκτάσεις",
        "frequency": "Περιοδική (δειγματοληπτική ή απογραφική)",
        "description": "Γεωργικές εκμεταλλεύσεις και εκτάσεις ανά είδος καλλιέργειας· Περιφέρειες και Περιφερειακές Ενότητες (2016) ή Νομοί (2023).",
        "first_year": 2016, "editions": [2016, 2023],
        "release": lambda title: title.strip().rstrip(".") == "Έρευνα Διάρθρωσης Γεωργικών και Κτηνοτροφικών Εκμεταλλεύσεων",
    },
    "SPK12": {
        "dir": "spk12", "module": "agri_survey", "title": "Έρευνα Διάρθρωσης Γεωργικών και Κτηνοτροφικών Εκμεταλλεύσεων: ζωικό κεφάλαιο",
        "frequency": "Περιοδική (δειγματοληπτική ή απογραφική)",
        "description": "Κτηνοτροφικές εκμεταλλεύσεις, ζώα και ζωικές μονάδες ανά είδος· Περιφέρειες και Περιφερειακές Ενότητες (2016) ή Νομοί (2023).",
        "first_year": 2016, "editions": [2016, 2023],
        "release": lambda title: title.strip().rstrip(".") == "Έρευνα Διάρθρωσης Γεωργικών και Κτηνοτροφικών Εκμεταλλεύσεων",
    },
    "SPG12": {
        "dir": "spg12", "module": "agri_survey", "title": "Έρευνα Διάρθρωσης Γεωργικών και Κτηνοτροφικών Εκμεταλλεύσεων: απασχόληση",
        "frequency": "Περιοδική (δειγματοληπτική ή απογραφική)",
        "description": "Απασχολούμενοι, ημέρες εργασίας, κάτοχοι εκμεταλλεύσεων ανά ηλικία και φύλο· Περιφέρειες και Περιφερειακές Ενότητες (2016) ή Νομοί (2023).",
        "first_year": 2016, "editions": [2016, 2023],
        "release": lambda title: title.strip().rstrip(".") == "Έρευνα Διάρθρωσης Γεωργικών και Κτηνοτροφικών Εκμεταλλεύσεων",
    },
    "DKT33": {
        "dir": "dkt33", "module": "agri_indices", "title": "Ετήσιοι δείκτες αμοιβής συντελεστών παραγωγής στη γεωργία-κτηνοτροφία",
        "frequency": "Ετήσια", "description": "Εθνικοί αριθμοδείκτες (έτος βάσης 2020=100) αμοιβής εργασίας, γης και κεφαλαίου στη γεωργία, 2000–2025.",
        "first_year": 2000, "editions": None, "latest_only": True,
        "release": lambda title: "Δείκτες Τιμών Αμοιβής Συντελεστών Παραγωγής" in title,
    },
    "DKT30": {
        "dir": "dkt30", "module": "agri_indices", "title": "Δείκτες τιμών εισροών και εκροών στη γεωργία-κτηνοτροφία",
        "frequency": "Μηνιαία", "description": "Εθνικοί αριθμοδείκτες (έτος βάσης 2020=100) τιμών εκροών, εκροών μερικών προϊόντων και εισροών, από το 2000.",
        "first_year": 2000, "editions": None, "latest_only": True,
        "release": lambda title: "Δείκτες Τιμών Εισροών-Εκροών στη Γεωργία" in title,
    },
    "SPK33": {
        "dir": "spk33", "module": "agri_livestock", "title": "Ετήσια Στατιστική Έρευνα Ζωικού Κεφαλαίου και Κτηνοτροφικής Παραγωγής",
        "frequency": "Ετήσια", "description": "Ζωικό κεφάλαιο, γεννήσεις, αρμεγμένα ζώα και κτηνοτροφικά προϊόντα ανά Περιφέρεια και Περιφερειακή Ενότητα.",
        "first_year": 2011, "editions": None, "release": None,
    },
    "SEL61": {
        "dir": "sel61", "module": "agri_accounts", "title": "Οικονομικοί Λογαριασμοί Γεωργίας κατά γεωγραφική ζώνη και περιφέρεια",
        "frequency": "Ετήσια", "description": "Αξία γεωργικής παραγωγής, ενδιάμεση ανάλωση, προστιθέμενη αξία και εισόδημα του γεωργικού κλάδου, σε εκατομμύρια ευρώ, ανά γεωγραφική ζώνη (NUTS 1) και περιφέρεια (NUTS 2).",
        "first_year": 1995, "editions": None, "release": None,
    },
}


def parser(code):
    """The parser module of a publication (parse_workbook, check_sums, CATEGORIES)."""
    return importlib.import_module(SOURCES[code]["module"])


def raw_dir(code):
    return DATA / SOURCES[code]["dir"]


def manifest_path(code):
    return raw_dir(code) / "manifest.csv"


def categories():
    """table_key -> category name of every publication, in the order of the tables."""
    out = {}
    for code in SOURCES:
        out.update(parser(code).CATEGORIES)
    return out

