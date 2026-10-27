"""화면용으로 답과 요약을 바꾼다.

- 답 본문의 [C7]처럼 근거 목록 번호를 화면 안에서 [1], [2]… 로 다시 매긴다.
- 근거마다 사람이 읽는 표기(은행 · 문서 · 시행일 · 조항)와 조각 id를 붙인다. 원문은 화면이 조각 id로 따로 가져온다.
  (원문은 data/processed에만 있고 레포에 올리지 않는다)
"""
from __future__ import annotations

import re

from .agent import Answer, Context
from .corpus import LAYER_NAME

STATUS = {"answered": "답변", "cannot_judge": "판단할 수 없음", "check_needed": "확인 필요", "flag_missing": "확인 필요"}


def ref(chunk) -> dict:
    return {"chunk_id": chunk.id, "label": chunk.label(), "bank": chunk.bank, "doc": chunk.title,
            "version": chunk.version, "layer": LAYER_NAME[chunk.layer]}


def answer(ctx: Context, ans: Answer) -> dict:
    order: list[int] = []

    def renumber(m):
        n = int(m.group(1))
        if not 1 <= n <= len(ctx.chunks):
            return ""          # 근거 목록에 없는 번호는 지운다 (지어낸 인용)
        if n not in order:
            order.append(n)
        return f"[{order.index(n) + 1}]"

    text = re.sub(r"\[C(\d+)\]", renumber, ans.answer)
    text = re.sub(r"\]\s*\[", "][", text).strip()
    return {"status": ans.status, "status_label": STATUS.get(ans.status, ans.status), "text": text,
            "refs": [ref(ctx.chunks[n - 1]) for n in order], "warnings": ans.warnings if ans.status == "check_needed" else []}
