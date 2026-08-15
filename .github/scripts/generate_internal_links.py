#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "maps" / "region_map.csv"

parser = argparse.ArgumentParser()
parser.add_argument(
    "--batch-prefix",
    help="신규 batch_id 접두어. 지정하면 신규 페이지와 직접 영향받는 부모 구·군 페이지만 수정합니다.",
)
args = parser.parse_args()

with MAP.open(encoding="utf-8-sig", newline="") as f:
    rows = [r for r in csv.DictReader(f) if r["status"] == "published"]

by_city = {}
for row in rows:
    by_city.setdefault(row["city_key"], []).append(row)


def rotate(items, seed):
    if not items:
        return []
    n = seed % len(items)
    return items[n:] + items[:n]


def dedupe(items, source):
    result, seen = [], {source["source_file"]}
    for row in items:
        if row["source_file"] not in seen:
            seen.add(row["source_file"])
            result.append(row)
    return result


def candidates(source, index):
    city = by_city[source["city_key"]]
    city_page = [r for r in city if r["level"] == "city"]
    districts = [r for r in city if r["level"] == "district"]
    localities = [r for r in city if r["level"] == "locality"]
    own = [r for r in localities if r["district_name"] == source["district_name"]]
    other_locs = [r for r in localities if r["district_name"] != source["district_name"]]
    sibling_districts = [r for r in districts if r["district_name"] != source["district_name"]]
    if source["level"] == "city":
        ordered = rotate(districts, index) + rotate(localities, index * 3)
    elif source["level"] == "district":
        ordered = rotate(own, index) + rotate(sibling_districts, index) + city_page + rotate(other_locs, index * 3)
    else:
        parent = [r for r in districts if r["district_name"] == source["district_name"]]
        ordered = rotate(own, index + 1) + parent + city_page + rotate(sibling_districts, index) + rotate(other_locs, index * 3)
    return dedupe(ordered, source)[:10]


def label(row):
    if row["level"] == "city":
        return f"{row['city_name']} 이사청소"
    if row["level"] == "district":
        return f"{row['district_name']} 입주청소"
    return row["locality_name"]


def href(row):
    return unquote(urlparse(row["canonical_url"]).path)


box_re = re.compile(r'(<div class="region-intro-box region-link-box"><h2>.*?</h2><p>).*?(</p></div>)', re.S)
href_re = re.compile(r'<a\s+href="([^"]+)"')

if args.batch_prefix:
    new_rows = [r for r in rows if r.get("batch_id", "").startswith(args.batch_prefix)]
    if not new_rows:
        raise RuntimeError(f"batch prefix에 해당하는 페이지가 없습니다: {args.batch_prefix}")
    parent_keys = {(r["city_key"], r["district_name"]) for r in new_rows if r["level"] == "locality"}
    targets = {
        r["source_file"]
        for r in rows
        if r in new_rows or (r["level"] == "district" and (r["city_key"], r["district_name"]) in parent_keys)
    }
else:
    targets = {r["source_file"] for r in rows}

# 수정하지 않는 페이지의 현재 링크 묶음을 먼저 예약해 전역 중복을 방지한다.
used_sets = set()
for row in rows:
    if row["source_file"] in targets:
        continue
    raw = (ROOT / row["source_file"]).read_text(encoding="utf-8")
    match = box_re.search(raw)
    if match:
        links = tuple(sorted(href_re.findall(match.group(0))))
        if len(links) == 10:
            used_sets.add(links)

changed = 0
for index, source in enumerate(rows):
    if source["source_file"] not in targets:
        continue
    links = []
    for bump in range(max(1, len(by_city[source["city_key"]]))):
        proposal = candidates(source, index + bump * 11)
        key = tuple(sorted(href(r) for r in proposal))
        if key not in used_sets:
            links = proposal
            used_sets.add(key)
            break
    if not links:
        raise RuntimeError(f"unique link set unavailable: {source['source_file']}")
    if len(links) != 10:
        raise RuntimeError(f"10 links unavailable: {source['source_file']} ({len(links)})")
    path = ROOT / source["source_file"]
    raw = path.read_text(encoding="utf-8")
    inner = " · ".join(f'<a href="{escape(href(r), quote=True)}">{escape(label(r))}</a>' for r in links)
    updated, n = box_re.subn(lambda m: m.group(1) + inner + m.group(2), raw, count=1)
    if n != 1:
        raise RuntimeError(f"link box not found: {source['source_file']}")
    if updated != raw:
        path.write_text(updated, encoding="utf-8", newline="")
        changed += 1

print(f"Internal-link targets: {len(targets)} / updated: {changed}")
