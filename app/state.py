"""화면에 줄 상태를 만든다. 서버(server.py)와 정적 데모(export_static.py)가 같이 쓴다.

- 은행·수집 문서 목록, 불리할 수 있는 조건 요약, 예시 질문과 답, 용어 풀이(근거 조각 포함)
- 근거 조각의 원문은 로컬 data/processed에서 읽는다(레포에는 없다). 없으면 원문 없이 표기만 보여 준다.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fineprint.agent import Agent  # noqa: E402
from fineprint.corpus import LAYER_NAME  # noqa: E402
from fineprint.present import ref  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
BANKS = ["토스뱅크", "카카오뱅크", "하나은행"]
# 사이클 2 신용카드 (D-011). 화면에는 요약 6줄이 있는 두 상품만 보인다. 신한카드는 상품설명서가 공개되지 않아 뺐다.
CARD_BANKS = ["하나카드", "BC카드"]
CARD_LAYER = {1: "표준약관", 2: "부속약관·약정서", 3: "상품설명서"}


def load_agent() -> Agent | None:
    try:
        return Agent()
    except Exception:  # data/processed가 없으면 검색도 원문도 없다
        return None


def load_card_agent() -> Agent | None:
    try:
        return Agent(product="card")
    except Exception:  # data/processed/card가 없으면 카드는 화면에 안 나온다
        return None


def chunk_payload(agent: Agent | None, ids: list[str], card_agent: Agent | None = None) -> dict:
    by = {c.id: c for a in (agent, card_agent) if a for c in a.chunks}
    out = {}
    for i in ids:
        c = by.get(i)
        out[i] = {"text": c.text.strip(), **ref(c)} if c else {"text": None, "chunk_id": i, "label": i}
    return out


def build(agent: Agent | None, live: bool, card_agent: Agent | None = None) -> dict:
    summaries = json.loads((DATA / "summaries.json").read_text(encoding="utf-8"))
    if card_agent:
        summaries += json.loads((DATA / "summaries-card.json").read_text(encoding="utf-8"))
    samples = json.loads((DATA / "samples.json").read_text(encoding="utf-8"))
    glossary = json.loads((DATA / "glossary.json").read_text(encoding="utf-8"))
    banks = []
    for b in BANKS:
        docs = []
        if agent:
            for d, cs in agent.doc_chunks.items():
                if cs[0].bank == b:
                    docs.append({"title": cs[0].title, "version": cs[0].version, "layer": LAYER_NAME[cs[0].layer]})
            docs.sort(key=lambda x: ["기본약관", "약정서", "상품설명서"].index(x["layer"]))
        banks.append({"name": b, "docs": docs, "product": "loan"})
    if card_agent:
        for b in CARD_BANKS:
            cs0 = [cs[0] for cs in card_agent.doc_chunks.values() if cs[0].bank == b]
            docs = [{"title": c.title, "version": c.version, "layer": CARD_LAYER[c.layer]}
                    for c in sorted(cs0, key=lambda c: c.layer)]
            banks.append({"name": b, "docs": docs, "product": "card"})
    ids = [i for s in summaries for it in s["items"] for i in it["chunk_ids"]]
    ids += [r["chunk_id"] for s in samples for r in s["refs"]]
    ids += [i for t in glossary for i in t["sources"].values()]
    return {"mode": "live" if live else "demo", "today": date.today().isoformat(), "banks": banks,
            "summaries": {s["bank"]: s["items"] for s in summaries},
            "products": {s["bank"]: s["product"] for s in summaries if s.get("product")}, "samples": samples,
            "glossary": glossary,
            "chunks": chunk_payload(agent, list(dict.fromkeys(ids)), card_agent)}
