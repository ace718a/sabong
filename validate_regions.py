#!/usr/bin/env python3
from __future__ import annotations
import csv, json, re, sys, zipfile
from pathlib import Path
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup
from collections import Counter
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
MAP = ROOT / "maps" / "region_map.csv"
CITIES = {"seoul":"서울","busan":"부산","daegu":"대구","daejeon":"대전","incheon":"인천","gwangju":"광주","ulsan":"울산","suwon":"수원","yongin":"용인","goyang":"고양"}
ESCAPE_RE = re.compile(r"#U[0-9A-Fa-f]{4}|%u[0-9A-Fa-f]{4}|\\\\u[0-9A-Fa-f]{4}")
FORBIDDEN_SPLIT_LOCALITIES = {"역삼1동","역삼2동","대저일동","대저이동","판암1동","판암2동","가양1동","가양2동","영종1동","영종2동","영종3동","운서1동","운서2동"}
ALLOWED_HOSTS = {"schema.org", "cleanm.kr", "co10.kr", "www.sitemaps.org"}
PLACEHOLDER_RE = re.compile(r"TODO|PLACEHOLDER|{{[^}]+}}|\[\[[^]]+]]|__+[A-Z][A-Z0-9_]*__+")

errors, warnings = [], []

def err(x): errors.append(x)
def warn(x): warnings.append(x)

def escaped_segment(name: str) -> str:
    return "".join(f"#U{ord(ch):x}" if ord(ch) > 127 else ch for ch in name)

def fs_path(relative: str) -> Path:
    p=ROOT/relative
    if p.exists(): return p
    cur=ROOT
    for part in Path(relative).parts:
        normal=cur/part; escaped=cur/escaped_segment(part)
        cur = normal if normal.exists() else escaped if escaped.exists() else normal
    return cur

def logical_rel(path: Path) -> str:
    def dec(seg):
        return re.sub(r"#U([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1),16)), seg)
    return "/".join(dec(x) for x in path.relative_to(ROOT).parts)

def soup(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

if not MAP.exists():
    err("maps/region_map.csv 없음")
    rows=[]
else:
    with MAP.open(encoding="utf-8-sig", newline="") as f:
        rows=list(csv.DictReader(f))
row_by_source={r["source_file"]:r for r in rows}
row_by_city_path={(r["city_key"],unquote(urlparse(r["canonical_url"]).path)):r for r in rows}

# Map uniqueness and actual file correspondence.
keys, canonicals, sources = [], [], []
for r in rows:
    key=(r["city_key"],r["district_name"],r["locality_name"],r["level"])
    keys.append(key); canonicals.append(r["canonical_url"]); sources.append(r["source_file"])
    p=fs_path(r["source_file"])
    if not p.exists(): err(f"map에는 있으나 HTML 없음: {r['source_file']}")
    if ESCAPE_RE.search(r["source_file"]) or ESCAPE_RE.search(r["path"]) or ESCAPE_RE.search(r["canonical_url"]):
        err(f"map escape 경로: {r['source_file']}")
    if r["locality_name"] in FORBIDDEN_SPLIT_LOCALITIES:
        err(f"대표 동명 대신 분할 행정동 사용: {r['source_file']}")

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

mapped={logical_rel(fs_path(r["source_file"])) for r in rows}
for p in actual:
    if logical_rel(p) not in mapped: err(f"HTML은 있으나 map에 없음: {logical_rel(p)}")

titles=[]; descs=[]; heroes=[]; internal_link_sets=[]; locality_intros=[]; metadata_rows=[]
for p in actual:
    rel=logical_rel(p)
    raw=p.read_text(encoding="utf-8")
    s=BeautifulSoup(raw, "html.parser")
    if len(re.findall(r"<!doctype\s+html\s*>", raw, re.I)) != 1: err(f"DOCTYPE 개수 오류: {rel}")
    if ".png" in raw.lower(): err(f"PNG 참조 잔존: {rel}")
    if len(s.find_all("h1")) != 1: err(f"H1 개수 오류: {rel}")
    title=s.title.get_text(" ",strip=True) if s.title else ""
    md=s.find("meta",attrs={"name":"description"})
    desc=md.get("content","").strip() if md else ""
    can=s.find("link",rel="canonical")
    canonical=can.get("href","").strip() if can else ""
    og=s.find("meta",attrs={"property":"og:url"})
    ogurl=og.get("content","").strip() if og else ""
    ogtitle=(s.find("meta",attrs={"property":"og:title"}) or {}).get("content","").strip()
    ogdesc=(s.find("meta",attrs={"property":"og:description"}) or {}).get("content","").strip()
    twtitle=(s.find("meta",attrs={"name":"twitter:title"}) or {}).get("content","").strip()
    twdesc=(s.find("meta",attrs={"name":"twitter:description"}) or {}).get("content","").strip()
    if not title: err(f"title 없음: {rel}")
    if not desc: err(f"description 없음: {rel}")
    if not canonical: err(f"canonical 없음: {rel}")
    if canonical and ogurl != canonical: err(f"og:url != canonical: {rel}")
    if ogtitle!=title or twtitle!=title: err(f"TITLE ↔ OG/Twitter 불일치: {rel}")
    if ogdesc!=desc or twdesc!=desc: err(f"description ↔ OG/Twitter 불일치: {rel}")
    if not 20<=len(title)<=65: err(f"TITLE 권장 범위 이탈({len(title)}자): {rel}")
    if not 70<=len(desc)<=200: err(f"description 권장 범위 이탈({len(desc)}자): {rel}")
    if ESCAPE_RE.search(p.read_text(encoding="utf-8")):
        err(f"escape 문자열 발견: {rel}")
    if PLACEHOLDER_RE.search(raw): err(f"placeholder/템플릿 토큰 발견: {rel}")
    for host in re.findall(r"https?://([^/\s\"'<>]+)", raw, re.I):
        host=host.lower().split(":",1)[0]
        if host not in ALLOWED_HOSTS and not (host=="sabong.co.kr" or host.endswith(".sabong.co.kr")):
            err(f"허용되지 않은 외부 도메인: {rel} -> {host}")
    for im in s.find_all("img"):
        if not im.has_attr("alt") or not im.get("alt","").strip(): err(f"ALT 누락: {rel}")
        if not im.get("width") or not im.get("height"): err(f"이미지 크기 속성 누락: {rel}")
        if im.get("loading") != "lazy": err(f"이미지 lazy loading 누락: {rel}")
        src=im.get("src","")
        if src and not src.startswith(("http://","https://","//","data:")):
            target=(ROOT/p.relative_to(ROOT).parts[0]/unquote(urlparse(src).path).lstrip("/")) if src.startswith("/") else (p.parent/unquote(urlparse(src).path))
            if not target.exists(): err(f"이미지 파일 없음: {rel} -> {src}")
    for a in s.find_all("a", href=True):
        href=a.get("href","")
        if not href or href.startswith(("#","http://","https://","//","mailto:","tel:","javascript:")): continue
        path=unquote(urlparse(href).path)
        target=(ROOT/p.relative_to(ROOT).parts[0]/path.lstrip("/")) if path.startswith("/") else (p.parent/path)
        if path.endswith("/"): target=target/"index.html"
        if not target.exists(): err(f"내부링크 대상 없음: {rel} -> {href}")
    webpage_schema=None
    for sc in s.find_all("script",attrs={"type":"application/ld+json"}):
        try:
            parsed=json.loads(sc.string or sc.get_text())
            if parsed.get("@type") in {"WebPage","WebSite"}: webpage_schema=parsed
        except Exception: err(f"JSON-LD 파싱 오류: {rel}")
    if not webpage_schema or webpage_schema.get("name")!=title or webpage_schema.get("description")!=desc:
        err(f"TITLE/description ↔ WebPage JSON-LD 불일치: {rel}")
    h=s.find("h1"); hp=h.find_next("p") if h else None
    hero=hp.get_text(" ",strip=True) if hp else ""
    if len(hero)<50: err(f"Hero 너무 짧음: {rel}")
    intro=s.select_one("section.region-intro")
    if intro and intro.find_all("p",recursive=False): err(f"region-intro 문단 박스 이탈: {rel}")
    box=s.select_one(".region-intro-box")
    if p.parent.name not in CITIES:
        if not box: err(f"region-intro-box 없음: {rel}")
        else:
            paragraphs=box.find_all("p",recursive=False)
            body=" ".join(x.get_text(" ",strip=True) for x in paragraphs)
            if len(body)<320: err(f"region-intro-box 본문 320자 미만: {rel}")
            if len(body)>550: err(f"region-intro-box 본문 550자 초과({len(body)}자): {rel}")
            sentences=[re.sub(r"\s+"," ",x.strip()) for x in re.split(r"(?<=[.!?])\s+|(?<=다\.)",body) if len(x.strip())>=20]
            if any(n>1 for n in Counter(sentences).values()): err(f"region-intro-box 동일 문장 반복: {rel}")
            row=row_by_source.get(rel)
            if row and row["level"]=="locality": locality_intros.append((row,body))
    link_box=s.select_one(".region-link-box")
    if not link_box:
        err(f"지역 내부링크 박스 없음: {rel}")
    else:
        link_hrefs=[a.get("href","").strip() for a in link_box.find_all("a",href=True)]
        if len(link_hrefs)!=10: err(f"지역 내부링크 10개 아님({len(link_hrefs)}): {rel}")
        if len(set(link_hrefs))!=len(link_hrefs): err(f"지역 내부링크 중복: {rel}")
        parts=Path(rel).parts
        self_href="/" if len(parts)==2 else f"/{parts[1]}/" if len(parts)==3 else f"/{parts[1]}/{parts[2]}/"
        if self_href in link_hrefs: err(f"지역 내부링크 자기 자신 포함: {rel}")
        source_row=row_by_source.get(rel)
        if source_row:
            targets=[row_by_city_path.get((source_row["city_key"],unquote(urlparse(href).path))) for href in link_hrefs]
            if any(x is None for x in targets):
                err(f"지역 내부링크 map 미등록 대상 포함: {rel}")
            else:
                city_rows=[r for r in rows if r["city_key"]==source_row["city_key"]]
                if source_row["level"]=="city":
                    available=sum(r["level"]=="district" for r in city_rows)
                    selected=sum(r["level"]=="district" for r in targets)
                    if selected!=min(10,available): err(f"시 페이지 구·군 링크 우선순위 오류: {rel}")
                elif source_row["level"]=="district":
                    available=sum(r["level"]=="locality" and r["district_name"]==source_row["district_name"] for r in city_rows)
                    selected=sum(r["level"]=="locality" and r["district_name"]==source_row["district_name"] for r in targets)
                    if selected!=min(10,available): err(f"구·군 페이지 하위 지역 링크 우선순위 오류: {rel}")
                else:
                    available=sum(r["level"]=="locality" and r["district_name"]==source_row["district_name"] and r["source_file"]!=rel for r in city_rows)
                    selected=sum(r["level"]=="locality" and r["district_name"]==source_row["district_name"] for r in targets)
                    if selected!=min(10,available): err(f"동·읍·면 페이지 같은 구 링크 우선순위 오류: {rel}")
        internal_link_sets.append(tuple(sorted(link_hrefs)))
    titles.append(title); descs.append(desc); heroes.append(hero)
    row=row_by_source.get(rel)
    if row: metadata_rows.append((row,title,desc))

for label, vals in [("title",titles),("description",descs),("Hero",heroes)]:
    dup=[x for x,n in Counter(vals).items() if x and n>1]
    if dup: err(f"duplicate {label}: {len(dup)}개 그룹")
if len(set(internal_link_sets)) != len(internal_link_sets):
    err(f"동일한 내부링크 10개 묶음 반복: {len(internal_link_sets)-len(set(internal_link_sets))}페이지")

# Short metadata naturally shares service keywords, but a large group that only
# changes the region name is rejected. This catches mass city/district/locality
# cloning without forcing every concise title to use unnatural synonyms.
for level in ("city","district","locality"):
    level_items=[x for x in metadata_rows if x[0]["level"]==level]
    for label,index,limit in (("TITLE",1,3),("description",2,2)):
        masked=[]
        for row,title,desc in level_items:
            text=(title,desc)[index-1]
            for name in (row["city_name"],row["district_name"],row["locality_name"]):
                if name: text=text.replace(name,"[지역]")
            masked.append(re.sub(r"\s+"," ",text).strip())
        largest=max(Counter(masked).values(),default=0)
        if largest>limit: err(f"{level} 지역명 치환형 {label} 반복 과다(최대 {largest}개)")

# Same-city locality pages: mask their own region names, then reject excessive
# shared five-word runs. Adding repeated filler cannot be used to game this check.
for ck in CITIES:
    items=[x for x in locality_intros if x[0]["city_key"]==ck]
    for i,(ra,ta) in enumerate(items):
        for rb,tb in items[i+1:]:
            normalized=[]
            for row,text in ((ra,ta),(rb,tb)):
                for name in (row["city_name"],row["district_name"],row["locality_name"]):
                    if name: text=text.replace(name," [REGION] ")
                normalized.append(re.sub(r"\s+"," ",text).strip())
            sets=[]
            for text in normalized:
                words=text.split()
                sets.append({tuple(words[n:n+5]) for n in range(max(0,len(words)-4))})
            score=len(sets[0]&sets[1])/max(1,min(len(sets[0]),len(sets[1])))
            if score>.45:
                err(f"동일 도시 본문 유사도 45% 초과({score:.3%}): {ra['source_file']} <> {rb['source_file']}")

# Parent hierarchy and city sitemap coverage.
for r in rows:
    if r["level"]=="locality":
        parent=fs_path(f"{r['city_key']}/{r['district_name']}/index.html")
        if not parent.exists(): err(f"동 페이지 부모 구·군 없음: {r['source_file']}")
        expected=f"{r['city_key']}/{r['district_name']}/{r['locality_name']}/index.html"
        if r["source_file"]!=expected: err(f"동 페이지 계층 오류: {r['source_file']}")

for ck in CITIES:
    sm=ROOT/ck/"sitemap.xml"
    if not sm.exists():
        err(f"{ck}/sitemap.xml 없음"); continue
    txt=sm.read_text(encoding="utf-8")
    if ESCAPE_RE.search(txt): err(f"{ck} sitemap escape 경로")
    expected={unquote(r["canonical_url"]) for r in rows if r["city_key"]==ck}
    try:
        tree=ET.fromstring(txt)
        found=[unquote(x.text.strip()) for x in tree.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc") if x.text]
        if len(found)!=len(set(found)): err(f"{ck} sitemap URL 중복")
        if set(found)!=expected:
            err(f"{ck} sitemap ↔ map 불일치(누락 {len(expected-set(found))}, 잔존 {len(set(found)-expected)})")
    except ET.ParseError:
        err(f"{ck} sitemap XML 파싱 오류")

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
