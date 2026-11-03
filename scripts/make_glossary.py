"""용어 풀이 데이터 만들기 (app/data/glossary_terms.json → app/data/glossary.json).

용어마다 풀이의 근거가 되는 문장을 은행별로 수집 문서에서 찾아 조각 id를 붙인다.
화면은 고른 은행의 근거를 먼저 보여 주고(근거 문장 위치 at 근처만 잘라서), 없으면 다른 은행 문서의 근거를 보여 준다.
풀이 문장은 사람이 근거와 대조해 쓴다(kind: 문서 정의 / 문서 설명 / 일반 설명).
근거를 하나도 못 찾은 용어는 실패로 알린다.

사용법: python scripts/make_glossary.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fineprint.corpus import load  # noqa: E402

DATA = ROOT / "app" / "data"
BANKS = ["토스뱅크", "카카오뱅크", "하나은행"]


def main():
    terms = json.loads((DATA / "glossary_terms.json").read_text(encoding="utf-8"))
    chunks = load()
    seen_text = set()
    out, missing = [], []
    for t in terms:
        pat = re.compile(t["pattern"])
        sources, at = {}, {}
        for bank in BANKS:
            for c in chunks:
                if c.bank != bank or not pat.search(c.text):
                    continue
                key = (c.doc, re.sub(r"\s+", "", c.text))  # 하나은행 설명서 중복 쪽은 하나만
                if key in seen_text and bank in sources:
                    continue
                seen_text.add(key)
                sources[bank] = c.id
                at[bank] = pat.search(c.text.strip()).start()  # 화면이 이 근처만 잘라 보여 준다(원문은 레포에 넣지 않는다)
                break
        if not sources:
            missing.append(t["term"])
        out.append({k: t[k] for k in ("term", "aliases", "kind", "plain")} | {"sources": sources, "at": at})
    (DATA / "glossary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"용어 {len(out)}개 → {DATA / 'glossary.json'}")
    for t in out:
        print(f"  {t['term']}: " + ", ".join(f"{b[:2]} {i.split(':', 1)[1]}" for b, i in t["sources"].items()))
    if missing:
        sys.exit(f"근거를 못 찾은 용어: {missing}")


if __name__ == "__main__":
    main()
