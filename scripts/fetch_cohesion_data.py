#!/usr/bin/env python3
"""Import the European Commission's Cohesion Open Data tables that cover Greece.

Usage:
    python3 scripts/fetch_cohesion_data.py

Sources (https://cohesiondata.ec.europa.eu, licence CC0):
    3git-md5z  2021-2027 Finances Detailed Planned vs Implemented (timeseries)
               The data behind the "Financial implementation by intervention field" chart (9b7m-ewym).
               Only the rows of Greece (ms = EL) are imported.
    9qee-iv7c  2021-2027 Financial Plan details by year (All CPR funds)
               The data behind the "Interreg EU allocations" chart (upqa-iza8). The transnational
               programmes (ms = TC) are imported.
    92d9-xqvh  2021-2027 cohesion CCI / NUTS lookup table
               The territories covered by each programme. It decides which Interreg programmes involve Greece.

The links of the two charts point at visualisations, not at tables, so the underlying datasets are
read through the Socrata API after the column names were checked against the dataset metadata.

Outputs (data/funding/): cohesion_financial_implementation_el.csv, interreg_allocations.csv,
interreg_greek_territories.csv and an entry per dataset in sync_log.csv. Importing the same data again
changes nothing; revised rows are updated and rows missing from the source are kept.
"""

import sys

import funding_lib as lib

HOST = "cohesiondata.ec.europa.eu"
PROGRESS_DATASET, ALLOCATION_DATASET, LOOKUP_DATASET = "3git-md5z", "9qee-iv7c", "92d9-xqvh"

PROGRESS_SOURCE_COLUMNS = [
    "ms", "cci", "programme_short_title", "programme_status", "programme_version", "programme_adoption_date", "fund",
    "fund_family", "category_region_name", "tod_cycle", "tod_year", "tod_reference_version", "priority_code",
    "priority_name", "step_priority", "pol_obj_code", "pol_obj_name", "spec_obj_code", "spec_obj_name", "dimension_type",
    "category_short_title", "category_code", "category_node", "cofinancing_rate", "eu_amount", "total_amount",
    "total_eligiblecost_of_selectedoperations", "eueligible_costs_decided_selectednotional",
    "totalspendeligibleexpenditure_declared", "euspendshare_eligexpendituredeclarednotional", "sustainable_urban_development",
    "territorial_tool", "territory_type", "un_sdg_tracking", "jtf_themes", "competitiveness_compass_pillar",
    "priority_type_code", "number_of_operations", "is_latest_tod_cycle",
]
PROGRESS_FIELDS = [
    "row_key", "cycle", "cycle_year", "reference_version", "is_latest_cycle", "programme_cci", "programme_title_en",
    "programme_version", "programme_status", "programme_adoption_date", "fund", "fund_family", "category_of_region",
    "priority_code", "priority_name", "step_priority", "policy_objective_code", "policy_objective_name",
    "specific_objective_code", "specific_objective_name", "dimension_type", "intervention_code", "intervention_title",
    "intervention_node", "cofinancing_rate", "planned_eu_eur", "planned_total_eur", "decided_total_eur",
    "decided_eu_notional_eur", "spent_total_eur", "spent_eu_notional_eur", "operations_count", "territorial_tool",
    "territory_type", "sustainable_urban_development", "un_sdg_tracking", "jtf_themes", "competitiveness_compass_pillar",
    "priority_type_code",
]
# Source columns that identify a row. Checked on the Greek rows: they give no duplicates in any cycle.
PROGRESS_KEY = ["cci", "tod_cycle", "fund", "category_region_name", "priority_code", "priority_name", "pol_obj_code",
                "spec_obj_code", "spec_obj_name", "dimension_type", "category_code", "category_short_title", "category_node",
                "territorial_tool", "territory_type", "sustainable_urban_development", "step_priority", "priority_type_code",
                "jtf_themes", "un_sdg_tracking", "cofinancing_rate", "competitiveness_compass_pillar"]

YEARS = list(range(2021, 2028))
ALLOCATION_FIELDS = ["row_key", "cci", "programme_title", "dg", "programme_version", "status", "status_date", "fund",
                     "financial_allocation_category", *[f"eu_commitment_{y}_eur" for y in YEARS],
                     "total_non_flexible_eur", "total_flexible_eur", "total_eu_commitments_eur"]
TERRITORY_FIELDS = ["row_key", "cci", "programme_title", "programme_title_local", "nuts_code", "territory", "nuts_level"]


def with_log(dataset, title, meta, rows_in_source, counts, note=""):
    lib.log_sync({
        "imported_at": lib.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), "dataset": dataset, "source_title": title,
        "source_url": f"https://{HOST}/d/{dataset}", "source_published": lib.iso_from_epoch(meta.get("publicationDate")),
        "source_modified": lib.iso_from_epoch(meta.get("rowsUpdatedAt")), "rows_in_source": rows_in_source,
        "status": "ok", "note": note, **counts,
    })


def import_progress(imported_at):
    meta = lib.socrata_metadata(HOST, PROGRESS_DATASET)
    # The dataset metadata must still describe the columns this importer reads.
    available = {column["fieldName"] for column in meta["columns"]}
    missing = [c for c in PROGRESS_SOURCE_COLUMNS if c not in available]
    if missing:
        sys.exit(f"{PROGRESS_DATASET} no longer has the columns {missing}; the importer has to be updated")
    rows = []
    for source in lib.socrata_rows(HOST, PROGRESS_DATASET, where="ms='EL'", select=",".join(PROGRESS_SOURCE_COLUMNS)):
        amount = lambda name: lib.parse_amount(source[name])
        rows.append({
            "row_key": lib.row_key(*(source[c] for c in PROGRESS_KEY)),
            "cycle": source["tod_cycle"], "cycle_year": source["tod_year"], "reference_version": source["tod_reference_version"],
            "is_latest_cycle": "Y" if source["is_latest_tod_cycle"] == "Y" else "N",
            "programme_cci": source["cci"], "programme_title_en": lib.clean_text(source["programme_short_title"]),
            "programme_version": source["programme_version"], "programme_status": lib.clean_text(source["programme_status"]),
            "programme_adoption_date": lib.parse_date(source["programme_adoption_date"]),
            "fund": source["fund"], "fund_family": source["fund_family"], "category_of_region": source["category_region_name"],
            "priority_code": source["priority_code"], "priority_name": lib.clean_text(source["priority_name"]),
            "step_priority": source["step_priority"], "policy_objective_code": source["pol_obj_code"],
            "policy_objective_name": lib.clean_text(source["pol_obj_name"]), "specific_objective_code": source["spec_obj_code"],
            "specific_objective_name": lib.clean_text(source["spec_obj_name"]), "dimension_type": source["dimension_type"],
            "intervention_code": source["category_code"], "intervention_title": lib.clean_text(source["category_short_title"]),
            "intervention_node": source["category_node"], "cofinancing_rate": source["cofinancing_rate"],
            "planned_eu_eur": amount("eu_amount"), "planned_total_eur": amount("total_amount"),
            "decided_total_eur": amount("total_eligiblecost_of_selectedoperations"),
            "decided_eu_notional_eur": amount("eueligible_costs_decided_selectednotional"),
            "spent_total_eur": amount("totalspendeligibleexpenditure_declared"),
            "spent_eu_notional_eur": amount("euspendshare_eligexpendituredeclarednotional"),
            "operations_count": source["number_of_operations"], "territorial_tool": source["territorial_tool"],
            "territory_type": source["territory_type"], "sustainable_urban_development": source["sustainable_urban_development"],
            "un_sdg_tracking": source["un_sdg_tracking"], "jtf_themes": source["jtf_themes"],
            "competitiveness_compass_pillar": source["competitiveness_compass_pillar"], "priority_type_code": source["priority_type_code"],
        })
    counts = lib.upsert(lib.FUNDING / "cohesion_financial_implementation_el.csv", PROGRESS_FIELDS, rows, imported_at)
    with_log(PROGRESS_DATASET, meta["name"], meta, len(rows), counts, "ms = EL; cumulative values per reporting cycle, not to be added across cycles")
    print("financial implementation:", len(rows), "rows", counts)


def import_allocations(imported_at):
    meta = lib.socrata_metadata(HOST, ALLOCATION_DATASET)
    rows = []
    for source in lib.socrata_rows(HOST, ALLOCATION_DATASET, where="ms='TC'"):
        row = {
            "row_key": lib.row_key(source["cci"], source["fund"], source["financial_allocation_category"]),
            "cci": source["cci"], "programme_title": lib.clean_text(source["cci_title"]), "dg": source["dg"],
            "programme_version": source["ver"], "status": lib.clean_text(source["status"]),
            "status_date": lib.parse_date(source["status_date"]), "fund": source["fund"],
            "financial_allocation_category": lib.clean_text(source["financial_allocation_category"]),
            "total_non_flexible_eur": lib.parse_amount(source["total_non_flexible_amount"]),
            "total_flexible_eur": lib.parse_amount(source["total_flexible_amount"]),
            "total_eu_commitments_eur": lib.parse_amount(source["total"]),
        }
        for year in YEARS:
            row[f"eu_commitment_{year}_eur"] = lib.parse_amount(source[f"y{year}"])
        rows.append(row)
    counts = lib.upsert(lib.FUNDING / "interreg_allocations.csv", ALLOCATION_FIELDS, rows, imported_at)
    with_log(ALLOCATION_DATASET, meta["name"], meta, len(rows), counts, "ms = TC; planned annual EU commitments, not expenditure")
    print("Interreg allocations:", len(rows), "rows", counts)


def import_territories(imported_at):
    meta = lib.socrata_metadata(HOST, LOOKUP_DATASET)
    rows = []
    for source in lib.socrata_rows(HOST, LOOKUP_DATASET, where="ms='TC' AND nuts_full_description like 'EL%'"):
        code = source["nuts_full_description"].split()[0]
        if not code.startswith("EL") or not code[2:].isalnum() and code != "EL":
            continue
        rows.append({
            "row_key": lib.row_key(source["cci"], code), "cci": source["cci"], "programme_title": lib.clean_text(source["cci_title_short"]),
            "programme_title_local": lib.clean_text(source["cci_title_local"]), "nuts_code": code,
            "territory": lib.clean_text(source["nuts_description"]), "nuts_level": source["nuts_level"],
        })
    counts = lib.upsert(lib.FUNDING / "interreg_greek_territories.csv", TERRITORY_FIELDS, rows, imported_at)
    with_log(LOOKUP_DATASET, meta["name"], meta, len(rows), counts, "ms = TC; territories with a Greek NUTS code")
    print("Greek territories of Interreg programmes:", len(rows), "rows", counts)


if __name__ == "__main__":
    lib.FUNDING.mkdir(parents=True, exist_ok=True)
    started = lib.now_utc()
    import_progress(started)
    import_allocations(started)
    import_territories(started)
