#!/usr/bin/env python3
"""Download the ELSTAT agriculture tables (see agri_sources.py) into data/agriculture/<publication>/.

Usage:
    python3 scripts/fetch_agriculture_data.py                          # every publication, new files only
    python3 scripts/fetch_agriculture_data.py --dataset SPK33          # one or more publications
    python3 scripts/fetch_agriculture_data.py --dataset SPG06 --years 2024   # selected editions
    python3 scripts/fetch_agriculture_data.py --force                  # download again and overwrite

Publications: SPG06 annual agricultural survey, SPG32 and SPK12 farm structure survey (holdings and areas, livestock
holdings), SPK33 annual livestock survey. Each ELSTAT publication page (…/publication/<code>/<year>) lists the XLS(X)
tables and, for most publications, the press release. The tables are saved unchanged under
data/agriculture/<publication>/<year>/<document id>.<ext>, and data/agriculture/<publication>/manifest.csv records, per
file, the edition (the ELSTAT page of the reference year it belongs to), the document id, title, checksum, whether the
publication is labelled final or provisional and, when the press release can be read, the publication date (the PDFs of
some years have unreadable text, then it stays empty). The data is parsed by scripts/import_agriculture_data.py. Needs
curl; pdftotext (poppler) is optional and only used to read the publication date from the press release.

The ELSTAT site is not always reachable by script. Files can also be added by hand: put the ELSTAT
spreadsheet under data/agriculture/<publication>/<year>/ and run the importer with --file (see its docstring).
"""

import argparse
import csv
import hashlib
import html
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import agri_sources

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["dataset", "edition", "doc_id", "filename", "title", "format", "sha256", "bytes", "source_page",
          "stage", "publication_date", "downloaded_at"]
MONTHS = {"Ιανουαρίου": 1, "Φεβρουαρίου": 2, "Μαρτίου": 3, "Απριλίου": 4, "Μαΐου": 5, "Ιουνίου": 6, "Ιουλίου": 7,
          "Αυγούστου": 8, "Σεπτεμβρίου": 9, "Οκτωβρίου": 10, "Νοεμβρίου": 11, "Δεκεμβρίου": 12}


def get(url):
    """Fetch a URL with curl; the ELSTAT site answers plain urllib requests with a redirect to http."""
    result = subprocess.run(["curl", "-sSL", "--fail", "--max-time", "180", url], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"download failed ({result.returncode}): {url}\n{result.stderr.decode('utf-8', 'ignore')}")
    return result.stdout


def text_of(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def documents(page):
    """(document id, file type, title, url) for every document linked from a publication page."""
    found, seen = [], set()
    for m in re.finditer(r'href="([^"]*documentID=(\d+)[^"]*)"[^>]*>(.*?)</a>.*?file_type_(\w+)', page, re.S):
        doc_id = m.group(2)
        if doc_id not in seen:
            seen.add(doc_id)
            found.append((doc_id, m.group(4), text_of(m.group(3)), html.unescape(m.group(1))))
    return found


def press_release_date(data):
    """Publication date from the first page of the press release (…, 25 Ιουνίου 2026), or ''."""
    try:
        text = subprocess.run(["pdftotext", "-layout", "-l", "1", "-", "-"], input=data, capture_output=True).stdout.decode("utf-8", "ignore")
    except FileNotFoundError:
        return ""
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", text)
    if m:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(20\d\d)", text)  # 29 / 04 / 2015
    return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""


def stage_of(titles):
    """final / provisional as the ELSTAT press release title states it; unspecified when it does not."""
    joined = " ".join(titles)
    if "Οριστικά" in joined:
        return "final"
    if "Προσωρινά" in joined:
        return "provisional"
    return "unspecified"


def read_manifest(dataset):
    path = agri_sources.manifest_path(dataset)
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {(r["edition"], r["doc_id"]): r for r in csv.DictReader(handle)}


def write_manifest(dataset, rows):
    path = agri_sources.manifest_path(dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, FIELDS, lineterminator="\n")
        writer.writeheader()
        for key in sorted(rows, key=lambda k: (int(k[0]), int(k[1]) if k[1].isdigit() else 0, k[1])):
            writer.writerow(rows[key])


def fetch_year(dataset, year, rows, force):
    source = agri_sources.SOURCES[dataset]
    raw = agri_sources.raw_dir(dataset)
    page_url = f"{agri_sources.PAGE.format(code=dataset)}/{year}"
    docs = documents(get(page_url).decode("utf-8", "ignore"))
    release = source["release"]
    releases = [d for d in docs if d[1] == "pdf" and release and release(d[2])]
    stage = stage_of([d[2] for d in releases])
    pub_date = ""
    for _, _, title, url in releases:
        if stage_of([title]) == stage:  # the date of the release that carries the stage the tables are labelled with
            pub_date = pub_date or press_release_date(get(url))
    tables = [d for d in docs if d[1] in ("xls", "xlsx")]
    if not tables:
        print(f"{dataset} {year}: no spreadsheets on the publication page")
    for doc_id, _, title, url in tables:
        old = rows.get((str(year), doc_id))
        if old and not force and (raw / str(year) / old["filename"]).exists():
            old.update(stage=stage, publication_date=pub_date or old["publication_date"])
            continue
        data = get(url)
        ext = "xlsx" if data[:2] == b"PK" else "xls"  # ELSTAT names both formats .xls
        target = raw / str(year) / f"{doc_id}.{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows[(str(year), doc_id)] = {
            "dataset": dataset, "edition": year, "doc_id": doc_id, "filename": target.name, "title": title, "format": ext,
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "source_page": page_url, "stage": stage,
            "publication_date": pub_date, "downloaded_at": date.today().isoformat()}
        print(f"{dataset} {year}: {target.name}  {title[:70]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset", nargs="*", choices=list(agri_sources.SOURCES), help="publications (default: all)")
    parser.add_argument("--years", nargs="*", type=int, help="editions (default: every year the publication is imported for)")
    parser.add_argument("--force", action="store_true", help="download again and overwrite existing files")
    args = parser.parse_args()
    for dataset in args.dataset or agri_sources.SOURCES:
        source = agri_sources.SOURCES[dataset]
        years = args.years
        if not years:
            if source["editions"]:
                years = source["editions"]
            else:
                index = get(agri_sources.PAGE.format(code=dataset)).decode("utf-8", "ignore")
                years = sorted({int(y) for y in re.findall(rf"publication/{dataset}/(\d{{4}})", index) if int(y) >= source["first_year"]})
        rows = read_manifest(dataset)
        for year in years:
            try:
                fetch_year(dataset, year, rows, args.force)
            except RuntimeError as error:
                print(f"{dataset} {year}: {error}", file=sys.stderr)
        write_manifest(dataset, rows)
        print(f"{dataset}: {len(rows)} files in {agri_sources.manifest_path(dataset).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
