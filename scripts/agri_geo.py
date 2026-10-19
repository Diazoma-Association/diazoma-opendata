"""Greek administrative geography used by the agriculture datasets.

Units are the 74 regional units (περιφερειακές ενότητες) plus Mount Athos, with the codes ELSTAT numbers them
with in its agricultural tables (the ListOfRegions sheet of every SPG06 workbook). `census_unit` links a unit to
the 2021 census files in data/census_2021_population_by_area.csv. Regions are the 13 NUTS 2 regions.

geo_code values: "EL" (country), the NUTS 2 code for a region (EL51 …) and "PE" + ELSTAT unit number for a
regional unit (PE01 … PE74, PE99). Source labels are matched after removing accents, case and punctuation;
ALIASES holds the spellings ELSTAT uses that differ from the display name.
"""

import re
import unicodedata

COUNTRY = ("EL", "Ελλάδα")

REGIONS = {
    "EL51": "Ανατολική Μακεδονία και Θράκη", "EL52": "Κεντρική Μακεδονία", "EL53": "Δυτική Μακεδονία", "EL54": "Ήπειρος",
    "EL61": "Θεσσαλία", "EL62": "Ιόνια Νησιά", "EL63": "Δυτική Ελλάδα", "EL64": "Στερεά Ελλάδα", "EL65": "Πελοπόννησος",
    "EL30": "Αττική", "EL41": "Βόρειο Αιγαίο", "EL42": "Νότιο Αιγαίο", "EL43": "Κρήτη",
}

# (ELSTAT unit number, name as ELSTAT writes it, NUTS 2 region, 2021 census unit code)
UNITS = [
    ("01", "Ροδόπης", "EL51", "11101"),
    ("02", "Δράμας", "EL51", "11102"),
    ("03", "Έβρου", "EL51", "11103"),
    ("04", "Θάσου", "EL51", "11104"),
    ("05", "Καβάλας", "EL51", "11105"),
    ("06", "Ξάνθης", "EL51", "11106"),
    ("07", "Θεσσαλονίκης", "EL52", "11207"),
    ("08", "Ημαθίας", "EL52", "11208"),
    ("09", "Κιλκίς", "EL52", "11209"),
    ("10", "Πέλλας", "EL52", "11210"),
    ("11", "Πιερίας", "EL52", "11211"),
    ("12", "Σερρών", "EL52", "11212"),
    ("13", "Χαλκιδικής", "EL52", "11213"),
    ("14", "Κοζάνης", "EL53", "12114"),
    ("15", "Γρεβενών", "EL53", "12115"),
    ("16", "Καστοριάς", "EL53", "12116"),
    ("17", "Φλώρινας", "EL53", "12117"),
    ("18", "Ιωαννίνων", "EL54", "12218"),
    ("19", "Άρτας", "EL54", "12219"),
    ("20", "Θεσπρωτίας", "EL54", "12220"),
    ("21", "Πρέβεζας", "EL54", "12221"),
    ("22", "Λάρισας", "EL61", "23122"),
    ("23", "Καρδίτσας", "EL61", "23123"),
    ("24", "Μαγνησίας", "EL61", "23124"),
    ("25", "Σποράδων", "EL61", "23125"),
    ("26", "Τρικάλων", "EL61", "23126"),
    ("27", "Φθιώτιδας", "EL64", "23227"),
    ("28", "Βοιωτίας", "EL64", "23228"),
    ("29", "Εύβοιας", "EL64", "23229"),
    ("30", "Ευρυτανίας", "EL64", "23230"),
    ("31", "Φωκίδας", "EL64", "23231"),
    ("32", "Κέρκυρας", "EL62", "24132"),
    ("33", "Ζακύνθου", "EL62", "24133"),
    ("34", "Ιθάκης", "EL62", "24134"),
    ("35", "Κεφαλληνίας", "EL62", "24135"),
    ("36", "Λευκάδας", "EL62", "24136"),
    ("37", "Αχαϊας", "EL63", "24237"),
    ("38", "Αιτωλοακαρνανίας", "EL63", "24238"),
    ("39", "Ηλείας", "EL63", "24239"),
    ("40", "Αρκαδίας", "EL65", "24340"),
    ("41", "Αργολίδας", "EL65", "24341"),
    ("42", "Κορινθίας", "EL65", "24342"),
    ("43", "Λακωνίας", "EL65", "24343"),
    ("44", "Μεσσηνίας", "EL65", "24344"),
    ("45", "Κεντρικού Τομέα Αθηνών", "EL30", "35145"),
    ("46", "Βορείου Τομέα Αθηνών", "EL30", "35146"),
    ("47", "Δυτικού Τομέα Αθηνών", "EL30", "35147"),
    ("48", "Νοτίου Τομέα Αθηνών", "EL30", "35148"),
    ("49", "Ανατολικής Αττικής", "EL30", "35149"),
    ("50", "Δυτικής Αττικής", "EL30", "35150"),
    ("51", "Πειραιώς", "EL30", "35151"),
    ("52", "Νήσων", "EL30", "35152"),
    ("53", "Λέσβου", "EL41", "46153"),
    ("54", "Ικαρίας", "EL41", "46154"),
    ("55", "Λήμνου", "EL41", "46155"),
    ("56", "Σάμου", "EL41", "46156"),
    ("57", "Χίου", "EL41", "46157"),
    ("58", "Σύρου", "EL42", "46258"),
    ("59", "Άνδρου", "EL42", "46259"),
    ("60", "Θήρας", "EL42", "46260"),
    ("61", "Καλύμνου", "EL42", "46261"),
    ("62", "Καρπάθου - Ηρωικής Νήσου Κάσου", "EL42", "46262"),
    ("63", "Κέας - Κύθνου", "EL42", "46263"),
    ("64", "Κω", "EL42", "46264"),
    ("65", "Μήλου", "EL42", "46265"),
    ("66", "Μυκόνου", "EL42", "46266"),
    ("67", "Νάξου", "EL42", "46267"),
    ("68", "Πάρου", "EL42", "46268"),
    ("69", "Ρόδου", "EL42", "46269"),
    ("70", "Τήνου", "EL42", "46270"),
    ("71", "Ηρακλείου", "EL43", "47171"),
    ("72", "Λασιθίου", "EL43", "47172"),
    ("73", "Ρεθύμνου", "EL43", "47173"),
    ("74", "Χανίων", "EL43", "47174"),
    ("99", "Άγιον Όρος", "EL52", "11299"),
]

# Spellings of unit names found in the ELSTAT tables that differ from the names above.
ALIASES = {
    "Αιτωλ/νανίας": "38", "Αιτωλοακαρνανίας": "38", "Καρπάθου - Ηρωικής Νήσου Κάσου": "62", "Κέας - Κύθνου": "63",
    "Ρεθύμνου": "73", "Ρεθύμνης": "73", "Καρπάθου": "62", "Κύθνου": "63", "Αγίου Όρους": "99", "Άγιο Όρος": "99",
}


def normalize(text):
    """Upper case, no accents or punctuation: the key under which source labels are compared."""
    text = unicodedata.normalize("NFD", str(text).upper())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^Α-ΩA-Z0-9/ ]", " ", text)).strip()


def region_name_key(label):
    return normalize(re.sub(r"^\s*Περιφέρεια\s+", "", label, flags=re.I))


_REGION_BY_LABEL = {}
for _code, _name in REGIONS.items():
    _REGION_BY_LABEL[normalize(_name)] = _code
# ELSTAT writes the region in the genitive after "Περιφέρεια".
_GENITIVE = {
    "EL51": "Ανατολικής Μακεδονίας και Θράκης", "EL52": "Κεντρικής Μακεδονίας", "EL53": "Δυτικής Μακεδονίας", "EL54": "Ηπείρου",
    "EL61": "Θεσσαλίας", "EL62": "Ιονίων Νήσων", "EL63": "Δυτικής Ελλάδας", "EL64": "Στερεάς Ελλάδας", "EL65": "Πελοποννήσου",
    "EL30": "Αττικής", "EL41": "Βορείου Αιγαίου", "EL42": "Νοτίου Αιγαίου", "EL43": "Κρήτης",
}
for _code, _name in _GENITIVE.items():
    _REGION_BY_LABEL[normalize(_name)] = _code

_UNIT_BY_LABEL = {}
for _num, _name, _region, _census in UNITS:
    _UNIT_BY_LABEL[normalize(_name)] = _num
for _name, _num in ALIASES.items():
    _UNIT_BY_LABEL[normalize(_name)] = _num
_UNIT = {u[0]: u for u in UNITS}


def region_code(label):
    """NUTS 2 code of a 'Περιφέρεια …' row label, or None."""
    return _REGION_BY_LABEL.get(region_name_key(label))


def unit_number(label):
    """ELSTAT unit number of a regional-unit row label, or None."""
    return _UNIT_BY_LABEL.get(normalize(label))


def unit_region(number):
    return _UNIT[number][2]


def geography():
    """Rows of the geography dimension: (geo_code, level, name_el, parent_code, nuts2, census_unit_code)."""
    rows = [(COUNTRY[0], "country", COUNTRY[1], "", "", "")]
    rows += [(code, "region", name, COUNTRY[0], code, "") for code, name in REGIONS.items()]
    rows += [("PE" + num, "unit", name, region, region, census) for num, name, region, census in UNITS]
    return rows
