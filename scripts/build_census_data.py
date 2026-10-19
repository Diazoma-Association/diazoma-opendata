#!/usr/bin/env python3
"""Generate the embedded dashboard data in demographics/census-2021/index.html from the CSV files in data/.

Usage:
    python3 scripts/build_census_data.py           # rewrite the data block in demographics/census-2021/index.html
    python3 scripts/build_census_data.py --check   # verify the dashboard and the CSVs agree, change nothing

The CSV files (see scripts/fetch_census_data.py) are the source of truth. The
<script type="application/json"> block in the dashboard page is generated from them.
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HTML = ROOT / "demographics" / "census-2021" / "index.html"
BLOCK = re.compile(r'(<script id="census-data" type="application/json">)(.*?)(</script>)', re.S)
LEVELS = ["country", "region", "unit", "municipality"]
AGE_GROUPS = ["0-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80+"]
EDU_AGE_GROUPS = ["ALL", "0-14", "15-29", "30-44", "45-59", "60-74", "75+"]
EDUCATION = ["tertiary", "post_secondary", "upper_secondary", "lower_secondary", "primary", "below_primary", "unclassified"]
# ELSTAT applies statistical confidentiality to the 2021 census tables, so the parts of an area can
# differ slightly from its published total. Larger differences indicate a parsing error.
TOLERANCE = 25
REGION_NAMES = {
    "EL30": "Αττική", "EL41": "Βόρειο Αιγαίο", "EL42": "Νότιο Αιγαίο", "EL43": "Κρήτη",
    "EL51": "Ανατολική Μακεδονία και Θράκη", "EL52": "Κεντρική Μακεδονία", "EL53": "Δυτική Μακεδονία",
    "EL54": "Ήπειρος", "EL61": "Θεσσαλία", "EL62": "Ιόνια Νησιά", "EL63": "Δυτική Ελλάδα",
    "EL64": "Στερεά Ελλάδα", "EL65": "Πελοπόννησος",
}


def read(name):
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build():
    areas = []
    for row in read("census_2021_population_by_area.csv"):
        ages = [int(row[f"{sex}_{age}"]) for sex in ("both", "male", "female") for age in AGE_GROUPS]
        total, male, female = int(row["total"]), int(row["male"]), int(row["female"])
        assert abs(male + female - total) <= TOLERANCE, f"sexes of {row['name']} do not add up"
        assert abs(sum(ages[:9]) - total) <= TOLERANCE, f"age groups of {row['name']} do not add up"
        areas.append([LEVELS.index(row["level"]), row["code"], row["name"], row["nuts2"], row["unit_code"], total, male, female, ages])

    education = {}
    for row in read("census_2021_education_by_age.csv"):
        values = [int(row["total"])] + [int(row[k]) for k in EDUCATION]
        assert abs(sum(values[1:]) - values[0]) <= TOLERANCE, f"education of {row['name']} {row['age_group']} does not add up"
        education.setdefault(row["code"], {})[row["age_group"]] = values
    education = {code: [groups[g] for g in EDU_AGE_GROUPS] for code, groups in education.items()}

    totals = {a[1]: a[5] for a in areas}
    for code, groups in education.items():
        assert groups[0][0] == totals[code], f"population and education totals of area {code} differ"
    by_unit = {}
    for a in areas:
        if a[0] == 3:
            by_unit[a[4]] = by_unit.get(a[4], 0) + a[5]
    for unit, total in by_unit.items():
        assert abs(total - totals[unit]) <= TOLERANCE, f"municipalities of unit {unit} do not add up"

    payload = {"regions": REGION_NAMES, "ages": AGE_GROUPS, "education": EDUCATION, "areas": areas, "edu": education}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def main():
    document = HTML.read_text(encoding="utf-8")
    match = BLOCK.search(document)
    if not match:
        sys.exit(f"no data block found in {HTML}")
    generated = build()
    if "--check" in sys.argv:
        if match.group(2).strip() != generated:
            sys.exit("census-data in the dashboard is out of date with the CSV files; run scripts/build_census_data.py")
        print(f"OK: census data in the dashboard matches the CSVs ({len(generated):,} characters).")
        return
    HTML.write_text(document[:match.start(2)] + generated + document[match.end(2):], encoding="utf-8")
    print(f"wrote {len(generated):,} characters of data into {HTML.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
