"""근거 인용 에이전트 1차.

흐름: 질문 → 조항 검색 → 같은 조의 다른 항·참조된 조 붙이기 → 교차 참조 확인
     → 근거 목록과 함께 LLM에 묻기 → 답이 댄 근거가 실제로 준 근거인지 확인.

LLM이 하는 일은 "준 근거 안에서 답 쓰기"뿐이다. 검색, 교차 참조 확인, 인용 검증은 코드가 한다.
그래서 LLM이 근거에 없는 조항을 지어내면 코드에서 걸러진다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from . import crossref
from .corpus import Chunk, load
from .retrieve import Index, detect_banks

SYSTEM = """너는 fineprint다. 한국 은행 신용대출 약관을 읽고, 사용자의 질문에 **주어진 근거 안에서만** 답한다.

규칙
1. 근거 목록([C1], [C2] …)에 있는 내용만 쓴다. 상식이나 다른 은행 이야기로 채우지 않는다.
2. 답의 문장마다 뒷받침하는 근거 번호를 [C3]처럼 붙인다. 근거 번호는 목록에 있는 것만 쓴다.
3. 근거로 답할 수 없으면(개인 금리, 개인 신용점수 변화 폭, 목록에 없는 문서 등) 추측하지 말고
   "판단할 수 없다"고 말한 뒤, 근거에서 확인되는 일반 원칙만 짧게 덧붙인다.
4. [교차 참조 경고]는 그 참조(예: "기본약관 제10조에 의해 상계")가 답과 관련 있을 때만 다룬다. 관련 있으면 경고 내용을 밝히고
   "확인 필요"라고 쓰며, 실제로 내용이 맞는 조를 함께 댄다. 질문과 관계없는 참조의 경고는 무시한다.
5. 어느 은행·상품이 낫다고 권하거나 고르게 하지 않는다. 비교를 원하면 각 은행 문서에 적힌 사실만 나란히 쓴다.
6. 질문한 은행의 문서를 우선한다. 예외·단서(다만, 단, 제외)가 있으면 빠뜨리지 않는다.
7. 짧게 쓴다. 결론 한 문장 → 조건·예외 → 필요하면 확인할 점. 5문장 이내.

출력은 JSON 하나만:
{"status": "answered" | "cannot_judge" | "check_needed", "answer": "답 본문(근거 번호 포함)", "citations": ["C1", "C3"]}
- citations에는 답이 실제로 기대는 근거만, 중요한 순서로 넣는다.
"""


@dataclass
class Context:
    question: str
    banks: list[str]
    chunks: list[Chunk]
    warnings: list[crossref.Warning] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"[질문] {self.question}"]
        if self.banks:
            lines.append(f"[질문 대상 은행] {', '.join(self.banks)}")
        lines.append("\n[근거 목록]")
        for i, c in enumerate(self.chunks, 1):
            lines.append(f"[C{i}] {c.label()}\n{c.text.strip()}\n")
        if self.warnings:
            lines.append("[교차 참조 경고]")
            for w in self.warnings:
                n = next(i for i, c in enumerate(self.chunks, 1) if c.id == w.chunk_id)
                lines.append(f"- [C{n}] {w.text()}")
        return "\n".join(lines)


@dataclass
class Answer:
    status: str
    answer: str
    citations: list[dict]          # 인용 표준형 (doc, version, article/paragraph 또는 page)
    labels: list[str]              # 사람이 읽는 인용 표기
    invalid: list[str]             # 근거 목록에 없는 번호를 댄 경우
    warnings: list[str]
    raw: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


class Agent:
    def __init__(self, k: int = 8, max_chunks: int = 18):
        self.chunks = load()
        self.index = Index(self.chunks)
        self.k, self.max_chunks = k, max_chunks
        self.basic: dict[str, dict[str, str]] = {}
        self.basic_chunks: dict[tuple[str, str], list[Chunk]] = {}
        for c in self.chunks:
            if c.layer == 1 and c.article:
                self.basic.setdefault(c.bank, {})[c.article] = c.article_title or ""
                self.basic_chunks.setdefault((c.bank, c.article), []).append(c)

    # 1. 검색과 근거 묶기 -------------------------------------------------
    def context(self, question: str, banks: list[str] | None = None) -> Context:
        banks = banks or detect_banks(question)
        hits = [c for c, _ in self.index.search(question, banks=banks, k=self.k)]
        chunks = self.index.with_siblings(hits)
        warnings = []
        for c in list(chunks):
            for w in crossref.check(c, self.basic.get(c.bank, {})):
                warnings.append(w)
                # 가리킨 조와 제목이 맞는 조를 근거에 같이 넣어 비교할 수 있게 한다
                for art in [w.ref] + w.suggest[:1]:
                    for b in self.basic_chunks.get((c.bank, art), []):
                        if b not in chunks:
                            chunks.append(b)
        chunks = chunks[: self.max_chunks + 4 * len(warnings)]
        return Context(question, banks, chunks, warnings)

    # 2. 답 만들기 ---------------------------------------------------------
    def prompt(self, ctx: Context) -> tuple[str, str]:
        return SYSTEM, ctx.render()

    def parse(self, ctx: Context, raw: str) -> Answer:
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            data = {}
        text = data.get("answer", raw.strip())
        ids = data.get("citations") or re.findall(r"C\d+", text)
        ids = list(dict.fromkeys(i.strip("[]") for i in ids))
        cites, labels, invalid = [], [], []
        for i in ids:
            n = int(i[1:]) if i[1:].isdigit() else 0
            if 1 <= n <= len(ctx.chunks):
                c = ctx.chunks[n - 1]
                cites.append(c.cite())
                labels.append(c.label())
            else:
                invalid.append(i)
        status = data.get("status", "answered")
        warned = {w.chunk_id for w in ctx.warnings}
        used = {ctx.chunks[int(i[1:]) - 1].id for i in ids if i not in invalid}
        if warned & used and "확인 필요" not in text:
            status = "flag_missing"   # 경고가 붙은 근거를 쓰고도 "확인 필요"를 밝히지 않음
        return Answer(status, text, cites, labels, invalid, [w.text() for w in ctx.warnings], raw)

    def generate(self, system: str, user: str, model: str | None = None) -> str:
        """Anthropic API로 답을 만든다. ANTHROPIC_API_KEY가 필요하다."""
        import anthropic  # 선택 의존성

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model or os.environ.get("FINEPRINT_MODEL", "claude-sonnet-4-5"),
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    def ask(self, question: str, banks: list[str] | None = None, model: str | None = None) -> Answer:
        ctx = self.context(question, banks)
        system, user = self.prompt(ctx)
        return self.parse(ctx, self.generate(system, user, model))
