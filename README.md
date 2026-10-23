# Diazoma Open Data

An open-data platform by the **Diazoma Association** (Σωματείο Διάζωμα) that turns official Greek and European statistics on culture, tourism, population, the economy, agriculture and EU funding into **readable, verifiable dashboards**. The site is in Greek.

Live site: published with GitHub Pages from the `main` branch (see [Deployment](#deployment)).

---

## What is this? (plain language)

Official statistics are published as large spreadsheets, often hard to read and split across many files. This project:

1. **Collects** the official files from ELSTAT (the Hellenic Statistical Authority), Eurostat, and the European Commission's Cohesion Open Data portal.
2. **Cleans** them with small Python scripts, so the numbers are consistent and labelled the same way across sections.
3. **Shows** them as simple interactive pages (charts, maps, tables, filters) that anyone can open in a web browser.
4. **Keeps the raw data** in the repository, so anyone can check a number against its source or reuse the data.

Nothing is hidden behind a login or a server. The pages are plain files, and the data is inside them.

---

## Sections

| Section | What it shows | Period | Main sources |
|---|---|---|---|
| [Archaeological sites](archaeological-sites/) (Επισκεψιμότητα αρχαιολογικών χώρων) | Visits and tickets per site and region | 1998–2026 (2026 partial) | ELSTAT, Museum and Archaeological Site Visits Survey, table 04 |
| [Tourism activity](tourism-activity/) (Τουριστική δραστηριότητα) | Arrivals, nights, bed occupancy, seasonality, visitor origin | 2025 (ELSTAT), Eurostat series | ELSTAT STO12, Eurostat `tour_occ_nin2`, `tour_occ_nin2m` |
| [Demographics](demographics/) (Δημογραφικά στοιχεία) | Population, births, deaths, migration, age structure by region | Eurostat series | Eurostat `demo_r_gind3`, `demo_r_d2jan` |
| [Census 2021](demographics/census-2021/) | Population and education by municipality | 2021 | ELSTAT, Population–Housing Census 2021 (SAM03) |
| [Regional economy](regional-economy/) (Περιφερειακή οικονομία) | GDP, GDP per head, comparison with the EU, real change, sector mix | 2000–2024 | Eurostat `nama_10r_2gdp`, `nama_10r_3gva`, `nama_10r_2gvagr` |
| [Agrifood and productive capacity](agrifood/) (Αγροδιατροφή) | Crops, holdings, livestock, aquaculture, employment, accounts, price indices | 1995–2025 | ELSTAT surveys SPG06, SPG32, SPG12, SPK12, SPK33, SPA06, SEL61, DKT30, DKT33 |
| [Funding and public investment](funding/) (Χρηματοδοτήσεις) | 2021–2027 financial progress and Interreg programmes with Greek participation | 2021–2027 | Cohesion Open Data (`3git-md5z`, `9qee-iv7c`, `92d9-xqvh`) |

The **funding** section is partly available. The list of ESPA projects (Έργα ΕΣΠΑ) is not imported yet, because the official file has not been loaded into the repository. See [`funding/projects/`](funding/projects/).

---

## Quick start: look at the data

No installation is needed to **view** the site. Open `index.html` in any modern browser, or use the live site.

To **rebuild** or **check** the data, you need Python 3.12 or later:

```bash
git clone https://github.com/Diazoma-Association/diazoma-opendata.git
cd diazoma-opendata

# Libraries used by the Excel parsers and the map builder
pip install openpyxl xlrd shapely

# Check that every dashboard matches its CSV source files (changes nothing)
python3 scripts/build_dashboard_data.py --check
python3 scripts/build_tourism_data.py --check
python3 scripts/build_demographics_data.py --check
python3 scripts/build_economy_data.py --check
python3 scripts/build_census_data.py --check
python3 scripts/build_agriculture_data.py --check
python3 scripts/build_funding_data.py --check
```

---

## How it works

### Simple version

Each section has three layers:

- **Source files**: the official spreadsheets or API data, stored as downloaded.
- **Tables**: clean CSV files that the scripts produce from the sources. These are the "source of truth".
- **Pages**: the dashboards. Their data is written into the HTML from the CSV tables, so the page and the CSV can never disagree. A check script confirms this.

### Technical version

- **Front end:** static HTML, CSS and vanilla JavaScript. There is no framework, no bundler, and no CDN or external library. Each dashboard is a single `index.html` whose data lives in one or more `<script type="application/json">` blocks. The agrifood pages also load one shared script from `assets/js/`.
- **Shared styling and logic:** `assets/css/dashboard.css`, `assets/css/agrifood.css` and `assets/js/agri-dashboard.js` (the latter is shared by the agrifood pages).
- **Data layer:** CSV files under `data/` with fixed schemas and stable keys. The agriculture tables are documented in [`data/agriculture/README.md`](data/agriculture/README.md) (Greek). Other sections are documented in [`data/README.md`](data/README.md) (Greek).
- **Build step:** Python scripts generate the JSON blocks inside each page. Each builder has a `--check` mode that compares the page to the CSV files and fails if they differ.
- **Idempotent imports:** the funding importers (`scripts/funding_lib.py`) use stable row keys. Re-importing the same file changes nothing, a revised row is updated, and a new row is inserted. Every import is recorded in `data/funding/sync_log.csv`.
- **Excel parsers:** ELSTAT publishes workbooks designed for reading, not processing. The parsers in `scripts/agri_*.py` read the header and footnote legends rather than assuming column positions. They also check each value's unit against the unit line, and report anything they cannot interpret instead of guessing.

### Data flow

```
ELSTAT / Eurostat / Cohesion Open Data
            │   scripts/fetch_*.py  (download, or read the stored copy)
            ▼
   data/<section>/…   raw spreadsheets, manifests
            │   scripts/import_*.py, scripts/agri_*.py  (parse and normalise)
            ▼
   data/**/*.csv      normalised tables (source of truth)
            │   scripts/build_*_data.py  (write the JSON block of each page)
            ▼
   <section>/index.html   static dashboard (served by GitHub Pages)
            ▲
            └── scripts/build_*_data.py --check  (run in CI, fails on drift)
```

---

## Repository layout

```
.
├── index.html                   Hub page: links to every section
├── archaeological-sites/        Archaeological site visits dashboard
├── tourism-activity/            Tourism dashboard
├── demographics/                Demographics dashboard
│   └── census-2021/             Census 2021 dashboard
├── regional-economy/            Regional economy dashboard
├── agrifood/                    Agrifood section (hub and 8 pages)
│   ├── plant-production/  livestock/  holdings/  economy/
│   ├── employment/  prices/  regional-profile/  aquaculture/
├── funding/                     Funding section (hub and 3 pages)
│   ├── progress/  interreg/  projects/
├── assets/                      Logo, shared CSS and JavaScript
├── data/                        CSV tables and source spreadsheets
│   ├── agriculture/             Agri tables per publication, geometry, manifests
│   ├── funding/                 Normalised funding tables and sync log
│   │   └── raw/                 Manual uploads for files that cannot be downloaded automatically
│   ├── census_2021/             Census source workbooks
│   └── elstat_tourism_2025/     Tourism source workbooks
├── scripts/                     Fetch, import, build and verify scripts (28 files)
├── .github/workflows/           CI (validation) and Pages deployment
├── README-archaeological-sites-dashboard.md   Detailed notes for that dashboard (Greek)
└── LICENSE                      MIT
```

---

## Scripts

Scripts are grouped by job. Most scripts start with a docstring that gives their usage; read the top of the file for details. `funding_lib.py` and the `agri_*.py` parsers are modules imported by the others, not commands to run directly.

| Job | Scripts | What they do |
|---|---|---|
| **Fetch** | `fetch_census_data.py`, `fetch_tourism_data.py`, `fetch_demographics_data.py`, `fetch_economy_data.py`, `fetch_cohesion_data.py`, `fetch_agriculture_data.py` | Download or read the official sources and write the tables |
| **Import (agriculture)** | `import_agriculture_data.py`, `agri_spg06.py`, `agri_survey.py`, `agri_livestock.py`, `agri_accounts.py`, `agri_indices.py`, `agri_aquaculture.py`, `agri_xlsx.py`, `agri_products.py`, `agri_geo.py`, `agri_sources.py` | Parse ELSTAT workbooks, classify products, and load the statistics tables. `agri_sources.py` lists every publication |
| **Build** | `build_dashboard_data.py`, `build_tourism_data.py`, `build_demographics_data.py`, `build_census_data.py`, `build_economy_data.py`, `build_agriculture_data.py`, `build_funding_data.py`, `build_agriculture_geometry.py` | Write the data into the dashboard pages, or build the map geometry (`greece_units.json`) |
| **Verify** | `verify_agriculture_data.py`, each `build_*` with `--check` | Check structure, anchor values against published figures, and that pages match the CSVs |
| **Utilities** | `inspect_xlsx.py`, `funding_lib.py` | Print the structure of an XLSX file (use before writing a parser), and shared helpers for funding imports |

### Useful commands

```bash
# Re-download the agriculture publications (new files only)
python3 scripts/fetch_agriculture_data.py
python3 scripts/fetch_agriculture_data.py --dataset SPK33 --years 2024

# Import agriculture tables (a dry run reports without writing)
python3 scripts/import_agriculture_data.py --dry-run
python3 scripts/import_agriculture_data.py --dataset SPG06

# Verify the agriculture tables, including re-parsing the source workbooks
python3 scripts/verify_agriculture_data.py --reparse

# Look inside a workbook before writing a parser
python3 scripts/inspect_xlsx.py data/elstat_archaeological_sites_1998_may2026.xlsx --rows 10

# Rebuild the map geometry from Eurostat GISCO LAU data
python3 scripts/build_agriculture_geometry.py
```

---

## Data sources

| Source | Used for | Licence and terms |
|---|---|---|
| [ELSTAT](https://www.statistics.gr/) (Hellenic Statistical Authority) | Archaeological visits, tourism, census, agriculture | Reuse of official statistics under the terms on the ELSTAT website |
| [Eurostat](https://ec.europa.eu/eurostat) | Demographics, regional economy, tourism (EU comparison) | Eurostat reuse policy (free reuse with attribution) |
| [Cohesion Open Data](https://cohesiondata.ec.europa.eu) | Funding progress and Interreg datasets | CC0 |
| Eurostat GISCO, LAU 2021 | Map boundaries for agriculture | © EuroGeographics, under the Eurostat/GISCO terms |

Each page lists its sources in the footer, and each section's documentation names the exact tables and publication dates.

---

## Important limits (please read before using the numbers)

- **Partial years.** 2026 in the archaeological series covers January to May only. Do not compare it with full years.
- **Different definitions over time.** From 2002 ELSTAT counts paid and free admissions. The 1998–2001 figures count tickets only, so the two periods are not fully comparable.
- **Visits are not people.** Archaeological visits and tickets count admissions, not unique visitors.
- **Changing coverage.** In some years a region's series covers only part of it (for example, Thessaly before the later addition of Trikala, Larissa and Karditsa). The dashboard shows a warning in these cases.
- **Old administrative boundaries.** The archaeological source is grouped by former prefectures (νομοί), mapped to the current 13 regions. Where one prefecture was split, the data is **not** divided further.
- **Missing is not zero.** An empty value means the source did not publish a figure. An explicit `0` is kept as zero.
- **Aquaculture is national only.** The ELSTAT aquaculture survey publishes country totals, so the page shows no regional breakdown.
- **Funding figures are cumulative per reporting cycle.** Do not add them across cycles.
- **Planned vs. implemented.** Some funding data is planned EU commitments, not expenditure. The dataset notes say which is which.

---

## Deployment

- **Continuous deployment:** `.github/workflows/pages.yml` publishes the site to GitHub Pages on every push to `main`. It copies the hub page, the section folders, `data/` and `assets/`. Scripts, workflows and READMEs are not published.
- **Continuous validation:** `.github/workflows/validate.yml` runs on every push and pull request. It re-parses the agriculture workbooks, checks every `build_*` script with `--check`, and runs `node --check` on the JavaScript of each dashboard.
- **One-time setup:** in *Settings → Pages → Build and deployment*, set the source to **GitHub Actions**.

---

## Contributing

Contributions are welcome, especially data checks, source corrections, translations and accessibility improvements.

1. Open an issue describing the change, or pick an existing one.
2. Create a branch from `main`.
3. Make your change. If you change a CSV table or a dashboard's data, run the matching `build_*_data.py` script so the page is regenerated, then run its `--check`.
4. Run the validation commands above. Every check in `validate.yml` must pass.
5. Open a pull request. Describe which source you used and any figures you changed.

**Rules of thumb**

- Never edit the generated JSON blocks in an HTML page by hand. Change the CSV or the script, then rebuild.
- Keep the raw source file next to the table it produced, so the number can be traced back.
- Do not infer or fill in missing values. Keep gaps as gaps and document them.
- Keep the wording simple. Each page should be understandable without the technical notes.

---

## Language

The site, the pages and most of the documentation are in **Greek**. This README is in English. The data files use Greek labels, with codes (such as NUTS and ELSTAT codes) kept in Latin characters.

---

## Licence

Released under the **MIT License**. Copyright © 2026 Σωματείο Διάζωμα. See [LICENSE](LICENSE).

The source data belongs to the publishers listed above and is subject to their own reuse terms.

---

## Acknowledgements

Built by the Diazoma Association, using official statistics from ELSTAT, Eurostat and the European Commission.
