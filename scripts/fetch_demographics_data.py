#!/usr/bin/env python3
"""Download the regional demographic data from Eurostat and write the CSV files in data/.

Usage:
    python3 scripts/fetch_demographics_data.py

Sources (Eurostat, NUTS 2 regions of Greece and the country total):
    demo_r_gind3   Population change - demographic balance and crude rates at regional level
                   (population on 1 January, live births, deaths, natural change, net migration)
    demo_r_d2jan   Population on 1 January by age, sex and NUTS 2 region
                   (region-years with incomplete age detail are left out)

The data are produced from ELSTAT's population and vital statistics. The CSV files are embedded
into demographics/index.html with scripts/build_demographics_data.py.
"""

import csv
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

REGION_NAMES = {
    "EL": "Σύνολο Ελλάδας",
    "EL30": "Αττική",
    "EL41": "Βόρειο Αιγαίο",
    "EL42": "Νότιο Αιγαίο",
    "EL43": "Κρήτη",
    "EL51": "Ανατολική Μακεδονία και Θράκη",
    "EL52": "Κεντρική Μακεδονία",
    "EL53": "Δυτική Μακεδονία",
    "EL54": "Ήπειρος",
    "EL61": "Θεσσαλία",
    "EL62": "Ιόνια Νησιά",
    "EL63": "Δυτική Ελλάδα",
    "EL64": "Στερεά Ελλάδα",
    "EL65": "Πελοπόννησος",
}

INDICATORS = {
    "JAN": "population_jan",
    "LBIRTH": "births",
    "DEATH": "deaths",
    "NATGROW": "natural_change",
    "CNMIGRAT": "net_migration",
    "GROW": "total_change",
    "GBIRTHRT": "birth_rate",
    "GDEATHRT": "death_rate",
    "NATGROWRT": "natural_change_rate",
    "CNMIGRATRT": "net_migration_rate",
}

AGE_GROUPS = [f"{a}-{a + 4}" for a in range(0, 85, 5)] + ["85+"]


def get(url):
    """Fetch a URL with curl (the environment's proxy is configured for it)."""
    result = subprocess.run(["curl", "-sSL", "--fail", "--max-time", "180", url], capture_output=True)
    if result.returncode != 0:
        sys.exit(f"download failed ({result.returncode}): {url}\n{result.stderr.decode('utf-8', 'ignore')}")
    return result.stdout


def eurostat(dataset, **filters):
    params = [("format", "JSON"), ("lang", "EN")]
    for key, values in filters.items():
        params += [(key, value) for value in (values if isinstance(values, list) else [values])]
    data = json.loads(get(f"{EUROSTAT}/{dataset}?{urllib.parse.urlencode(params)}"))
    ids, sizes = data["id"], data["size"]
    positions = {dim: list(data["dimension"][dim]["category"]["index"]) for dim in ids}
    for flat, value in data["value"].items():
        flat, record = int(flat), {}
        for dim, size in reversed(list(zip(ids, sizes))):
            flat, index = divmod(flat, size)
            record[dim] = positions[dim][index]
        yield record, value


def age_group(code):
    if code in ("TOTAL", "UNK"):
        return None
    if code == "Y_LT1":
        return AGE_GROUPS[0]
    if code == "Y_OPEN":
        return AGE_GROUPS[-1]
    years = int(code[1:])
    return AGE_GROUPS[min(years // 5, len(AGE_GROUPS) - 1)]


def fetch_balance():
    table = {}
    for record, value in eurostat("demo_r_gind3", geo=list(REGION_NAMES), indic_de=list(INDICATORS)):
        table.setdefault((record["time"], record["geo"]), {})[INDICATORS[record["indic_de"]]] = value
    fields = ["year", "nuts2", "region", *INDICATORS.values()]
    path = DATA / "demographics_eurostat_regional_balance.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        for (year, geo), values in sorted(table.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            writer.writerow([year, geo, REGION_NAMES[geo]] + [("" if values.get(k) is None else values[k]) for k in fields[3:]])
    print("wrote", path.name, len(table), "rows")


def fetch_age_sex():
    regions = [g for g in REGION_NAMES if g != "EL"]
    totals, listed = {}, {}
    for record, value in eurostat("demo_r_d2jan", geo=regions, sex=["M", "F"]):
        key = (record["time"], record["geo"], record["sex"])
        if record["age"] == "TOTAL":
            totals[key] = int(value)
            continue
        group = age_group(record["age"])
        if group is not None:
            listed.setdefault(key, {})
            listed[key][group] = listed[key].get(group, 0) + int(value)

    # Keep a region and year only when the age groups add up to the published total. Eurostat has
    # partial age detail for some regions in some years (1990 and 2011), which would distort sums.
    complete = {}
    for key, groups in listed.items():
        total = totals.get(key)
        if total and abs(sum(groups.values()) - total) <= 0.005 * total:
            complete[key] = groups
        else:
            print(f"skipped {key[1]} {key[0]} {key[2]}: incomplete age detail")

    rows = {(year, geo, sex): groups for (year, geo, sex), groups in complete.items()}
    # The country total is the sum of the regions, only for years where all of them are complete.
    for year in sorted({k[0] for k in rows}):
        for sex in ("M", "F"):
            parts = [rows.get((year, geo, sex)) for geo in regions]
            if all(parts):
                rows[(year, "EL", sex)] = {g: sum(part[g] for part in parts) for g in AGE_GROUPS}

    path = DATA / "demographics_eurostat_population_age_sex.csv"
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["year", "nuts2", "region", "sex", "age_group", "population"])
        for (year, geo, sex), groups in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
            for group in AGE_GROUPS:
                writer.writerow([year, geo, REGION_NAMES[geo], sex, group, groups.get(group, 0)])
                count += 1
    print("wrote", path.name, count, "rows")


if __name__ == "__main__":
    fetch_balance()
    fetch_age_sex()
