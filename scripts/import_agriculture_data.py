#!/usr/bin/env python3
"""Import the ELSTAT Annual Agricultural Survey tables (SPG06) into the agriculture statistics tables.

Usage:
    python3 scripts/import_agriculture_data.py                    # every file listed in data/agriculture/spg06/manifest.csv
    python3 scripts/import_agriculture_data.py --years 2024       # one publication year
    python3 scripts/import_agriculture_data.py --file table.xlsx --year 2025 [--stage final] [--publication-date 2026-06-30]
                                                                  # a spreadsheet downloaded by hand
    python3 scripts/import_agriculture_data.py --dry-run          # parse and report, write nothing
    python3 scripts/import_agriculture_data.py --rebuild          # start from empty tables (checks reproducibility)

The platform has no database server, so the tables are CSV files in data/agriculture/ with a fixed schema (see
data/README.md): one row per statistic in agri_observations.csv and dimension tables for geography, products,
variables, sources and publications. An import is a merge, never a replacement:

* a statistic is identified by (table, reference year, geography, product, variable, qualifier);
* the same value from another file is a duplicate and is not stored twice;
* a different value from a later publication updates the row (new last_updated) and the previous row is kept in
  agri_observation_revisions.csv; a different value from an earlier publication is kept there only;
* statistics of other years and tables are never touched, so older publications survive a re-import.

Every run appends a summary to agri_import_log.csv, and agri_import_issues.csv lists what was skipped or
looks wrong in each file (stale sheets, columns that could not be read, totals that differ from their parts).
Values are stored as published: a dash is status "dash", an empty cell "blank", and neither becomes a zero.
"""

import argparse
import csv
import hashlib
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import agri_geo
import agri_products
import agri_spg06
import fetch_agriculture_data as fetch
from agri_spg06 import CATEGORIES, parse_workbook, check_sums

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "agriculture" / "spg06"
OUT = ROOT / "data" / "agriculture"
MANIFEST = RAW / "manifest.csv"
DATASET = "SPG06"

OBS = ["dataset", "table_key", "ref_year", "pub_year", "geo_code", "product_code", "variable", "qualifier", "value", "unit",
       "status", "stage", "flags", "source_doc", "last_updated"]
REVISIONS = OBS + ["superseded_on", "superseded_by"]
PUBLICATIONS = ["dataset", "edition", "pub_year", "doc_id", "sheet", "source_table", "table_key", "ref_year", "title", "unit_line", "stage",
                "publication_date", "sha256", "imported_at", "columns", "rows", "note"]
ISSUES = ["dataset", "edition", "doc_id", "sheet", "severity", "code", "message"]
LOG = ["run_at", "command", "files", "tables", "inserted", "updated", "unchanged", "duplicates", "kept_as_revision",
       "unit_mismatch", "errors", "warnings"]
PRODUCTS = ["product_code", "dataset", "table_key", "category", "subcategory", "name_el", "name_en", "path", "is_total",
            "is_residual", "continues", "series_breaks", "first_year", "last_year", "source_labels"]
GEO = ["geo_code", "level", "name_el", "parent_code", "nuts2", "census_unit_code"]
VARIABLES = [
    ("area", "Καλλιεργούμενη έκταση", "stremma", "στρέμματα", "Χρησιμοποιείται για έκταση. 1 στρέμμα = 0,1 εκτάριο."),
    ("production", "Παραγωγή", "tonne", "τόνοι", "Ποσότητα προϊόντος στη μονάδα που δημοσιεύει η πηγή."),
    ("trees_total", "Συνολικός αριθμός δένδρων", "tree", "δένδρα", "Αριθμός δένδρων."),
    ("trees_regular", "Δένδρα κανονικών δενδρώνων", "tree", "δένδρα", "Αριθμός δένδρων σε κανονικούς δενδρώνες."),
]
DATASETS = [(
    DATASET, "Ετήσια Γεωργική Στατιστική Έρευνα", "ΕΛΣΤΑΤ", "https://www.statistics.gr/el/statistics/-/publication/SPG06",
    "Ετήσια", "Εκτάσεις και παραγωγή καλλιεργειών ανά Περιφέρεια και Περιφερειακή Ενότητα.")]
DATASET_FIELDS = ["dataset", "title", "publisher", "url", "frequency", "description"]


# ---------------------------------------------------------------- files

def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value):
    """A value as the shortest exact text: integers without a decimal part, others to three decimals."""
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{round(float(value), 3):.3f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------- manifest

def manifest_entries(years):
    rows = read_csv(MANIFEST)
    entries = [r for r in rows if not years or int(r["edition"]) in years]
    return sorted(entries, key=lambda r: (int(r["edition"]), r["doc_id"]))


def add_manual_file(path, year, stage, publication_date):
    """Copy a hand-downloaded spreadsheet next to the others and register it in the manifest."""
    path = Path(path)
    digest = sha256(path)
    ext = "xlsx" if path.read_bytes()[:2] == b"PK" else "xls"
    doc_id = f"manual-{digest[:10]}"
    target = RAW / str(year) / f"{doc_id}.{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    rows = read_csv(MANIFEST)
    rows = [r for r in rows if not (r["edition"] == str(year) and r["doc_id"] == doc_id)]
    rows.append({"dataset": DATASET, "edition": year, "doc_id": doc_id, "filename": target.name, "title": path.name,
                 "format": ext, "sha256": digest, "bytes": target.stat().st_size, "source_page": "manual upload",
                 "stage": stage, "publication_date": publication_date or "", "downloaded_at": date.today().isoformat()})
    write_csv(MANIFEST, fetch.FIELDS, sorted(rows, key=lambda r: (int(r["edition"]), r["doc_id"])))
    return doc_id


# ---------------------------------------------------------------- one workbook -> observation rows

def observations_of(table, entry, flags_by_cell):
    """Observation dicts of one parsed table, in file order."""
    out = []
    for row in table["rows"]:
        for i, spec in enumerate(table["columns"]):
            status, value = row["cells"][i]
            flags = list(flags_by_cell.get((row["geo_code"], i), []))
            if status in ("ok", "combined") and spec["measure"].startswith("trees") and not float(value).is_integer():
                flags.append("non_integer_count")
            if status == "combined":
                flags.append("includes_" + "_".join(sorted(table_missing_regions(table))))
            if not table["ref_year_stated"]:
                flags.append("ref_year_from_publication")
            if table["fix"]:
                flags.append("source_corrected")
            out.append({
                "dataset": DATASET, "table_key": table["table_key"], "ref_year": table["ref_year"],
                "pub_year": entry["publication_date"][:4], "geo_code": row["geo_code"], "product_code": spec["product_code"],
                "variable": spec["measure"], "qualifier": spec["qualifier"],
                "value": number(value) if status in ("ok", "combined") else "", "unit": spec["unit"], "status": status,
                "stage": entry["stage"], "flags": ";".join(sorted(set(flags))), "source_doc": entry["doc_id"]})
    return out


def table_missing_regions(table):
    return {w.split()[4] for w in table["warnings"] if w.startswith("the row of region")}


def key_of(row):
    return (row["table_key"], str(row["ref_year"]), row["geo_code"], row["product_code"], row["variable"], row["qualifier"])


# ---------------------------------------------------------------- merge

def unit_mismatch(old, new):
    """True when two figures for the same statistic differ by a factor of 1000: one of them is in the wrong unit."""
    try:
        a, b = float(old["value"]), float(new["value"])
    except ValueError:
        return False
    return a > 0 and b > 0 and (abs(b / a - 1000) < 1 or abs(a / b - 1000) < 1)


class Store:
    def __init__(self, rebuild, editions):
        self.edition = editions  # document id -> edition: later editions replace earlier ones
        self.rows = {} if rebuild else {key_of(r): r for r in read_csv(OUT / "agri_observations.csv")}
        self.revisions = [] if rebuild else read_csv(OUT / "agri_observation_revisions.csv")
        self.counts = Counter()

    def merge(self, incoming, today):
        """Merge the observations of one table; returns the number of conflicts inside the table."""
        seen, conflicts = {}, 0
        for row in incoming:
            k = key_of(row)
            if k in seen:  # the same statistic twice in one file
                if (seen[k]["value"], seen[k]["status"]) == (row["value"], row["status"]):
                    self.counts["duplicates"] += 1
                else:
                    conflicts += 1
                continue
            seen[k] = row
        if conflicts:
            return conflicts  # nothing of an ambiguous table is stored
        for k, row in seen.items():
            old = self.rows.get(k)
            if old is None:
                self.rows[k] = dict(row, last_updated=today)
                self.counts["inserted"] += 1
            elif (old["value"], old["status"]) == (row["value"], row["status"]):
                self.counts["unchanged"] += 1
                if old["source_doc"] != row["source_doc"]:
                    self.counts["duplicates"] += 1  # the same figure published again
                if old["flags"] != row["flags"] and old["source_doc"] == row["source_doc"]:
                    old["flags"] = row["flags"]
            elif unit_mismatch(old, row):
                self.counts["unit_mismatch"] += 1  # e.g. the same table in kilograms: never stored
            elif self.rank(row) >= self.rank(old):
                self.revisions.append(dict(old, superseded_on=today, superseded_by=row["source_doc"]))
                self.rows[k] = dict(row, last_updated=today)
                self.counts["updated"] += 1
            else:  # an earlier publication disagrees with the stored (later) figure
                self.revisions.append(dict(row, last_updated=today, superseded_on=today, superseded_by=old["source_doc"]))
                self.counts["kept_as_revision"] += 1
        return 0

    def rank(self, row):
        return (self.edition.get(row["source_doc"], 0), row["source_doc"])

    def sorted_rows(self):
        order = {code: n for n, (code, *_rest) in enumerate(agri_geo.geography())}
        return sorted(self.rows.values(), key=lambda r: (
            r["table_key"], int(r["ref_year"]), r["product_code"], r["variable"], r["qualifier"], order.get(r["geo_code"], 999)))


# ---------------------------------------------------------------- registry

def build_products(store_rows, meta):
    """Product registry: one row per product code with its names, years and series breaks."""
    years = defaultdict(set)
    for r in store_rows:
        years[r["product_code"]].add(int(r["ref_year"]))
    by_table = defaultdict(lambda: defaultdict(set))  # table -> year -> product codes present
    for code, ys in years.items():
        for y in ys:
            by_table[meta[code]["table_key"]][y].add(code)
    breaks = series_breaks(by_table, meta)
    rows = []
    for code in sorted(years):
        m = meta[code]
        path = m["path"]
        rows.append({
            "product_code": code, "dataset": DATASET, "table_key": m["table_key"], "category": CATEGORIES[m["table_key"]],
            "subcategory": path[0] if len(path) > 1 else "", "name_el": " – ".join(path), "name_en": m["name_en"],
            "path": " > ".join(path), "is_total": int(m["is_total"]), "is_residual": int(is_residual(path)),
            "continues": agri_products.CONTINUES.get(code, ""), "series_breaks": ";".join(str(y) for y in sorted(breaks.get(code, []))),
            "first_year": min(years[code]), "last_year": max(years[code]), "source_labels": " | ".join(sorted(m["labels"]))})
    return rows


def is_residual(path):
    return agri_spg06.fold(path[-1]).startswith("λοιπα")


def series_breaks(by_table, meta):
    """Years in which a total or a "Λοιπά" category changed content because its group gained or lost members.

    A residual ("Λοιπά …") changes whenever a category is added to or removed from its group. A total changes
    when a crop is dropped from its group or moves to another one (CONTINUES links the codes of a crop that moved);
    adding categories, or replacing one by a finer or coarser breakdown of the same crop, does not change it.
    The total of a whole table is not affected by crops moving between its groups or into its "Λοιπά" lines."""
    out = defaultdict(set)
    for table, per_year in by_table.items():
        ys = sorted(per_year)
        for prev, year in zip(ys, ys[1:]):
            members = {}
            for y in (prev, year):
                groups = defaultdict(set)
                for code in per_year[y]:
                    path = meta[code]["path"]
                    if meta[code]["is_total"] or is_residual(path):
                        continue
                    groups[path[0] if len(path) > 1 else ""].add(code)
                    groups["*"].add(code)
                members[y] = groups
            successors = {agri_products.CONTINUES[c] for c in per_year[year] if c in agri_products.CONTINUES}
            for group in set(members[prev]) | set(members[year]):
                old, new = members[prev].get(group, set()), members[year].get(group, set())
                removed, added = old - new, new - old
                def covered(code):  # replaced by a coarser or finer breakdown of the same crop, not dropped
                    path = meta[code]["path"]
                    return any(meta[a]["path"][:len(path)] == path or path[:len(meta[a]["path"])] == meta[a]["path"] for a in added)
                moved = {c for c in removed if not covered(c)} | {c for c in added if agri_products.CONTINUES.get(c) in per_year[prev]}
                for code in per_year[year]:
                    path = meta[code]["path"]
                    in_group = len(path) == 1 if group == "*" else (path[0] if len(path) > 1 else "") == group
                    if in_group and ((meta[code]["is_total"] and moved and group != "*") or (is_residual(path) and (removed or added))):
                        out[code].add(year)
    return out


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--years", nargs="*", type=int, help="editions (reference years of the ELSTAT pages) to import (default: all in the manifest)")
    parser.add_argument("--file", help="import a spreadsheet downloaded by hand (needs --year)")
    parser.add_argument("--year", type=int, help="publication year of --file")
    parser.add_argument("--stage", default="unspecified", choices=["final", "provisional", "unspecified"])
    parser.add_argument("--publication-date", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true", help="ignore the stored tables and import everything again")
    parser.add_argument("--today", default=date.today().isoformat(), help="date stored as last_updated (default: today)")
    args = parser.parse_args()
    if args.file:
        if not args.year:
            sys.exit("--file needs --year (the publication year)")
        add_manual_file(args.file, args.year, args.stage, args.publication_date)
        args.years = [args.year]

    entries = manifest_entries(set(args.years or []))
    if not entries:
        sys.exit(f"nothing to import: run scripts/fetch_agriculture_data.py first ({MANIFEST.relative_to(ROOT)})")
    store = Store(args.rebuild, {r["doc_id"]: int(r["edition"]) for r in read_csv(MANIFEST)})
    publications = {} if args.rebuild else {(p["edition"], p["doc_id"], p["sheet"]): p for p in read_csv(OUT / "agri_publications.csv")}
    issues = [] if args.rebuild else [i for i in read_csv(OUT / "agri_import_issues.csv")
                                      if (i["edition"], i["doc_id"]) not in {(e["edition"], e["doc_id"]) for e in entries}]
    meta = {}
    for p in read_csv(OUT / "agri_products.csv") if not args.rebuild else []:
        meta[p["product_code"]] = {"table_key": p["table_key"], "path": p["path"].split(" > "), "name_en": p["name_en"],
                                   "is_total": p["is_total"] == "1", "labels": set(filter(None, p["source_labels"].split(" | ")))}
    imported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    errors = warnings = tables = 0

    for entry in entries:
        path = RAW / entry["edition"] / entry["filename"]
        if not path.exists():
            sys.exit(f"{path} is listed in the manifest but missing; run scripts/fetch_agriculture_data.py")
        if sha256(path) != entry["sha256"]:
            issues.append(issue(entry, "", "warning", "checksum", "the file differs from the checksum in the manifest"))
        parsed, notes = parse_workbook(path, int(entry["edition"]))
        for note in notes:
            code = ("stale_sheet" if "stale" in note["message"] else "continuation_sheet" if "continuation" in note["message"]
                    else "skipped_sheet" if note["severity"] == "warning" else "unreadable_sheet")
            issues.append(issue(entry, note["sheet"], note["severity"], code, note["message"]))
        for table in parsed:
            flags_by_cell = defaultdict(list)
            sums = check_sums(table)
            for s in sums:
                flags_by_cell[(s["geo"], s["col"])].append("total_differs_from_parts")
            conflicts = store.merge(observations_of(table, entry, flags_by_cell), args.today)
            if conflicts:
                issues.append(issue(entry, table["sheet"], "error", "conflict",
                                    f"{conflicts} statistics appear twice in the sheet with different values; the sheet was not imported"))
                continue
            tables += 1
            n_rows = len(table["rows"]) * len(table["columns"])
            publications[(entry["edition"], entry["doc_id"], table["sheet"])] = {
                "dataset": DATASET, "edition": entry["edition"], "pub_year": entry["publication_date"][:4], "doc_id": entry["doc_id"], "sheet": table["sheet"],
                "source_table": table["source_table"], "table_key": table["table_key"], "ref_year": table["ref_year"],
                "title": table["title"], "unit_line": table["units"], "stage": entry["stage"],
                "publication_date": entry["publication_date"], "sha256": entry["sha256"], "imported_at": imported_at,
                "columns": len(table["columns"]), "rows": n_rows, "note": table["fix"]}
            if table["fix"]:
                issues.append(issue(entry, table["sheet"], "info", "source_correction", table["fix"]))
            for column in table["skipped_columns"]:
                issues.append(issue(entry, table["sheet"], "warning", "skipped_column",
                                    f"column {column['col']} ({' > '.join(column['path'])}) not imported: {column['reason']}"))
            for spec in table["columns"]:
                for text in spec["notes"]:
                    issues.append(issue(entry, table["sheet"], "info", "label_inherited", text))
            for text in table["warnings"]:
                issues.append(issue(entry, table["sheet"], "warning", "region_row_missing", text))
            if sums:
                example = sums[0]
                issues.append(issue(entry, table["sheet"], "warning", "total_differs_from_parts",
                                    f"{len(sums)} published totals differ from the sum of their parts, e.g. {example['geo']} "
                                    f"{example['column']}: {example['message']}"))
            if not table["ref_year_stated"]:
                issues.append(issue(entry, table["sheet"], "info", "ref_year_from_publication",
                                    "the sheet title states no year; the publication year is used"))
            for spec in table["columns"]:
                m = meta.setdefault(spec["product_code"], {"table_key": table["table_key"], "path": spec["product_path"],
                                                           "name_en": "", "is_total": spec["is_total"], "labels": set()})
                m["labels"].add(" > ".join(spec["source_path"]))
                if spec["name_en"]:
                    m["name_en"] = spec["name_en"]
    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")

    rows = store.sorted_rows()
    counts = store.counts
    print(f"{len(entries)} files, {tables} tables: {counts['inserted']} new, {counts['updated']} updated, "
          f"{counts['unchanged']} unchanged, {counts['duplicates']} duplicates, {counts['kept_as_revision']} kept as revision, {counts['unit_mismatch']} rejected for a unit mismatch; "
          f"{errors} errors, {warnings} warnings; {len(rows):,} statistics in total")
    for i in issues:
        if i["severity"] == "error":
            print(f"  ERROR {i['edition']}/{i['doc_id']} {i['sheet']}: {i['message']}")
    if args.dry_run:
        return

    used = {r["product_code"] for r in rows}
    write_csv(OUT / "agri_observations.csv", OBS, rows)
    write_csv(OUT / "agri_observation_revisions.csv", REVISIONS, store.revisions)
    write_csv(OUT / "agri_products.csv", PRODUCTS, build_products(rows, {k: v for k, v in meta.items() if k in used}))
    write_csv(OUT / "agri_geo.csv", GEO, [dict(zip(GEO, g)) for g in agri_geo.geography()])
    write_csv(OUT / "agri_variables.csv", ["variable", "label_el", "unit", "unit_label_el", "note"],
              [dict(zip(["variable", "label_el", "unit", "unit_label_el", "note"], v)) for v in VARIABLES])
    write_csv(OUT / "agri_datasets.csv", DATASET_FIELDS, [dict(zip(DATASET_FIELDS, d)) for d in DATASETS])
    write_csv(OUT / "agri_publications.csv", PUBLICATIONS,
              sorted(publications.values(), key=lambda p: (int(p["edition"]), p["doc_id"], p["sheet"])))
    write_csv(OUT / "agri_import_issues.csv", ISSUES, sorted(issues, key=lambda i: (int(i["edition"]), i["doc_id"], i["sheet"], i["code"], i["message"])))
    log = read_csv(OUT / "agri_import_log.csv")
    log.append({"run_at": imported_at, "command": " ".join(sys.argv[1:]), "files": len(entries), "tables": tables,
                "inserted": counts["inserted"], "updated": counts["updated"], "unchanged": counts["unchanged"],
                "duplicates": counts["duplicates"], "kept_as_revision": counts["kept_as_revision"],
                "unit_mismatch": counts["unit_mismatch"], "errors": errors, "warnings": warnings})
    write_csv(OUT / "agri_import_log.csv", LOG, log)


def issue(entry, sheet, severity, code, message):
    return {"dataset": DATASET, "edition": entry["edition"], "doc_id": entry["doc_id"], "sheet": sheet,
            "severity": severity, "code": code, "message": message}


if __name__ == "__main__":
    main()
