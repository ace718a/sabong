#!/usr/bin/env python3
from __future__ import annotations

import html
import csv
import re
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.etree import ElementTree as ET

BASE_URL = "https://sabong.co.kr"
ROOT = Path(__file__).resolve().parents[2]
REGION_MAP = ROOT / "maps" / "region_map.csv"

EXCLUDED_FILES = {"about.html", "privacy.html"}
EXCLUDED_NAMES = {"404.html", "403.html", "500.html"}

CANONICAL_PATTERNS = (
    re.compile(
        r'<link\b[^>]*\brel=["\']canonical["\'][^>]*\bhref=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<link\b[^>]*\bhref=["\']([^"\']+)["\'][^>]*\brel=["\']canonical["\']',
        re.IGNORECASE,
    ),
)


def git_lastmod(relative_path: str) -> str:
    """Return the date of the latest Git commit that touched the file."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", relative_path],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        value = result.stdout.strip()
        if value:
            return value
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return date.today().isoformat()


def existing_lastmods(sitemap_path: Path) -> dict[str, str]:
    """Read the dates already published instead of resetting every URL."""
    if not sitemap_path.is_file():
        return {}
    try:
        root = ET.fromstring(sitemap_path.read_text(encoding="utf-8"))
    except (ET.ParseError, OSError, UnicodeDecodeError):
        return {}
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    result: dict[str, str] = {}
    for item in root.findall("sm:url", namespace):
        loc = item.findtext("sm:loc", default="", namespaces=namespace).strip()
        lastmod = item.findtext("sm:lastmod", default="", namespaces=namespace).strip()
        if loc and re.fullmatch(r"\d{4}-\d{2}-\d{2}", lastmod):
            result[loc] = lastmod
    return result


def previous_file(relative_path: str) -> str | None:
    """Return the file before the current commit when Git history is available."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD^:{relative_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError, UnicodeDecodeError):
        return None


def without_presentation(text: str) -> str:
    """Ignore inline CSS when deciding whether search-visible content changed."""
    return re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)


def content_lastmod(path: Path, url: str, old_dates: dict[str, str]) -> str:
    """Preserve lastmod for presentation-only edits; update real content edits."""
    rel = path.relative_to(ROOT).as_posix()
    old_date = old_dates.get(url)
    previous = previous_file(rel)
    if old_date and previous is not None:
        current = path.read_text(encoding="utf-8")
        if without_presentation(current) == without_presentation(previous):
            return old_date
    return git_lastmod(rel)


def canonical_url(index_file: Path) -> str | None:
    try:
        text = index_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    for pattern in CANONICAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def discover_subdomains() -> dict[str, str]:
    """Discover top-level city folders by the canonical host in index.html."""
    result: dict[str, str] = {}

    for child in sorted(ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue

        index_file = child / "index.html"
        if not index_file.is_file():
            continue

        canonical = canonical_url(index_file)
        if not canonical:
            continue

        parsed = urlparse(canonical)
        host = (parsed.hostname or "").lower()
        if host.endswith(".sabong.co.kr") and host != "sabong.co.kr":
            result[child.name] = f"https://{host}"

    return result


def should_include(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith(".github/"):
        return False
    if rel in EXCLUDED_FILES or path.name in EXCLUDED_FILES:
        return False
    if path.name in EXCLUDED_NAMES:
        return False
    return True


def root_html_files(subdomain_dirs: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.html"):
        rel = path.relative_to(ROOT).as_posix()
        if not should_include(path):
            continue
        if rel.split("/", 1)[0] in subdomain_dirs:
            continue
        files.append(path)
    return sorted(files, key=lambda p: (p.name != "index.html", p.as_posix()))


def subdomain_html_files(directory: Path) -> list[Path]:
    files = [path for path in directory.rglob("*.html") if should_include(path)]
    return sorted(
        files,
        key=lambda p: (
            p.relative_to(directory).as_posix() != "index.html",
            p.as_posix(),
        ),
    )


def encoded_path(relative_html: str) -> str:
    # Normalize work-environment #Uxxxx display names before URL encoding.
    relative_html = re.sub(r"#U([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), relative_html)
    if relative_html == "index.html":
        return "/"
    if relative_html.endswith("/index.html"):
        relative_html = relative_html[:-10]
    return "/" + quote(relative_html, safe="/~-._")


def build_xml(items: list[tuple[Path, str, bool]], old_dates: dict[str, str]) -> str:
    entries: list[str] = []

    for path, url, is_site_root in items:
        rel = path.relative_to(ROOT).as_posix()
        entries.append(
            "  <url>\n"
            f"    <loc>{html.escape(url)}</loc>\n"
            f"    <lastmod>{content_lastmod(path, url, old_dates)}</lastmod>\n"
            f"    <changefreq>{'weekly' if is_site_root else 'monthly'}</changefreq>\n"
            f"    <priority>{'1.0' if is_site_root else '0.7'}</priority>\n"
            "  </url>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


def main() -> None:
    subdomains = discover_subdomains()

    root_items: list[tuple[Path, str, bool]] = []
    for path in root_html_files(set(subdomains)):
        rel = path.relative_to(ROOT).as_posix()
        root_items.append((path, BASE_URL + encoded_path(rel), rel == "index.html"))

    root_sitemap = ROOT / "sitemap.xml"
    root_dates = existing_lastmods(root_sitemap)
    root_sitemap.write_text(build_xml(root_items, root_dates), encoding="utf-8")
    print(f"Generated sitemap.xml with {len(root_items)} URL(s).")

    with REGION_MAP.open(encoding="utf-8-sig", newline="") as f:
        rows = [row for row in csv.DictReader(f) if row["status"] == "published"]

    seen_urls: set[str] = set()
    seen_sources: set[str] = set()
    for row in rows:
        source = row["source_file"]
        canonical = row["canonical_url"]
        if source in seen_sources or canonical in seen_urls:
            raise RuntimeError(f"Duplicate region_map entry: {source} / {canonical}")
        seen_sources.add(source)
        seen_urls.add(canonical)
        path = ROOT / source
        if not path.is_file():
            raise FileNotFoundError(f"Mapped HTML missing: {source}")
        actual = canonical_url(path)
        if actual != canonical:
            raise RuntimeError(f"Canonical mismatch: {source}: {actual} != {canonical}")

    for folder, base_url in subdomains.items():
        directory = ROOT / folder
        items: list[tuple[Path, str, bool]] = []
        for row in rows:
            if row["city_key"] != folder:
                continue
            path = ROOT / row["source_file"]
            items.append((path, row["canonical_url"], row["level"] == "city"))

        city_sitemap = directory / "sitemap.xml"
        city_dates = existing_lastmods(city_sitemap)
        city_sitemap.write_text(build_xml(items, city_dates), encoding="utf-8")
        print(
            f"Generated {folder}/sitemap.xml with {len(items)} URL(s) "
            f"for {base_url}."
        )


if __name__ == "__main__":
    main()
