#!/usr/bin/env python3
"""Generate the embedded data of the funding dashboards from the CSV files in data/funding/.

Usage:
    python3 scripts/build_funding_data.py           # rewrite the data blocks of the dashboards
    python3 scripts/build_funding_data.py --check   # verify the dashboards and the CSVs agree, change nothing

Dashboards:
    funding/progress/index.html  financial progress of the 2021-2027 programmes (Cohesion Open Data, dataset 3git-md5z)
    funding/interreg/index.html  Interreg programmes involving Greece (datasets 9qee-iv7c and 92d9-xqvh)

The reporting cycles of the financial implementation are cumulative: every cycle is a complete snapshot and cycles
are never added together. The planned annual allocations of Interreg are commitments, not expenditure.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNDING = ROOT / "data" / "funding"
PAGES = {"progress": ROOT / "funding" / "progress" / "index.html", "interreg": ROOT / "funding" / "interreg" / "index.html"}
BLOCKS = {"progress": "funding-progress-data", "interreg": "funding-interreg-data"}

FUND_NAMES = {"ERDF": "ΕΤΠΑ", "ESF+": "ΕΚΤ+", "CF": "Ταμείο Συνοχής", "JTF": "Ταμείο Δίκαιης Μετάβασης", "EMFAF": "ΕΤΘΑΥ",
              "AMIF": "ΤΑΜΕ", "BMVI": "ΜΔΣΘ", "ISF": "ΤΕΑ", "IPA3": "IPA III", "NDICI": "NDICI", "INTERREG": "Interreg"}
# The regional programmes of Greece, by the English title in the source.
REGIONAL_PROGRAMMES = {"Anatoliki Makedonia, Thraki": "EL51", "Kentriki Makedonia": "EL52", "Dytiki Makedonia": "EL53", "Ipeiros": "EL54",
                       "Thessalia": "EL61", "Ionia Nisia": "EL62", "Dytiki Ellada": "EL63", "Sterea Ellada": "EL64", "Peloponnisos": "EL65",
                       "Attiki": "EL30", "Voreio Aigaio": "EL41", "Notio Aigaio": "EL42", "Kriti": "EL43"}


def read(name):
    with (FUNDING / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def num(value):
    return float(value) if value not in ("", None) else 0.0


def euros(value):
    return int(round(value))


# ---- financial progress ---------------------------------------------------------------------------

def taxonomy():
    themes = read("taxonomy_themes.csv")
    cohesion, emfaf, home = {}, {}, {}
    for row in read("taxonomy_intervention_fields.csv"):
        {"cohesion": cohesion, "emfaf": emfaf, "home": home}[row["scope"]][row["code"]] = row["theme_id"]
    return themes, cohesion, emfaf, home


def theme_of(row, cohesion, emfaf, home):
    family, code = row["fund_family"], row["intervention_code"]
    if family == "Cohesion":
        return cohesion[code]
    if family == "EMFAF":
        return emfaf[code]
    if family == "HOME":
        return home["TA.*"] if row["intervention_title"].startswith("TA.") else home["*"]
    raise KeyError(f"unknown fund family {family!r}")


def programme_label(cci, title_el, title_en, fund_codes):
    if title_el:
        return title_el
    funds = " / ".join(FUND_NAMES.get(f, f) for f in fund_codes)
    return f"Ελλάδα – {funds}"


def build_progress():
    themes, cohesion, emfaf, home = taxonomy()
    rows = read("cohesion_financial_implementation_el.csv")
    greek = {r["cci"]: r["programme_title_el"] for r in read("programmes_el.csv")}
    cycles = sorted({r["cycle"] for r in rows})
    latest = {r["cycle"] for r in rows if r["is_latest_cycle"] == "Y"}
    assert latest == {cycles[-1]}, f"the latest cycle flag does not match the last cycle: {latest}"

    english, funds_of = {}, defaultdict(set)
    for r in rows:
        english[r["programme_cci"]] = r["programme_title_en"]
        funds_of[r["programme_cci"]].add(r["fund"])
    ccis = sorted(english)
    programmes = []
    for cci in ccis:
        region = next((code for name, code in REGIONAL_PROGRAMMES.items() if english[cci].startswith(name)), "")
        kind = "regional" if region else "national"
        programmes.append({"cci": cci, "name": programme_label(cci, greek.get(cci, ""), english[cci], sorted(funds_of[cci])),
                           "kind": kind, "region": region, "titleEn": english[cci]})
    prog_index = {p["cci"]: i for i, p in enumerate(programmes)}
    fund_codes = sorted({r["fund"] for r in rows})
    fund_index = {f: i for i, f in enumerate(fund_codes)}
    theme_ids = [t["theme_id"] for t in themes]
    theme_index = {t: i for i, t in enumerate(theme_ids)}
    cycle_index = {c: i for i, c in enumerate(cycles)}

    spec_index, spec_list = {}, []
    cube = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    interventions = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        theme = theme_of(r, cohesion, emfaf, home)
        spec_key = (r["programme_cci"], r["specific_objective_code"], r["specific_objective_name"])
        if spec_key not in spec_index:
            spec_index[spec_key] = len(spec_list)
            spec_list.append([prog_index[r["programme_cci"]], r["specific_objective_code"], r["specific_objective_name"]])
        key = (cycle_index[r["cycle"]], prog_index[r["programme_cci"]], fund_index[r["fund"]], theme_index[theme], spec_index[spec_key])
        for i, field in enumerate(("planned_total_eur", "planned_eu_eur", "decided_total_eur", "spent_total_eur")):
            cube[key][i] += num(r[field])
        if r["cycle"] == cycles[-1]:
            ikey = (prog_index[r["programme_cci"]], fund_index[r["fund"]], theme_index[theme], r["intervention_code"], r["intervention_title"])
            for i, field in enumerate(("planned_total_eur", "decided_total_eur", "spent_total_eur")):
                interventions[ikey][i] += num(r[field])

    # Every Greek row has a theme and the cube keeps the totals of each cycle.
    for cycle in cycles:
        expected = sum(num(r["planned_total_eur"]) for r in rows if r["cycle"] == cycle)
        got = sum(v[0] for k, v in cube.items() if k[0] == cycle_index[cycle])
        assert abs(expected - got) < 1, f"planned total of cycle {cycle} changed while aggregating"

    payload = {
        "cycles": cycles,
        "programmes": programmes,
        "funds": [{"code": f, "name": FUND_NAMES.get(f, f)} for f in fund_codes],
        "themes": [{"id": t["theme_id"], "name": t["theme_el"], "description": t["description"]} for t in themes],
        "specificObjectives": spec_list,
        "cube": [[*key, *(euros(v) for v in values)] for key, values in sorted(cube.items())],
        "interventions": [[*key, *(euros(v) for v in values)] for key, values in sorted(interventions.items())],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ---- Interreg ---------------------------------------------------------------------------------------

YEARS = list(range(2021, 2028))


def interreg_type(title):
    if "VI-A" in title:
        return "Διασυνοριακή συνεργασία"
    if "VI-B" in title:
        return "Διακρατική συνεργασία"
    return "Διαπεριφερειακή συνεργασία και ευρωπαϊκά δίκτυα"


def build_interreg():
    allocations = read("interreg_allocations.csv")
    territories = read("interreg_greek_territories.csv")
    greek_ccis = sorted({r["cci"] for r in territories})
    by_cci = defaultdict(list)
    for r in allocations:
        by_cci[r["cci"]].append(r)
    missing = [c for c in greek_ccis if c not in by_cci]
    assert not missing, f"programmes with Greek territories but no allocations: {missing}"

    covered = defaultdict(lambda: {"regions": set(), "units": set()})
    for r in territories:
        if r["nuts_level"] == "2":
            covered[r["cci"]]["regions"].add(r["nuts_code"])
        elif r["nuts_level"] == "3":
            covered[r["cci"]]["units"].add(r["nuts_code"])

    programmes = []
    for cci in greek_ccis:
        rows = by_cci[cci]
        title = rows[0]["programme_title"]
        lines = [{"fund": r["fund"], "fundName": FUND_NAMES.get(r["fund"], r["fund"]), "category": r["financial_allocation_category"],
                  "years": [euros(num(r[f"eu_commitment_{y}_eur"])) for y in YEARS], "total": euros(num(r["total_eu_commitments_eur"]))} for r in rows]
        for line in lines:
            assert abs(sum(line["years"]) - line["total"]) <= len(YEARS), f"yearly commitments of {cci} do not add up to the total"
        programmes.append({"cci": cci, "name": title, "type": interreg_type(title), "status": rows[0]["status"],
                           "version": rows[0]["programme_version"], "lines": lines,
                           "regions": sorted(covered[cci]["regions"]), "units": len(covered[cci]["units"])})
    all_total = sum(euros(num(r["total_eu_commitments_eur"])) for r in allocations)
    payload = {"years": YEARS, "programmes": programmes, "allProgrammes": len({r["cci"] for r in allocations}), "allTotal": all_total}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


BUILDERS = {"progress": build_progress, "interreg": build_interreg}


def main():
    check = "--check" in sys.argv
    stale = []
    for name, path in PAGES.items():
        document = path.read_text(encoding="utf-8")
        block = re.compile(rf'(<script id="{BLOCKS[name]}" type="application/json">)(.*?)(</script>)', re.S)
        match = block.search(document)
        if not match:
            sys.exit(f"no data block {BLOCKS[name]} found in {path}")
        generated = BUILDERS[name]()
        if check:
            if match.group(2).strip() != generated:
                stale.append(name)
            else:
                print(f"OK: {name} data in the dashboard matches the CSVs ({len(generated):,} characters).")
        else:
            path.write_text(document[:match.start(2)] + generated + document[match.end(2):], encoding="utf-8")
            print(f"wrote {len(generated):,} characters of data into {path.relative_to(ROOT)}")
    if stale:
        sys.exit(f"funding data of {', '.join(stale)} is out of date with the CSV files; run scripts/build_funding_data.py")


if __name__ == "__main__":
    main()
