#!/usr/bin/env python3
from __future__ import annotations

import html
import subprocess
from datetime import date
from pathlib import Path

BASE_URL = "https://sabong.co.kr"
ROOT = Path(__file__).resolve().parents[2]

# 현재 메인에서 노출하지 않는 문서는 사이트맵에서 제외합니다.
EXCLUDED_FILES = {
    "about.html",
    "privacy.html",
}

# 향후 생성될 수 있는 공통 오류/임시 파일도 자동 제외합니다.
EXCLUDED_NAMES = {
    "404.html",
    "403.html",
    "500.html",
}


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


def html_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.html"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(".github/"):
            continue
        if rel in EXCLUDED_FILES or path.name in EXCLUDED_NAMES:
            continue
        files.append(path)
    return sorted(files, key=lambda p: (p.name != "index.html", p.as_posix()))


def url_for(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    if rel == "index.html":
        return f"{BASE_URL}/"
    # /folder/index.html -> /folder/
    if rel.endswith("/index.html"):
        return f"{BASE_URL}/{rel[:-10]}"
    return f"{BASE_URL}/{rel}"


def priority_for(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return "1.0" if rel == "index.html" else "0.7"


def changefreq_for(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return "weekly" if rel == "index.html" else "monthly"


def main() -> None:
    entries = []
    for path in html_files():
        rel = path.relative_to(ROOT).as_posix()
        entries.append(
            "  <url>\n"
            f"    <loc>{html.escape(url_for(path))}</loc>\n"
            f"    <lastmod>{git_lastmod(rel)}</lastmod>\n"
            f"    <changefreq>{changefreq_for(path)}</changefreq>\n"
            f"    <priority>{priority_for(path)}</priority>\n"
            "  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + '\n</urlset>\n'
    )
    (ROOT / "sitemap.xml").write_text(xml, encoding="utf-8")
    print(f"Generated sitemap.xml with {len(entries)} URL(s).")


if __name__ == "__main__":
    main()
