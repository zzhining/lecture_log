#!/usr/bin/env python3
"""하위 폴더의 html을 스캔해 pages.json을 생성한다.

- 루트 바로 아래 폴더 = 메뉴(카테고리). '.'/'_' 로 시작하는 폴더, scripts 는 제외.
- 폴더 표시 이름은 folders.json 에 {"book": "도서"} 형태로 지정 (없으면 폴더명 사용).
- 각 html 의 <title> 을 제목으로, 없으면 파일명을 사용. 폴더 안 하위 폴더도 재귀 탐색.
- 어떤 폴더에 index.html 이 있으면 그 폴더는 '허브'로 보고, 메뉴에는 index.html 한 줄만 올린다.
  (허브 안의 다른 html 은 허브 페이지에서 링크로 연결)
"""
import html, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE = {"scripts", "node_modules", "temp"}

def title_of(p: Path) -> str:
    try:
        head = p.read_text(encoding="utf-8", errors="ignore")[:8000]
    except OSError:
        head = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
    t = html.unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""
    return t or p.stem.replace("_", " ").replace("-", " ")

def main():
    labels = {}
    fj = ROOT / "folders.json"
    if fj.exists():
        labels = json.loads(fj.read_text(encoding="utf-8"))
    cats = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")) or d.name in EXCLUDE:
            continue
        files = sorted(d.rglob("*.html"), key=lambda p: p.as_posix().lower())
        hubs = [p.parent for p in files if p.name == "index.html"]
        files = [f for f in files if not any(h in f.parents and f != h / "index.html" for h in hubs)]
        if not files:
            continue
        cats.append({
            "id": d.name,
            "name": labels.get(d.name, d.name),
            "pages": [{"title": title_of(f), "path": f.relative_to(ROOT).as_posix()} for f in files],
        })
    out = json.dumps({"categories": cats}, ensure_ascii=False, indent=2) + "\n"
    (ROOT / "pages.json").write_text(out, encoding="utf-8", newline="\n")
    print(f"pages.json: {len(cats)} categories, {sum(len(c['pages']) for c in cats)} pages")

if __name__ == "__main__":
    sys.exit(main())
