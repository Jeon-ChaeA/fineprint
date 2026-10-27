"""불리할 수 있는 조건 요약 (소비자용 화면 1, D-008).

은행 하나의 수집 문서에서 사람들이 당황했던 조건(설문)을 주제별로 검색해 근거 목록을 만들고,
LLM이 그 근거 안에서만 5~7줄로 요약한다. 줄마다 근거 번호를 붙이고, 코드가 그 번호를 실제 조각으로 되돌린다.
답변(agent.py)과 같은 원칙이다: 검색과 인용 검증은 코드, 요약 문장만 LLM.
"""
from __future__ import annotations

import json
import re

from .agent import Agent, Context

# 설문에서 당황했다고 답한 조건(D-008) → 검색 질의
TOPICS = [
    ("금리가 오르는 조건", "변동금리 기준금리 금리변동주기 금리가 오르는 경우 우대금리 적용 제외 가산금리 재산정"),
    ("중도상환해약금", "중도상환해약금 기한전의 임의 상환 면제"),
    ("연체이자", "연체이자 지연배상금 연체가산금리 최고 연체이율"),
    ("한꺼번에 갚아야 하는 경우", "기한의 이익 상실 사유 곧 갚아야 서면 통지 독촉"),
    ("신용점수 영향", "신용평점 하락 연체정보 등록 신용정보 불이익"),
    ("만기 연장 조건", "기한연장 만기연장 심사 연장 거절 감액"),
]
PER_TOPIC = 6       # 주제마다 근거 조각 수
MAX_CHUNKS = 32

SUMMARY_SYSTEM = """너는 fineprint다. 한 은행의 신용대출 약관·약정서·상품설명서에서, 대출받는 사람에게 불리할 수 있는 조건을 요약한다.

규칙
1. 근거 목록([C1], [C2] …)에 있는 내용만 쓴다. 상식이나 다른 은행 이야기로 채우지 않는다.
2. 주제마다 한 줄, 모두 5~7줄. 주제: 금리가 오르는 조건, 중도상환해약금, 연체이자, 한꺼번에 갚아야 하는 경우, 신용점수 영향, 만기 연장 조건.
   근거에 내용이 없는 주제는 빼고, 그 주제 이름을 missing에 넣는다.
3. 한 줄은 60자 안팎의 쉬운 말. 숫자(기간, 비율, 횟수)는 원문 그대로. 예외·단서가 결과를 바꾸면 짧게 붙인다.
4. 줄마다 그 내용을 직접 뒷받침하는 근거 번호를 1~2개 붙인다(citations). 가장 직접적인 것을 먼저.
5. 불리한 점을 과장하거나 줄이지 않는다. 어느 은행이 낫다고 평가하지 않는다.
6. 문서끼리 다르게 적혀 있으면 그 줄에 "문서마다 다르게 적혀 있어 확인 필요"를 붙인다.

출력은 JSON 하나만:
{"items": [{"topic": "금리가 오르는 조건", "line": "요약 한 줄", "citations": ["C3", "C7"]}, ...], "missing": ["주제 이름", ...]}
"""


def context(agent: Agent, bank: str) -> Context:
    """주제별 검색 결과를 합쳐 근거 목록을 만든다. 주제 순서대로 넣어 각 주제가 자리를 갖게 한다."""
    chunks, seen = [], set()
    for _, query in TOPICS:
        got = 0
        for c, _ in agent.index.search_layered(query, banks=[bank]):
            t = (c.doc, re.sub(r"\s+", "", c.text))  # 하나은행 설명서 1~3쪽 = 4~6쪽
            if t not in seen:
                seen.add(t)
                chunks.append(c)
                got += 1
            if got >= PER_TOPIC:
                break
    question = f"{bank} 신용대출에서 불리할 수 있는 조건을 요약해 주세요."
    return Context(question, [bank], chunks[:MAX_CHUNKS], [], {bank: agent.inventory[bank]})


def prompt(ctx: Context) -> tuple[str, str]:
    return SUMMARY_SYSTEM, ctx.render()


_NUM = re.compile(r"\d+(?:\.\d+)?\s*(?:%|영업일|개월|년|일|회|만원|천만원|억원)")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _bigrams(s: str) -> set:
    s = _norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _match(text: str, part: str) -> float:
    """요약 구절의 2글자 조각이 근거 원문에 얼마나 들어 있는가 (0~1)"""
    b = _bigrams(part)
    return len(b & _bigrams(text)) / max(1, len(b))


def repair(ctx: Context, line: str, ids: list[str]) -> tuple[list[str], list[str]]:
    """근거 번호 고치기. 같은 쪽의 다른 창을 대는 실수가 있어(토스뱅크 신용점수 줄이 9쪽의 연장 안내 창을 댐),
    구절마다 가장 잘 맞는 근거 조각을 더하고, 줄과 거의 겹치지 않는 근거는 뺀다.
    줄의 숫자(기간·비율·횟수)가 고친 근거 원문에 없으면 unverified로 남긴다."""
    by = {c.id: c for c in ctx.chunks}
    parts = [p for p in re.split(r"[,.]\s*|\s*·\s*", line) if len(_norm(p)) >= 6]
    out, needed = list(ids), set()
    for p in parts:
        best = max(ctx.chunks, key=lambda c: _match(c.text, p))
        if _match(best.text, p) >= 0.5:
            needed.add(best.id)
            if best.id not in out:
                out.append(best.id)
    # LLM이 댄 근거는 두는 것이 원칙이다(겹침 정도만으로는 맞고 틀림이 갈리지 않았다).
    # 같은 쪽·같은 조의 더 잘 맞는 창을 새로 더했고, 원래 근거가 줄과 거의 겹치지 않을 때만 뺀다(같은 쪽 다른 창을 댄 실수)
    unit = lambda i: (by[i].doc, by[i].article or by[i].page)
    added = [i for i in out if i not in ids]
    nums = [_norm(x) for x in _NUM.findall(line)]
    def wrong_window(i):
        return (i in ids and i not in needed and _match(by[i].text, line) < 0.25
                and not any(n in _norm(by[i].text) for n in nums)
                and any(unit(a) == unit(i) for a in added))
    out = [i for i in out if not wrong_window(i)] or out[:1]
    txt = _norm(" ".join(by[i].text for i in out))
    unverified = [n for n in (_norm(x) for x in _NUM.findall(line)) if n not in txt]
    return out[:4], unverified


def parse(ctx: Context, raw: str) -> dict:
    """LLM 출력 → 줄마다 근거 조각 id. 목록에 없는 번호는 버리고 invalid에 남긴다. 근거가 하나도 안 남은 줄은 뺀다."""
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0)) if m else {}
    items, invalid = [], []
    for it in data.get("items", []):
        ids = []
        for cid in it.get("citations") or re.findall(r"C\d+", it.get("line", "")):
            n = int(cid.strip("[]C")) if cid.strip("[]C").isdigit() else 0
            if 1 <= n <= len(ctx.chunks):
                ids.append(ctx.chunks[n - 1].id)
            else:
                invalid.append(cid)
        line = re.sub(r"\s*\[C\d+\]", "", it.get("line", "")).strip()
        if ids and line:
            fixed, unverified = repair(ctx, line, list(dict.fromkeys(ids)))
            items.append({"topic": it.get("topic", ""), "line": line, "chunk_ids": fixed, "unverified": unverified})
    return {"bank": ctx.banks[0], "items": items, "missing": data.get("missing", []), "invalid": invalid}


def summarize(agent: Agent, bank: str, model: str | None = None) -> dict:
    """Anthropic API로 요약을 만든다. ANTHROPIC_API_KEY가 필요하다."""
    ctx = context(agent, bank)
    system, user = prompt(ctx)
    return parse(ctx, agent.generate(system, user, model))
