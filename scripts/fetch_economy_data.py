#!/usr/bin/env python3
"""Download the regional economy data from Eurostat and write the CSV files in data/.

Usage:
    python3 scripts/fetch_economy_data.py

Sources (Eurostat, NUTS 2 regions of Greece, the country total and the EU27 average):
    nama_10r_2gdp   Gross domestic product (GDP) at current market prices by NUTS 2 region
    nama_10r_3gva   Gross value added at basic prices by NUTS 3 region (NUTS 2 and country rows)
    nama_10r_2gvagr GDP and GVA in volume by NUTS 2 region (annual real change)

The data are produced from ELSTAT's regional accounts. The CSV files are embedded into
regional-economy/index.html with scripts/build_economy_data.py.
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
    "EU27_2020": "Ευρωπαϊκή Ένωση (ΕΕ27)",
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
GREEK_GEOS = [g for g in REGION_NAMES if g != "EU27_2020"]

GDP_UNITS = {
    "MIO_EUR": "gdp_meur",
    "EUR_HAB": "gdp_per_inhabitant_eur",
    "EUR_HAB_EU27_2020": "gdp_per_inhabitant_pct_eu27",
    "PPS_EU27_2020_HAB": "gdp_pps_per_inhabitant",
    "PPS_HAB_EU27_2020": "gdp_pps_pct_eu27",
}

SECTORS = {
    "A": "Γεωργία, δασοκομία και αλιεία",
    "B-E": "Βιομηχανία (εκτός κατασκευών)",
    "F": "Κατασκευές",
    "G-J": "Εμπόριο, μεταφορές, καταλύματα και εστίαση, πληροφορική και επικοινωνίες",
    "K-N": "Χρηματοοικονομικές, ακίνητα, επιστημονικές και διοικητικές δραστηριότητες",
    "O-U": "Δημόσια διοίκηση, εκπαίδευση, υγεία και λοιπές υπηρεσίες",
}


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


def fetch_gdp():
    table = {}
    for record, value in eurostat("nama_10r_2gdp", geo=list(REGION_NAMES), unit=list(GDP_UNITS)):
        table.setdefault((record["time"], record["geo"]), {})[GDP_UNITS[record["unit"]]] = value
    for record, value in eurostat("nama_10r_2gvagr", geo=GREEK_GEOS, na_item="B1GQ", unit="PCH_PRE"):
        table.setdefault((record["time"], record["geo"]), {})["real_growth_pct"] = value
    fields = [*GDP_UNITS.values(), "real_growth_pct"]
    path = DATA / "economy_eurostat_gdp.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["year", "nuts2", "region", *fields])
        for (year, geo), values in sorted(table.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            writer.writerow([year, geo, REGION_NAMES[geo]] + [("" if values.get(k) is None else values[k]) for k in fields])
    print("wrote", path.name, len(table), "rows")


def fetch_gva():
    rows = {}
    for record, value in eurostat("nama_10r_3gva", geo=GREEK_GEOS, unit="CP_MEUR", nace_r2=["TOTAL", *SECTORS]):
        rows[(record["time"], record["geo"], record["nace_r2"])] = value
    path = DATA / "economy_eurostat_gva_by_sector.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["year", "nuts2", "region", "sector_code", "sector", "gva_meur"])
        for (year, geo, nace), value in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
            writer.writerow([year, geo, REGION_NAMES[geo], nace, "Σύνολο δραστηριοτήτων" if nace == "TOTAL" else SECTORS[nace], value])
    print("wrote", path.name, len(rows), "rows")

    # The six sector groups must add up to the published total (allowing for rounding).
    for (year, geo, nace), total in rows.items():
        if nace != "TOTAL":
            continue
        parts = [rows.get((year, geo, code)) for code in SECTORS]
        if all(p is not None for p in parts) and abs(sum(parts) - total) > max(2.0, 0.002 * total):
            print(f"warning: {geo} {year}: sectors add up to {sum(parts):.1f}, total {total:.1f}")


if __name__ == "__main__":
    fetch_gdp()
    fetch_gva()
