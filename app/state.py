"""화면에 줄 상태를 만든다. 서버(server.py)와 정적 데모(export_static.py)가 같이 쓴다.

- 은행·수집 문서 목록, 불리할 수 있는 조건 요약, 예시 질문과 답
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


def load_agent() -> Agent | None:
    try:
        return Agent()
    except Exception:  # data/processed가 없으면 검색도 원문도 없다
        return None


def chunk_payload(agent: Agent | None, ids: list[str]) -> dict:
    by = {c.id: c for c in agent.chunks} if agent else {}
    out = {}
    for i in ids:
        c = by.get(i)
        out[i] = {"text": c.text.strip(), **ref(c)} if c else {"text": None, "chunk_id": i, "label": i}
    return out


def build(agent: Agent | None, live: bool) -> dict:
    summaries = json.loads((DATA / "summaries.json").read_text(encoding="utf-8"))
    samples = json.loads((DATA / "samples.json").read_text(encoding="utf-8"))
    banks = []
    for b in BANKS:
        docs = []
        if agent:
            for d, cs in agent.doc_chunks.items():
                if cs[0].bank == b:
                    docs.append({"title": cs[0].title, "version": cs[0].version, "layer": LAYER_NAME[cs[0].layer]})
            docs.sort(key=lambda x: ["기본약관", "약정서", "상품설명서"].index(x["layer"]))
        banks.append({"name": b, "docs": docs})
    ids = [i for s in summaries for it in s["items"] for i in it["chunk_ids"]]
    ids += [r["chunk_id"] for s in samples for r in s["refs"]]
    return {"mode": "live" if live else "demo", "today": date.today().isoformat(), "banks": banks,
            "summaries": {s["bank"]: s["items"] for s in summaries}, "samples": samples,
            "chunks": chunk_payload(agent, list(dict.fromkeys(ids)))}
