#!/usr/bin/env python3
from __future__ import annotations
import csv, json, re, sys, zipfile
from pathlib import Path
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup
from collections import Counter

ROOT = Path(__file__).resolve().parent
MAP = ROOT / "maps" / "region_map.csv"
CITIES = {"seoul":"서울","busan":"부산","daegu":"대구","daejeon":"대전","incheon":"인천"}
ESCAPE_RE = re.compile(r"#U[0-9A-Fa-f]{4}|%u[0-9A-Fa-f]{4}|\\\\u[0-9A-Fa-f]{4}")

errors, warnings = [], []

def err(x): errors.append(x)
def warn(x): warnings.append(x)

def soup(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

if not MAP.exists():
    err("maps/region_map.csv 없음")
    rows=[]
else:
    with MAP.open(encoding="utf-8-sig", newline="") as f:
        rows=list(csv.DictReader(f))

# Map uniqueness and actual file correspondence.
keys, canonicals, sources = [], [], []
for r in rows:
    key=(r["city_key"],r["district_name"],r["locality_name"],r["level"])
    keys.append(key); canonicals.append(r["canonical_url"]); sources.append(r["source_file"])
    p=ROOT/r["source_file"]
    if not p.exists(): err(f"map에는 있으나 HTML 없음: {r['source_file']}")
    if ESCAPE_RE.search(r["source_file"]) or ESCAPE_RE.search(r["path"]) or ESCAPE_RE.search(r["canonical_url"]):
        err(f"map escape 경로: {r['source_file']}")

for label, vals in [("지역키",keys),("canonical",canonicals),("source_file",sources)]:
    dup=[x for x,n in Counter(vals).items() if x and n>1]
    if dup: err(f"중복 {label}: {dup[:5]}")

# Actual managed region pages.
actual=[]
for ck in CITIES:
    cp=ROOT/ck/"index.html"
    if cp.exists(): actual.append(cp)
    for d in (ROOT/ck).iterdir():
        if not d.is_dir() or d.name=="assets": continue
        dp=d/"index.html"
        if dp.exists(): actual.append(dp)
        # locality pages are one level below district
        for loc in d.iterdir():
            if loc.is_dir() and (loc/"index.html").exists():
                actual.append(loc/"index.html")

mapped={str((ROOT/r["source_file"]).resolve()) for r in rows}
for p in actual:
    if str(p.resolve()) not in mapped: err(f"HTML은 있으나 map에 없음: {p.relative_to(ROOT)}")

titles=[]; descs=[]; heroes=[]
for p in actual:
    rel=p.relative_to(ROOT).as_posix()
    s=soup(p)
    if len(s.find_all("h1")) != 1: err(f"H1 개수 오류: {rel}")
    title=s.title.get_text(" ",strip=True) if s.title else ""
    md=s.find("meta",attrs={"name":"description"})
    desc=md.get("content","").strip() if md else ""
    can=s.find("link",rel="canonical")
    canonical=can.get("href","").strip() if can else ""
    og=s.find("meta",attrs={"property":"og:url"})
    ogurl=og.get("content","").strip() if og else ""
    if not title: err(f"title 없음: {rel}")
    if not desc: err(f"description 없음: {rel}")
    if not canonical: err(f"canonical 없음: {rel}")
    if canonical and ogurl != canonical: err(f"og:url != canonical: {rel}")
    if ESCAPE_RE.search(rel) or ESCAPE_RE.search(p.read_text(encoding="utf-8")):
        err(f"escape 문자열 발견: {rel}")
    for im in s.find_all("img"):
        if not im.has_attr("alt") or not im.get("alt","").strip(): err(f"ALT 누락: {rel}")
    for sc in s.find_all("script",attrs={"type":"application/ld+json"}):
        try: json.loads(sc.string or sc.get_text())
        except Exception: err(f"JSON-LD 파싱 오류: {rel}")
    h=s.find("h1"); hp=h.find_next("p") if h else None
    hero=hp.get_text(" ",strip=True) if hp else ""
    if len(hero)<50: err(f"Hero 너무 짧음: {rel}")
    box=s.select_one(".region-intro-box")
    if p.parent.name not in CITIES:
        if not box: err(f"region-intro-box 없음: {rel}")
        elif len(box.get_text(" ",strip=True))<320: err(f"region-intro-box 320자 미만: {rel}")
    titles.append(title); descs.append(desc); heroes.append(hero)

for label, vals in [("title",titles),("description",descs),("Hero",heroes)]:
    dup=[x for x,n in Counter(vals).items() if x and n>1]
    if dup: err(f"duplicate {label}: {len(dup)}개 그룹")

# Parent hierarchy and city sitemap coverage.
for r in rows:
    if r["level"]=="locality":
        parent=ROOT/r["city_key"]/r["district_name"]/"index.html"
        if not parent.exists(): err(f"동 페이지 부모 구·군 없음: {r['source_file']}")
        expected=(ROOT/r["city_key"]/r["district_name"]/r["locality_name"]/"index.html").resolve()
        if (ROOT/r["source_file"]).resolve()!=expected: err(f"동 페이지 계층 오류: {r['source_file']}")

for ck in CITIES:
    sm=ROOT/ck/"sitemap.xml"
    if not sm.exists():
        err(f"{ck}/sitemap.xml 없음"); continue
    txt=sm.read_text(encoding="utf-8")
    if ESCAPE_RE.search(txt): err(f"{ck} sitemap escape 경로")
    expected=[r["canonical_url"] for r in rows if r["city_key"]==ck]
    for u in expected:
        # sitemap may contain Unicode while canonical is percent encoded.
        if u not in txt and unquote(u) not in txt: err(f"{ck} sitemap 누락: {u}")

# Root sitemap must not publish city subdomain trees as sabong.co.kr/city/...
root_sm=(ROOT/"sitemap.xml").read_text(encoding="utf-8") if (ROOT/"sitemap.xml").exists() else ""
for ck in CITIES:
    if f"https://sabong.co.kr/{ck}/" in root_sm: err(f"루트 sitemap에 서브도메인 폴더 URL 혼입: {ck}")

# Filesystem display check is informational only. ZIP central directory is authoritative for ZIP corruption.
fs_escape=[str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if ESCAPE_RE.search(p.name)]
if fs_escape: warn(f"작업환경 파일명 escape 표시 {len(fs_escape)}건 — 원본/최종 ZIP central directory로 최종 판정")

print(f"Managed pages: {len(actual)} / map rows: {len(rows)}")
print(f"Warnings: {len(warnings)}")
for x in warnings: print("WARN:",x)
if errors:
    print(f"QA FAIL: {len(errors)} error(s)")
    for x in errors: print("ERROR:",x)
    sys.exit(1)
print("QA PASS")
