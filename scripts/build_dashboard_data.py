#!/usr/bin/env python3
"""Generate the embedded dashboard data in archaeological-sites/index.html from the CSV files in data/.

Usage:
    python3 scripts/build_dashboard_data.py           # rewrite the data blocks in archaeological-sites/index.html
    python3 scripts/build_dashboard_data.py --check   # verify the dashboard and the CSVs agree, change nothing

The CSV files are the source of truth. The two <script type="application/json">
blocks in archaeological-sites/index.html are generated from them, so the dashboard and the downloadable
CSVs cannot drift apart.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "archaeological-sites" / "index.html"
SITE_CSV = ROOT / "data" / "archaeological_site_visits_by_site_1998_2026.csv"
UNIT_CSV = ROOT / "data" / "archaeological_site_visits_by_source_unit_1998_2026.csv"

SITE_BLOCK = re.compile(r'(<script id="site-data" type="application/json">)(.*?)(</script>)', re.S)
UNIT_BLOCK = re.compile(r'(<script id="unit-data" type="application/json">)(.*?)(</script>)', re.S)

SITE_FIELDS = [
    "year", "region", "source_unit", "source_prefecture", "site_name_gr", "site_name_en",
    "monument_type", "visitors", "coverage_months", "period_status", "count_basis", "source_site_names",
]
UNIT_FIELDS = [
    "year", "region", "source_unit", "source_prefecture", "visitors", "coverage_months",
    "period_status", "site_sum_visitors", "site_sum_minus_reported",
]
INT_FIELDS = {"year", "coverage_months", "visitors", "site_sum_visitors", "site_sum_minus_reported"}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def convert(row, fields):
    out = {}
    for field in fields:
        value = row[field]
        if field in INT_FIELDS:
            out[field] = None if value == "" else int(value)
        else:
            out[field] = value
    return out


def build_json(rows, fields):
    return json.dumps([convert(r, fields) for r in rows], ensure_ascii=False, separators=(",", ":"))


def embedded(html, pattern):
    match = pattern.search(html)
    if not match:
        sys.exit(f"Missing data block matching {pattern.pattern!r} in {HTML.name}")
    return json.loads(match.group(2))


def same_rows(a, b):
    """Compare two lists of records regardless of row order."""
    def key(rows):
        return sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
    return key(a) == key(b)


def check_totals(site_rows, unit_rows):
    """Each unit-year total must equal the sum of its site rows, as recorded in the source."""
    sums = defaultdict(int)
    for r in site_rows:
        if r["visitors"] not in ("", None):
            sums[(r["year"], r["source_unit"])] += int(r["visitors"])
    problems = []
    for r in unit_rows:
        expected = sums.get((r["year"], r["source_unit"]), 0)
        if int(r["site_sum_visitors"] or 0) != expected:
            problems.append(f'{r["year"]} {r["source_unit"]}: CSV sum {r["site_sum_visitors"]} != site rows {expected}')
    return problems


def main():
    check_only = "--check" in sys.argv[1:]
    site_rows = read_csv(SITE_CSV)
    unit_rows = read_csv(UNIT_CSV)
    site_json = build_json(site_rows, SITE_FIELDS)
    unit_json = build_json(unit_rows, UNIT_FIELDS)

    html = HTML.read_text(encoding="utf-8")

    if check_only:
        problems = []
        if not same_rows(embedded(html, SITE_BLOCK), json.loads(site_json)):
            problems.append("site-data in the dashboard is out of date with the site CSV")
        if not same_rows(embedded(html, UNIT_BLOCK), json.loads(unit_json)):
            problems.append("unit-data in the dashboard is out of date with the source-unit CSV")
        problems += check_totals(site_rows, unit_rows)
        if problems:
            print("\n".join(problems))
            sys.exit(1)
        print(f"OK: {len(site_rows)} site rows, {len(unit_rows)} source-unit rows, data in the dashboard matches the CSVs.")
        return

    html = SITE_BLOCK.sub(lambda m: m.group(1) + site_json + m.group(3), html, count=1)
    html = UNIT_BLOCK.sub(lambda m: m.group(1) + unit_json + m.group(3), html, count=1)
    HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {len(site_rows)} site rows and {len(unit_rows)} source-unit rows to {HTML.name}.")


if __name__ == "__main__":
    main()
