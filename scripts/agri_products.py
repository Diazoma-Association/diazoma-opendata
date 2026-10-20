"""Classification of the agricultural products and animals of the ELSTAT tables.

ELSTAT renames and regroups the columns of its tables from year to year ("Ηλιόσπορος" became "Ηλίανθος",
peaches moved from "Οπωροφόρα δένδρα" to "Πυρηνόκαρπα"). Product codes are built from the Greek label of the
column (table key + transliterated label path), after the spelling variants below have been mapped to one name.
Only renames of the same thing are mapped; a definition that really changed keeps a separate product and
is linked, when it is the same crop, through CONTINUES, so that no series is joined silently.

The registry also records, for totals and "Λοιπά" (other) categories, the years in which their content changed
because other categories were added to or removed from their group: such a series must not be read as one
continuous line across that year.
"""

import re
import unicodedata


def fold(text):
    text = unicodedata.normalize("NFD", str(text).lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("ς", "σ")


# One spelling of the same label (applied to every element of a header path). Keys are compared folded.
ELEMENT_ALIASES = {
    "Αγρανάπαυση (1 - 5) ετών": "Αγρανάπαυση",
    "Ηλιόσπορος": "Ηλίανθος",
    "Κολοκύθες για σπόρους πασατέμπου": "Κολοκύθες",
    "Αρωματικά φυτά που καλλιεργούνται": "Αρωματικά φυτά",
    "Κοφτολίβαδα (Σανός)": "Κοφτολίβαδα",
    "Φασολάκια χλωρά": "Φασολάκια",
    "Γλαύκος (Μούστος)": "Γλεύκος (Μούστος)",
    "Πατάτες συγκομιζόμενες": "Πατάτες",
    "την άνοιξη": "Άνοιξης",
    "το καλοκαίρι": "Καλοκαιριού",
    "το φθινόπωρο ή χειμώνα": "Φθινοπώρου και χειμώνα",
    "Άλλες καλλιέργειες: Άνθη - Σπορεία - Φυτώρια": "Καλλωπιστικά φυτά - Σπορεία - Φυτώρια",
    "Δένδρα για ξηρούς και αποξηραμένους καρπούς (ακρόδρυα)": "Ακρόδρυα",
    "Δένδρα για ξηρούς και αποξηραμένους καρπούς": "Ακρόδρυα",
    "Βερυκοκιές": "Βερικοκιές",
    "Λοιπά δένδρα σύνολο": "Λοιπά δένδρα > Σύνολο",
    "Ελαιώνες": "Ελιές",
}
_ELEMENTS = {fold(k): v for k, v in ELEMENT_ALIASES.items()}

# Variants of the qualifier of a production column (what the grapes were used for).
QUALIFIER_ALIASES = {
    "σταφυλιών που γλαυκοποιήθηκαν": "σταφυλιών που γλευκοποιήθηκαν",
    "επιτραπέζιων σταφυlιών": "επιτραπέζιων σταφυλιών",
}
_QUALIFIERS = {fold(k): v for k, v in QUALIFIER_ALIASES.items()}

# Same crop, listed under another group in a later year (the group totals differ, so the codes stay apart).
# {product code: code of the series it continues}
CONTINUES = {
    "tree_areas.pyrinokarpa.rodakinies_nektarinies": "tree_areas.oporofora_dendra.rodakinies",
    "tree_areas.pyrinokarpa.verikokies": "tree_areas.oporofora_dendra.verikokies",
    "tree_areas.pyrinokarpa.kerasies": "tree_areas.oporofora_dendra.kerasies",
}


def canonical_path(table_key, path):
    out = []
    for element in path:
        name = _ELEMENTS.get(fold(element), element)
        out.extend(part.strip() for part in name.split(" > "))
    # the olive groves listed under "Λοιπά δένδρα" in early years are the olives of the later tables
    if table_key == "tree_areas" and [fold(p) for p in out] == ["λοιπα δενδρα", "ελιεσ"]:
        out = ["Ελιές"]
    return out


def canonical_qualifier(qualifier):
    return _QUALIFIERS.get(fold(qualifier), qualifier)
