#!/usr/bin/env python3
"""Generate the embedded dashboard data in tourism-activity/index.html from the CSV files in data/.

Usage:
    python3 scripts/build_tourism_data.py           # rewrite the data block in tourism-activity/index.html
    python3 scripts/build_tourism_data.py --check   # verify the dashboard and the CSVs agree, change nothing

The CSV files (see scripts/fetch_tourism_data.py) are the source of truth. The
<script type="application/json"> block in tourism-activity/index.html is generated from them.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HTML = ROOT / "tourism-activity" / "index.html"
BLOCK = re.compile(r'(<script id="tourism-data" type="application/json">)(.*?)(</script>)', re.S)


def read(name):
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value):
    return int(value) if value not in ("", None) else None


def build():
    names = {}
    annual = defaultdict(lambda: defaultdict(dict))
    for row in read("tourism_eurostat_nights_annual.csv"):
        names[row["nuts2"]] = row["region"]
        annual[row["nuts2"]][row["residence"]][row["year"]] = number(row["nights"])

    monthly = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [None] * 12)))
    for row in read("tourism_eurostat_nights_monthly.csv"):
        monthly[row["nuts2"]][row["year"]][row["residence"]][int(row["month"]) - 1] = number(row["nights"])

    regions = [[r["accommodation"], r["nuts2"], r["unit"], r["level"], number(r["arrivals_domestic"]),
                number(r["arrivals_foreign"]), number(r["arrivals_total"]), number(r["nights_domestic"]),
                number(r["nights_foreign"]), number(r["nights_total"]), number(r["beds"])]
               for r in read("tourism_elstat_2025_regions.csv")]

    by_month = defaultdict(dict)
    for r in read("tourism_elstat_2025_monthly.csv"):
        by_month[(r["accommodation"], r["residence"])][int(r["month"])] = [number(r["arrivals"]), number(r["nights"])]
    elstat_monthly = {f"{acc}|{res}": [months[m] for m in range(1, 13)] for (acc, res), months in sorted(by_month.items())}

    occupancy = [float(r["bed_occupancy_pct"]) for r in sorted(read("tourism_elstat_2025_occupancy.csv"), key=lambda r: int(r["month"]))]

    origin_rows = read("tourism_elstat_2025_origin.csv")
    grouped = defaultdict(list)
    for r in origin_rows:
        grouped[r["nuts2"]].append(r)
    origin = []
    for code, rows in grouped.items():
        total = number(rows[0]["nights"])
        leaf_sum = 0
        for i, r in enumerate(rows):
            indent = int(r["indent"])
            following = int(rows[i + 1]["indent"]) if i + 1 < len(rows) else 0
            # Leaves are the listed countries and country groups, plus Africa and the undeclared residents.
            leaf = (indent >= 1 and following <= indent) or r["origin"] in ("Σύνολο Αφρικής",) or r["origin"].startswith("Δε δήλωσαν")
            if leaf:
                leaf_sum += number(r["nights"])
            origin.append([code, r["origin"], indent, number(r["arrivals"]), number(r["nights"]), int(leaf)])
        assert leaf_sum == total, f"origin rows of {code} add up to {leaf_sum}, expected {total}"

    payload = {
        "names": names,
        "annual": {code: {res: dict(series) for res, series in sorted(values.items())} for code, values in sorted(annual.items())},
        "monthly": {code: {year: dict(values) for year, values in sorted(years.items())} for code, years in sorted(monthly.items())},
        "regions": regions,
        "elstatMonthly": elstat_monthly,
        "occupancy": occupancy,
        "origin": origin,
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
            sys.exit("tourism-data in the dashboard is out of date with the CSV files; run scripts/build_tourism_data.py")
        print(f"OK: tourism data in the dashboard matches the CSVs ({len(generated):,} characters).")
        return
    HTML.write_text(document[:match.start(2)] + generated + document[match.end(2):], encoding="utf-8")
    print(f"wrote {len(generated):,} characters of data into {HTML.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
