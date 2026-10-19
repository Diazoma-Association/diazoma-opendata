#!/usr/bin/env python3
"""Generate the embedded dashboard data in regional-economy/index.html from the CSV files in data/.

Usage:
    python3 scripts/build_economy_data.py           # rewrite the data block in regional-economy/index.html
    python3 scripts/build_economy_data.py --check   # verify the dashboard and the CSVs agree, change nothing

The CSV files (see scripts/fetch_economy_data.py) are the source of truth. The
<script type="application/json"> block in regional-economy/index.html is generated from them.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HTML = ROOT / "regional-economy" / "index.html"
BLOCK = re.compile(r'(<script id="economy-data" type="application/json">)(.*?)(</script>)', re.S)
INDICATORS = ["gdp_meur", "gdp_per_inhabitant_eur", "gdp_per_inhabitant_pct_eu27", "gdp_pps_per_inhabitant",
              "gdp_pps_pct_eu27", "real_growth_pct"]
SECTORS = ["A", "B-E", "F", "G-J", "K-N", "O-U"]


def read(name):
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value):
    if value in ("", None):
        return None
    return float(value) if "." in value else int(value)


def build():
    names = {}
    gdp = defaultdict(lambda: defaultdict(dict))
    for row in read("economy_eurostat_gdp.csv"):
        names[row["nuts2"]] = row["region"]
        for indicator in INDICATORS:
            value = number(row[indicator])
            if value is not None:
                gdp[row["nuts2"]][indicator][row["year"]] = value

    gva = defaultdict(lambda: defaultdict(dict))
    for row in read("economy_eurostat_gva_by_sector.csv"):
        gva[row["nuts2"]][row["sector_code"]][row["year"]] = number(row["gva_meur"])

    # The regions add up to the country total, and the sector groups to each region's total.
    for year, total in gdp["EL"]["gdp_meur"].items():
        regions = [gdp[c]["gdp_meur"].get(year) for c in gdp if c not in ("EL", "EU27_2020")]
        if all(v is not None for v in regions):
            assert abs(sum(regions) - total) <= 0.002 * total, f"regional GDP of {year} does not add up to the country total"
    for code, sectors in gva.items():
        for year, total in sectors["TOTAL"].items():
            parts = [sectors[s].get(year) for s in SECTORS]
            assert all(p is not None for p in parts), f"missing sector value for {code} {year}"
            assert abs(sum(parts) - total) <= max(2.0, 0.002 * total), f"sectors of {code} {year} do not add up"

    payload = {
        "names": names,
        "sectors": SECTORS,
        "gdp": {code: {i: dict(sorted(v.items())) for i, v in sorted(series.items())} for code, series in sorted(gdp.items())},
        "gva": {code: {s: dict(sorted(v.items())) for s, v in sorted(series.items())} for code, series in sorted(gva.items())},
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
            sys.exit("economy-data in the dashboard is out of date with the CSV files; run scripts/build_economy_data.py")
        print(f"OK: economy data in the dashboard matches the CSVs ({len(generated):,} characters).")
        return
    HTML.write_text(document[:match.start(2)] + generated + document[match.end(2):], encoding="utf-8")
    print(f"wrote {len(generated):,} characters of data into {HTML.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
