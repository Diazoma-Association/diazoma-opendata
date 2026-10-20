#!/usr/bin/env python3
"""Build the map geometries of the agriculture dashboards: 13 regions, the regional units (περιφερειακές ενότητες) and the
prefectures (νομοί) of the farm structure surveys.

Usage:
    python3 scripts/build_agriculture_geometry.py                  # download LAU, write data/agriculture/geo/greece_units.json
    python3 scripts/build_agriculture_geometry.py --lau lau.geojson  # use an already downloaded LAU file

Source: Eurostat GISCO, Local Administrative Units (LAU) 2021, 1:1 million, © EuroGeographics
    https://ec.europa.eu/eurostat/web/gisco/geodata/administrative-units/local-administrative-units
Every Greek LAU of the file is a community or municipal unit whose id starts with the ELSTAT number of the regional
unit it belongs to (the number the SPG06 agricultural tables use: 01 Ροδόπης … 74 Χανίων, 99 Άγιον Όρος), so the real
administrative boundaries of the regional units are obtained by merging the LAUs with the same two-digit prefix; the
regions are the merge of their units, a zone (NUTS 1, used by the regional agricultural accounts) the merge of its regions, and a prefecture is the merge of the units listed for it in agri_geo.PREFECTURES. The 52 NUTS 3 areas of Eurostat cannot be used: they group several regional
units (e.g. Άρτα + Πρέβεζα) while ELSTAT publishes the tables per regional unit.

The geometries are simplified to roughly one kilometre and written as SVG paths in a projection that keeps
shapes (x = longitude × cos 38°, y = latitude). Needs shapely (pip install shapely). The downloaded file is about
126 MB and is not kept.
"""

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from shapely.geometry import shape, MultiPolygon, Polygon
from shapely.ops import unary_union

import agri_geo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "agriculture" / "geo" / "greece_units.json"
LAU_URL = "https://gisco-services.ec.europa.eu/distribution/v2/lau/geojson/LAU_RG_01M_2021_4326.geojson"
WIDTH = 1000.0
LAT0 = math.cos(math.radians(38))
TOLERANCE = 0.006  # degrees (about 650 m); the source scale is 1:1 000 000
MIN_AREA_KM2 = 2.0  # islets smaller than this are dropped, except the largest part of every unit


def load_greek_lau(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [f for f in data["features"] if f["properties"]["CNTR_CODE"] == "EL"]


def download(target):
    result = subprocess.run(["curl", "-sSL", "--fail", "--max-time", "600", "-o", str(target), LAU_URL], capture_output=True)
    if result.returncode:
        sys.exit(f"download failed: {result.stderr.decode('utf-8', 'ignore')}")


def km2(polygon):
    lat = polygon.centroid.y
    return polygon.area * 111.0 * 111.0 * math.cos(math.radians(lat))


def keep_parts(geometry):
    parts = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
    parts.sort(key=lambda p: -p.area)
    kept = [p for p in parts if km2(p) >= MIN_AREA_KM2] or parts[:1]
    return MultiPolygon([Polygon(p.exterior) for p in kept])  # holes are not drawn at this scale


def path_of(geometry, project):
    """SVG path with relative integer-tenths coordinates."""
    out = []
    for part in geometry.geoms:
        ring = [project(x, y) for x, y in part.exterior.coords]
        last = None
        for i, (x, y) in enumerate(ring[:-1]):
            x, y = round(x * 10), round(y * 10)
            if last is None:
                out.append(f"M{x / 10:g} {y / 10:g}")
            elif (x, y) != last:
                out.append(f"l{(x - last[0]) / 10:g} {(y - last[1]) / 10:g}")
            last = (x, y)
        out.append("z")
    return "".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lau", help="LAU GeoJSON already downloaded")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        source = args.lau
        if not source:
            source = Path(tmp) / "lau.geojson"
            download(source)
        features = load_greek_lau(source)

    by_unit = {}
    for f in features:
        by_unit.setdefault(f["properties"]["LAU_ID"][:2], []).append(shape(f["geometry"]))
    known = {u[0] for u in agri_geo.UNITS}
    if set(by_unit) != known:
        sys.exit(f"LAU prefixes differ from the ELSTAT unit numbers: {sorted(set(by_unit) ^ known)}")

    units = {num: unary_union(geoms).buffer(0) for num, geoms in by_unit.items()}
    regions = {}
    for num, geom in units.items():
        regions.setdefault(agri_geo.unit_region(num), []).append(geom)
    regions = {code: unary_union(geoms).buffer(0) for code, geoms in regions.items()}

    prefectures = {"NO" + code: unary_union([units[n] for n in members]).buffer(0) for code, members in agri_geo.prefecture_units().items()}
    zones = {code: unary_union([regions[r] for r in members]).buffer(0) for code, members in agri_geo.zone_regions().items()}
    simple_units = {n: keep_parts(g.simplify(TOLERANCE, preserve_topology=True)) for n, g in units.items()}
    simple_regions = {c: keep_parts(g.simplify(TOLERANCE, preserve_topology=True)) for c, g in regions.items()}
    simple_zones = {c: keep_parts(g.simplify(TOLERANCE, preserve_topology=True)) for c, g in zones.items()}
    simple_prefectures = {c: keep_parts(g.simplify(TOLERANCE, preserve_topology=True)) for c, g in prefectures.items()}

    minx = min(g.bounds[0] for g in simple_regions.values())
    maxx = max(g.bounds[2] for g in simple_regions.values())
    miny = min(g.bounds[1] for g in simple_regions.values())
    maxy = max(g.bounds[3] for g in simple_regions.values())
    scale = WIDTH / ((maxx - minx) * LAT0)
    height = (maxy - miny) * scale

    def project(x, y):
        return (x - minx) * LAT0 * scale, (maxy - y) * scale

    def centroid(g):
        c = g.representative_point()
        x, y = project(c.x, c.y)
        return [round(x, 1), round(y, 1)]

    document = {
        "source": "Eurostat GISCO, LAU 2021 (1:1 000 000), © EuroGeographics; regional units merged from LAU by ELSTAT unit number",
        "viewBox": [0, 0, round(WIDTH), round(height)],
        "regions": {c: {"path": path_of(g, project), "label": centroid(g)} for c, g in sorted(simple_regions.items())},
        "units": {"PE" + n: {"path": path_of(g, project), "label": centroid(g)} for n, g in sorted(simple_units.items())},
        "zones": {c: {"path": path_of(g, project), "label": centroid(g)} for c, g in sorted(simple_zones.items())},
        "prefectures": {c: {"path": path_of(g, project), "label": centroid(g)} for c, g in sorted(simple_prefectures.items())},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    size = OUT.stat().st_size
    print(f"wrote {OUT.relative_to(ROOT)}: {len(document['regions'])} regions, {len(document['units'])} units, "
          f"{len(document['prefectures'])} prefectures, {len(document['zones'])} zones, "
          f"viewBox {document['viewBox']}, {size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
