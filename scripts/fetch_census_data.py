#!/usr/bin/env python3
"""Download the 2021 census tables from ELSTAT and write the CSV files in data/.

Usage:
    python3 scripts/fetch_census_data.py

Source: ELSTAT, Population-Housing Census 2021, published tables
    https://www.statistics.gr/el/statistics/-/publication/SAM03/2021
    B01  Permanent population by sex and age group, municipalities (with regions and regional units)
    B02  Permanent population by age group and level of education, municipalities (same hierarchy)

The ELSTAT spreadsheets are kept under data/census_2021/ so the CSVs can be rebuilt without the
website. Needs openpyxl (pip install openpyxl). The dashboard data is embedded with
scripts/build_census_data.py.
"""

import csv
import html
import re
import subprocess
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "census_2021"
PUBLICATION_URL = "https://www.statistics.gr/el/statistics/-/publication/SAM03/2021"
DOCS = {
    "B01_population_by_sex_and_age_municipalities.xlsx": "568512",
    "B02_population_by_age_and_education_municipalities.xlsx": "568511",
}

REGION_NAMES = {
    "EL30": "Αττική", "EL41": "Βόρειο Αιγαίο", "EL42": "Νότιο Αιγαίο", "EL43": "Κρήτη",
    "EL51": "Ανατολική Μακεδονία και Θράκη", "EL52": "Κεντρική Μακεδονία", "EL53": "Δυτική Μακεδονία",
    "EL54": "Ήπειρος", "EL61": "Θεσσαλία", "EL62": "Ιόνια Νησιά", "EL63": "Δυτική Ελλάδα",
    "EL64": "Στερεά Ελλάδα", "EL65": "Πελοπόννησος",
}
# ELSTAT writes the region names in capitals and without accents.
REGION_CODES = {
    "ΑΝΑΤΟΛΙΚΗΣ ΜΑΚΕΔΟΝΙΑΣ ΚΑΙ ΘΡΑΚΗΣ": "EL51", "ΚΕΝΤΡΙΚΗΣ ΜΑΚΕΔΟΝΙΑΣ": "EL52", "ΔΥΤΙΚΗΣ ΜΑΚΕΔΟΝΙΑΣ": "EL53",
    "ΗΠΕΙΡΟΥ": "EL54", "ΘΕΣΣΑΛΙΑΣ": "EL61", "ΙΟΝΙΩΝ ΝΗΣΩΝ": "EL62", "ΔΥΤΙΚΗΣ ΕΛΛΑΔΑΣ": "EL63",
    "ΣΤΕΡΕΑΣ ΕΛΛΑΔΑΣ": "EL64", "ΠΕΛΟΠΟΝΝΗΣΟΥ": "EL65", "ΑΤΤΙΚΗΣ": "EL30", "ΒΟΡΕΙΟΥ ΑΙΓΑΙΟΥ": "EL41",
    "ΝΟΤΙΟΥ ΑΙΓΑΙΟΥ": "EL42", "ΚΡΗΤΗΣ": "EL43",
}
LEVELS = {"0": "country", "3": "region", "4": "unit", "5": "municipality"}
AGE_GROUPS = ["0-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80+"]
EDU_AGE_GROUPS = ["0-14", "15-29", "30-44", "45-59", "60-74", "75+"]
EDUCATION = ["tertiary", "post_secondary", "upper_secondary", "lower_secondary", "primary", "below_primary", "unclassified"]


def get(url):
    """Fetch a URL with curl; the ELSTAT site answers plain urllib requests with a redirect to http."""
    result = subprocess.run(["curl", "-sSL", "--fail", "--max-time", "180", url], capture_output=True)
    if result.returncode != 0:
        sys.exit(f"download failed ({result.returncode}): {url}\n{result.stderr.decode('utf-8', 'ignore')}")
    return result.stdout


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    page = get(PUBLICATION_URL).decode("utf-8", "ignore")
    links = {m.group(2): html.unescape(m.group(1)) for m in re.finditer(r'href="([^"]*documentID=(\d+)[^"]*)"', page)}
    for filename, doc_id in DOCS.items():
        target = RAW / filename
        if target.exists():
            continue
        if doc_id not in links:
            sys.exit(f"ELSTAT document {doc_id} ({filename}) not found on {PUBLICATION_URL}")
        target.write_bytes(get(links[doc_id]))
        print("downloaded", filename)


def clean(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def hierarchy(rows):
    """Region (NUTS 2) of every area, derived from the geographic codes and the region names."""
    regions = {}
    for level, code, name in rows:
        if level == "region":
            label = clean(name).upper().removeprefix("ΠΕΡΙΦΕΡΕΙΑ ").strip()
            if label not in REGION_CODES:
                sys.exit(f"unknown region name: {name!r}")
            regions[code] = REGION_CODES[label]
    return regions


def area_fields(level, code, regions):
    nuts2 = "" if level == "country" else regions[code[:3]]
    unit = code[:5] if level in ("unit", "municipality") else ""
    return nuts2, unit


def parse_population():
    sheet = openpyxl.load_workbook(RAW / "B01_population_by_sex_and_age_municipalities.xlsx", data_only=True, read_only=True).worksheets[0]
    areas = []
    for row in sheet.iter_rows(min_row=7, values_only=True):
        level = LEVELS.get(str(row[0])) if row[0] is not None else None
        if level and isinstance(row[3], (int, float)):
            areas.append((level, str(row[1]), clean(row[2]), row))
    regions = hierarchy([(level, code, name) for level, code, name, _ in areas])
    path = DATA / "census_2021_population_by_area.csv"
    header = ["level", "code", "name", "nuts2", "unit_code", "total", "male", "female"]
    header += [f"{sex}_{age}" for sex in ("both", "male", "female") for age in AGE_GROUPS]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for level, code, name, row in areas:
            nuts2, unit = area_fields(level, code, regions)
            ages = [row[4 + i] for i in range(9)] + [row[14 + i] for i in range(9)] + [row[24 + i] for i in range(9)]
            writer.writerow([level, code, name, nuts2, unit, row[3], row[13], row[23], *ages])
    print("wrote", path.name, len(areas), "rows")
    return regions


def parse_education(regions):
    sheet = openpyxl.load_workbook(RAW / "B02_population_by_age_and_education_municipalities.xlsx", data_only=True, read_only=True).worksheets[0]
    path = DATA / "census_2021_education_by_age.csv"
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["level", "code", "name", "nuts2", "unit_code", "age_group", "total", *EDUCATION])
        area = None
        for row in sheet.iter_rows(min_row=6, values_only=True):
            if row[0] is None or not isinstance(row[3], (int, float)):
                continue
            level, code, label = LEVELS.get(str(row[0])), str(row[1]), clean(row[2])
            if level is None:
                continue
            if label in EDU_AGE_GROUPS:
                age = label
            else:
                area, age = (level, code, label), "ALL"
            nuts2, unit = area_fields(area[0], area[1], regions)
            writer.writerow([area[0], area[1], area[2], nuts2, unit, age, row[3], *row[4:11]])
            count += 1
    print("wrote", path.name, count, "rows")


if __name__ == "__main__":
    download()
    parse_education(parse_population())
