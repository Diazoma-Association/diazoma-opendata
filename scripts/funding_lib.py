"""Shared helpers of the funding section: normalisation, idempotent CSV upserts and the import log.

The platform is a static site, so the "structured tables" of the funding datasets are normalised CSV
files under data/funding/. Every importer uses the same rules:

- rows are identified by a stable key built from the source's dimension columns (`row_key`);
- re-importing the same file changes nothing, a revised row is updated, a new row is inserted;
- rows that are no longer in the source are kept (nothing is lost) and counted in the log;
- each import is recorded in data/funding/sync_log.csv with the source, its publication and
  modification dates and the outcome.
"""

import csv
import datetime
import hashlib
import io
import subprocess
import sys
import time
import urllib.parse
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNDING = ROOT / "data" / "funding"
SYNC_LOG = FUNDING / "sync_log.csv"
SYNC_FIELDS = ["imported_at", "dataset", "source_title", "source_url", "source_published", "source_modified",
               "rows_in_source", "inserted", "updated", "unchanged", "kept_not_in_source", "status", "note"]


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def iso_from_epoch(seconds):
    if not seconds:
        return ""
    return datetime.datetime.fromtimestamp(int(seconds), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- normalisation ------------------------------------------------------------------------------

def parse_amount(value):
    """Euro amount as a number with two decimals; empty and non-numeric values become None.

    Accepts plain numbers, and Greek or English formatted strings such as '1.234.567,89' or '1,234,567.89'.
    """
    if value is None:
        return None
    text = str(value).strip().replace(" ", "").replace("€", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        decimal_comma = text.rfind(",") > text.rfind(".")
        text = text.replace(".", "").replace(",", ".") if decimal_comma else text.replace(",", "")
    elif text.count(",") > 1:
        text = text.replace(",", "")
    elif "," in text:
        # A single comma is a decimal comma unless exactly three digits follow it ("3,000" is a thousand separator).
        head, _, tail = text.partition(",")
        text = head + tail if len(tail) == 3 else head + "." + tail
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(Decimal(text).quantize(Decimal("0.01")))
    except InvalidOperation:
        return None


def parse_date(value):
    """ISO date (YYYY-MM-DD) from ISO timestamps and dd/mm/yyyy or dd.mm.yyyy strings; otherwise None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def clean_text(value):
    return " ".join(str(value or "").replace(" ", " ").split())


def row_key(*parts):
    """Stable 16 character key of the dimension values that identify a source row."""
    return hashlib.sha1("\x1f".join(clean_text(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def fmt(value):
    """CSV representation of a value: numbers without exponents, None as an empty cell."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))
    return str(value)


# ---- downloads ----------------------------------------------------------------------------------

def get(url, attempts=5):
    """Fetch a URL with curl (the environment's proxy is configured for it), retrying transient server errors."""
    for attempt in range(attempts):
        result = subprocess.run(["curl", "-sSL", "--fail", "--max-time", "300", url], capture_output=True)
        if result.returncode == 0:
            return result.stdout
        if attempt + 1 < attempts:
            time.sleep(2 ** (attempt + 1))
    sys.exit(f"download failed ({result.returncode}): {url}\n{result.stderr.decode('utf-8', 'ignore')}")


def socrata_rows(host, dataset, where=None, select=None, page_size=50000):
    """Rows of a Socrata dataset as dictionaries, fetched page by page in a stable order."""
    offset = 0
    while True:
        params = [("$limit", page_size), ("$offset", offset), ("$order", ":id")]
        if where:
            params.append(("$where", where))
        if select:
            params.append(("$select", select))
        page = list(csv.DictReader(io.StringIO(get(f"https://{host}/resource/{dataset}.csv?{urllib.parse.urlencode(params)}").decode("utf-8"))))
        yield from page
        if len(page) < page_size:
            return
        offset += page_size


def socrata_metadata(host, dataset):
    import json
    return json.loads(get(f"https://{host}/api/views/{dataset}"))


# ---- idempotent upsert --------------------------------------------------------------------------

def read_table(path):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["row_key"]: row for row in csv.DictReader(handle)}


def upsert(path, fields, new_rows, imported_at):
    """Merge `new_rows` (dicts with a `row_key`) into the CSV at `path`; returns the counts.

    The tracking columns first_seen, last_seen and last_changed are maintained here. A row that is not in
    `new_rows` is kept unchanged, so a source that drops history does not delete it from the table.
    """
    stamp = imported_at.strftime("%Y-%m-%d")
    table = read_table(path)
    inserted = updated = unchanged = 0
    seen = set()
    for row in new_rows:
        key = row["row_key"]
        if key in seen:
            raise ValueError(f"duplicate row key {key} in the source rows of {path.name}")
        seen.add(key)
        values = {name: fmt(row.get(name)) for name in fields}
        old = table.get(key)
        if old is None:
            table[key] = {**values, "first_seen": stamp, "last_seen": stamp, "last_changed": stamp}
            inserted += 1
        elif any(old.get(name, "") != values[name] for name in fields if name != "row_key"):
            table[key] = {**values, "first_seen": old["first_seen"], "last_seen": stamp, "last_changed": stamp}
            updated += 1
        else:
            old["last_seen"] = stamp
            unchanged += 1
    kept = len(table) - len(seen)
    columns = [*fields, "first_seen", "last_seen", "last_changed"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for key in sorted(table):
            writer.writerow({name: table[key].get(name, "") for name in columns})
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged, "kept_not_in_source": kept}


def log_sync(entry):
    FUNDING.mkdir(parents=True, exist_ok=True)
    exists = SYNC_LOG.exists()
    with SYNC_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SYNC_FIELDS, lineterminator="\n")
        if not exists:
            writer.writeheader()
        writer.writerow({name: entry.get(name, "") for name in SYNC_FIELDS})
