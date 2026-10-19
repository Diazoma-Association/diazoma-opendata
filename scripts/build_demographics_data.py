#!/usr/bin/env python3
"""Generate the embedded dashboard data in demographics/index.html from the CSV files in data/.

Usage:
    python3 scripts/build_demographics_data.py           # rewrite the data block in demographics/index.html
    python3 scripts/build_demographics_data.py --check   # verify the dashboard and the CSVs agree, change nothing

The CSV files (see scripts/fetch_demographics_data.py) are the source of truth. The
<script type="application/json"> block in demographics/index.html is generated from them.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HTML = ROOT / "demographics" / "index.html"
BLOCK = re.compile(r'(<script id="demographics-data" type="application/json">)(.*?)(</script>)', re.S)
AGE_GROUPS = [f"{a}-{a + 4}" for a in range(0, 85, 5)] + ["85+"]
INDICATORS = ["population_jan", "births", "deaths", "natural_change", "net_migration", "total_change",
              "birth_rate", "death_rate", "natural_change_rate", "net_migration_rate"]


def read(name):
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value):
    if value in ("", None):
        return None
    return float(value) if "." in value else int(value)


def build():
    names = {}
    balance = defaultdict(lambda: defaultdict(dict))
    for row in read("demographics_eurostat_regional_balance.csv"):
        names[row["nuts2"]] = row["region"]
        for indicator in INDICATORS:
            value = number(row[indicator])
            if value is not None:
                balance[row["nuts2"]][indicator][row["year"]] = value

    age = defaultdict(lambda: defaultdict(lambda: {"M": [0] * len(AGE_GROUPS), "F": [0] * len(AGE_GROUPS)}))
    for row in read("demographics_eurostat_population_age_sex.csv"):
        age[row["nuts2"]][row["year"]][row["sex"]][AGE_GROUPS.index(row["age_group"])] = int(row["population"])

    for code, series in balance.items():
        for year, births in series["births"].items():
            expected = births - series["deaths"][year]
            assert expected == series["natural_change"][year], f"natural change of {code} {year} is not births minus deaths"

    payload = {
        "names": names,
        "groups": AGE_GROUPS,
        "balance": {code: {i: dict(sorted(v.items())) for i, v in sorted(series.items())} for code, series in sorted(balance.items())},
        "age": {code: {year: values for year, values in sorted(years.items())} for code, years in sorted(age.items())},
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def main():
    document = HTML.read_text(encoding="utf-8")
    match = BLOCK.search(document)
    if not match:
        sys.exit(f"no data block found in {HTML}")
    generated = build()
    if "--check" in sys.argv:
        if match.group(2).strip() != generated:
            sys.exit("demographics-data in the dashboard is out of date with the CSV files; run scripts/build_demographics_data.py")
        print(f"OK: demographics data in the dashboard matches the CSVs ({len(generated):,} characters).")
        return
    HTML.write_text(document[:match.start(2)] + generated + document[match.end(2):], encoding="utf-8")
    print(f"wrote {len(generated):,} characters of data into {HTML.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
