"""교차 참조 확인: 약정서·설명서가 "은행여신거래기본약관 제N조"를 가리킬 때, 그 조가 문맥과 맞는지 본다.

예) 토스뱅크 약정서 제12조 제2항 "은행여신거래기본약관 제10조에 의해 상계"
    → 토스뱅크 기본약관 제10조는 '기한전의 임의 상환', 상계는 제11조 → 확인 필요

판단 방법은 단순하다. 참조 바로 뒤(또는 괄호 안)에 나오는 주제어를 보고,
가리킨 조의 제목에 그 주제어가 있는지 확인한다. 주제어를 못 찾으면 판단하지 않는다(경고 없음).
틀렸다고 단정하지 않고 "확인 필요"로만 표시한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .corpus import Chunk

REF = re.compile(
    r"(?:은행여신거래기본약관|은행거래여신거래기본약관|기본약관)\s*(?:\(가계용\))?\s*"
    r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?"
)
CHAIN = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")

# 문맥 주제어 → 그 조의 제목에 있어야 할 말 (앞쪽일수록 구체적. 제안할 조를 고를 때 순서대로 본다)
TOPICS = {
    "상계": ["은행으로부터의 상계", "상계"],
    "기한의 이익": ["채무변제", "기한이익"],
    "기한 전의 채무변제": ["채무변제"],
    "채무변제의무": ["채무변제"],
    "비용의 부담": ["비용"],
    "채무자가 부담": ["철회", "비용"],
    "철회": ["철회"],
    "임의 상환": ["임의 상환"],
    "충당": ["충당"],
    "지연배상금": ["지연배상금"],
    "약관 변경": ["변경"],
}


@dataclass
class Warning:
    chunk_id: str
    ref: str             # 가리킨 조 (예: 제10조)
    ref_title: str       # 가리킨 조의 실제 제목
    topic: str           # 문맥 주제어
    suggest: list[str]   # 주제어와 제목이 맞는 조
    quote: str

    def text(self) -> str:
        s = f"'기본약관 {self.ref}'를 '{self.topic}' 근거로 들지만, 이 은행 기본약관 {self.ref}의 제목은 '{self.ref_title}'이다."
        if self.suggest:
            s += f" 제목이 맞는 조: {', '.join(self.suggest)}."
        return s + " 확인 필요."


def _label(n: str, ui: str | None) -> str:
    return f"제{n}조" + (f"의{ui}" if ui else "")


def _topic(after: str) -> str | None:
    hits = [(after.find(t), t) for t in TOPICS if t in after]
    return min(hits)[1] if hits else None


def check(chunk: Chunk, basic_titles: dict[str, str]) -> list[Warning]:
    """basic_titles: 같은 은행 기본약관의 {조: 제목}"""
    if chunk.layer == 1 or not basic_titles:
        return []
    out = []
    for m in REF.finditer(chunk.text):
        # "제7조에서 정한 기한의 이익 상실 및 제10조에서 정한 상계"처럼 이어지는 조도 같이 본다
        tail = re.match(r"[^.。]*", chunk.text[m.end():]).group(0)
        tail_refs = list(CHAIN.finditer(tail))
        items = [(_label(m.group(1), m.group(2)), m.end())]
        items += [(_label(x.group(1), x.group(2)), m.end() + x.end()) for x in tail_refs]
        for idx, (ref, pos) in enumerate(items):
            nxt = items[idx + 1][1] if idx + 1 < len(items) else pos + 30
            after = chunk.text[pos: min(pos + 30, nxt)]
            topic = _topic(after)
            title = basic_titles.get(ref)
            if not topic or title is None:
                continue
            want = TOPICS[topic]
            if any(w in title for w in want):
                continue
            suggest = []
            for w in want:  # 가장 구체적인 말부터 맞는 조를 찾는다
                suggest = [a for a, t in basic_titles.items() if w in t]
                if suggest:
                    break
            out.append(Warning(chunk.id, ref, title, topic, suggest,
                               chunk.text[max(0, m.start() - 20): m.end() + 20].strip()))
    return out
