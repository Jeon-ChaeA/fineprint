"""약관 PDF를 조항 단위로 나눈다.

사용법:
    python scripts/parse_terms.py --raw data/raw --out data/processed

- data/sources.json에 적힌 문서를 읽는다. 받은 파일의 sha256이 다르면 경고한다.
- 2단 편집 PDF(카카오뱅크 등)는 페이지를 왼쪽/오른쪽 열로 나눠 읽는다.
- 약관·약정서는 "제N조" 단위로, 상품설명서는 페이지 단위로 나눈다.
- 결과: data/processed/{id}.txt (전체 텍스트), data/processed/{id}.json (조항 목록)
  원문에서 나온 결과물이므로 레포에 올리지 않는다(.gitignore).
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
# 제목 안에 괄호가 또 있는 경우(카드 표준약관 "제14조(단기카드대출(현금서비스))")도 잡도록 바깥 괄호까지 읽는다
ARTICLE_RE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:\(((?:[^()]|\([^()]*\))*)\)|\s+(.+))?\s*$")
PARA_RE = re.compile(r"^([①-⑳])\s*")
PAGE_NO_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")


def is_two_column(page):
    """본문 단어 대부분이 가운데 선을 넘지 않으면 2단으로 본다."""
    words = page.extract_words()
    if len(words) < 40:
        return False
    mid = page.width / 2
    crossing = sum(1 for w in words if w["x0"] < mid - 2 and w["x1"] > mid + 2)
    left = sum(1 for w in words if w["x1"] <= mid)
    right = sum(1 for w in words if w["x0"] >= mid)
    return crossing / len(words) < 0.03 and min(left, right) > len(words) * 0.2


def page_text(page, two_col):
    if not two_col:
        return page.extract_text() or ""
    mid = page.width / 2
    words = page.extract_words(keep_blank_chars=False)
    lines = {}
    for w in words:
        lines.setdefault(round(w["top"] / 3), []).append(w)
    out, left, right = [], [], []

    def flush():
        out.extend(left)
        out.extend(right)
        left.clear()
        right.clear()

    for key in sorted(lines):
        ws = sorted(lines[key], key=lambda w: w["x0"])
        spans = any(w["x0"] < mid - 2 and w["x1"] > mid + 2 for w in ws)
        if spans:
            flush()
            out.append(" ".join(w["text"] for w in ws))
            continue
        l = [w["text"] for w in ws if w["x1"] <= mid + 2]
        r = [w["text"] for w in ws if w["x1"] > mid + 2]
        if l:
            left.append(" ".join(l))
        if r:
            right.append(" ".join(r))
    flush()
    return "\n".join(out)


def extract(pdf_path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        votes = [is_two_column(p) for p in pdf.pages]
        two_col = sum(votes) > len(votes) / 2  # 문서 전체 기준으로 판단 (마지막 쪽처럼 글이 적은 쪽도 2단으로)
        for i, page in enumerate(pdf.pages, 1):
            text = page_text(page, two_col)
            text = text.replace("\x00", "·")
            lines = [ln.rstrip() for ln in text.splitlines() if not PAGE_NO_RE.match(ln)]
            pages.append((i, lines))
    return pages


# --- 상품설명서 표 처리 (사이클 2 카드, sources의 "tables": true인 문서만) -----------------
# 카드 상품설명서는 한 쪽이 좌우 두 면으로 된 펼침면이고 면마다 표가 있다. 쪽 전체를 한 번에 읽으면
# 왼쪽 표와 오른쪽 글이 한 줄로 섞인다("월 적립영역서비스 한도기본 2배국내외…"). 그래서
# (1) 가운데 세로 여백이 있으면 좌우 면으로 나누고, (2) 면마다 표는 행 단위 "셀 | 셀"로,
# 표 밖 글은 줄 단위로 읽어 위에서부터 순서대로 잇는다. 사이클 1 문서는 바꾸지 않는다.

def _halves(page):
    words = page.extract_words()
    mid = page.width / 2
    crossing = [w for w in words if w["x0"] < mid - 4 and w["x1"] > mid + 4]
    if words and len(crossing) <= max(2, len(words) * 0.01):
        return [page.crop((0, 0, mid, page.height)), page.crop((mid, 0, page.width, page.height))]
    return [page]


def _cell(c):
    return re.sub(r"\s+", " ", c or "").strip()


def _panel_lines(panel):
    found = panel.find_tables()

    def within(a, b):  # 표 a가 표 b 안에 들어 있는가 (안쪽 표는 바깥 표를 읽을 때 같이 읽힌다)
        return a is not b and a.bbox[0] >= b.bbox[0] - 1 and a.bbox[1] >= b.bbox[1] - 1 \
            and a.bbox[2] <= b.bbox[2] + 1 and a.bbox[3] <= b.bbox[3] + 1

    tables = [t for t in found if not any(within(t, o) for o in found)]
    # 표 테두리가 아니라 칸 단위로 뺀다: 테두리 안이라도 어느 칸에도 안 걸린 글이 있어서(신한카드 설명서) 테두리로 빼면 글이 사라졌다
    boxes = [c for t in tables for c in t.cells]

    def inside(obj):
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes)

    items = []
    for t in tables:  # 세로선까지 그어진 표
        rows = []
        for row in t.extract():
            # 병합된 칸(None)을 위 행 값으로 채우면 표 아래 글 상자의 행에 숫자가 복사돼 들어가서(2026-11-04 시험) 채우지 않는다
            cells = [_cell(c) for c in row]
            if any(cells):
                rows.append(" | ".join(c for c in cells if c))
        if rows:
            items.append((t.bbox[1], 1, "[표] " + " / ".join(rows)))
    # 세로선이 없는 표(MOVING카드)는 행·칸을 안정적으로 가를 수 없어 줄 단위로 둔다.
    # 좌우 면을 나누는 것만으로 다른 면의 글이 섞이는 문제는 없어진다 (2026-11-04 시험: 가로선 기준 행 나누기는
    # 단락 구분선까지 행으로 잡아 면 전체가 한 표가 돼서 버렸다)
    words = [w for w in panel.extract_words(keep_blank_chars=False) if not inside(w)]
    lines = {}
    for w in words:
        lines.setdefault(round(w["top"] / 3), []).append(w)
    for key in sorted(lines):
        ws = sorted(lines[key], key=lambda w: w["x0"])
        items.append((ws[0]["top"], 0, " ".join(w["text"] for w in ws)))
    items.sort(key=lambda x: (round(x[0]), x[1]))
    return [t for _, _, t in items]


def extract_tables(pdf_path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            lines = []
            for panel in _halves(page):
                lines.extend(_panel_lines(panel))
            lines = [ln.replace("\x00", "·") for ln in lines if not PAGE_NO_RE.match(ln)]
            pages.append((i, lines))
    return pages


HANGUL = re.compile(r"[가-힣]")


def join_lines(lines):
    """줄바꿈으로 끊긴 한글 단어는 붙이고, 그 밖에는 공백으로 잇는다."""
    out = ""
    for s in lines:
        if out and not (HANGUL.match(out[-1]) and HANGUL.match(s[0])):
            out += " "
        out += s
    return out


def split_articles(pages):
    articles, cur, section = [], None, "본문"
    for page_no, lines in pages:
        for ln in lines:
            s = ln.strip()
            if re.match(r"^부\s*칙", s):
                section = "부칙 " + re.sub(r"^부\s*칙\s*", "", s).strip()
                cur = None
                continue
            m = ARTICLE_RE.match(s)
            if m and len(s) < 60:
                no = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
                title, rest = (m.group(3) or m.group(4) or "").strip(), []
                if not m.group(3) and title.endswith(".") and " " in title:  # 제목 뒤에 본문이 붙은 경우
                    title, tail = title.split(" ", 1)
                    rest = [tail]
                cur = {"section": section.strip(), "article": no, "title": title, "page": page_no, "lines": rest}
                articles.append(cur)
                continue
            if cur is not None and s:
                cur["lines"].append(s)
    for a in articles:
        paras, buf, label = [], [], None
        for s in a["lines"]:
            pm = PARA_RE.match(s)
            if pm:
                if buf:
                    paras.append({"paragraph": label, "text": join_lines(buf)})
                label, buf = pm.group(1), [s[pm.end():]]
            else:
                buf.append(s)
        if buf:
            paras.append({"paragraph": label, "text": join_lines(buf)})
        a["paragraphs"] = paras
        a["text"] = join_lines(a.pop("lines"))
    return articles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--out", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--sources", default=str(ROOT / "data" / "sources.json"),
                    help="문서 목록 (사이클 2 카드: data/sources-card.json)")
    args = ap.parse_args()
    raw, out = Path(args.raw), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sources = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    summary = []
    for d in sources["documents"]:
        f = raw / d["file"]
        if not f.exists():
            print(f"[없음] {d['id']}: {f}")
            continue
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        if digest != d.get("sha256"):
            print(f"[경고] {d['id']}: sha256이 문서 목록과 다름. 약관이 바뀌었을 수 있음")
        pages = extract_tables(f) if d.get("tables") else extract(f)
        full = "\n\n".join(f"[p.{n}]\n" + "\n".join(ls) for n, ls in pages)
        (out / f"{d['id']}.txt").write_text(full, encoding="utf-8")
        units = split_articles(pages) if d["layer"] in (1, 2) else []
        if units:
            kind = "article"
        elif d["layer"] in (1, 2) and not d.get("tables"):
            kind = "article"  # 사이클 1(하나은행 금리 추가약정서)은 그대로 둔다
        else:  # 조가 없는 표 형식 약정서(하나카드 리볼빙)는 쪽 단위로
            units = [{"page": n, "text": join_lines([x.strip() for x in ls if x.strip()])} for n, ls in pages]
            kind = "page"
        doc = {k: d[k] for k in ("id", "bank", "layer", "title", "effective", "url")}
        doc.update({"sha256": digest, "unit": kind, "units": units})
        (out / f"{d['id']}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append((d["id"], kind, len(units)))
        print(f"[완료] {d['id']}: {kind} {len(units)}개")
    return summary


if __name__ == "__main__":
    main()
