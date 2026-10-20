"""근거 인용 에이전트 (1.5).

흐름: 질문 → 층별 조항 검색 → 같은 조의 다른 항·짧은 문서 전체·참조된 기본약관 조 붙이기 → 교차 참조 확인
     → 근거 목록과 함께 LLM에 묻기 → 답이 댄 근거가 실제로 준 근거인지 확인.

1.2에서 점검 단계(초안 → 근거 목록과 대조해 빠진 예외·결과·숫자 보충, 다른 제도 섞임, 원문 표현 → 최종)를 만들었다.
1.2에서는 새 문항에서 효과가 없고 답만 길어져 껐다(eval/results-v1.2.md).
1.4에서 점검 항목(법 요건 문구, 근거에 명시된 결론을 미루지 않기, 현재 적용 여부, 길이 제한)을 고쳐
문항당 3회 평가로 다시 쟀고, 처음 보는 문항에서도 오르고 내려간 문항이 없어 기본값으로 켰다(eval/results-v1.4.md).
1.5에서 검색을 보강했다: 같은 내용 조각 빼기, 설명서 한 쪽 2조각, 항까지 참조 따라가기, 결과 조항 잇기,
콕 집어 넣은 조각은 상한에서 자르지 않기. 근거 재현율(항 단위) 86% → 97%(eval/results-v1.5.md).

LLM이 하는 일은 "준 근거 안에서 답 쓰기"뿐이다. 검색, 교차 참조 확인, 인용 검증은 코드가 한다.
그래서 LLM이 근거에 없는 조항을 지어내면 코드에서 걸러진다.
"""
from __future__ import annotations

import json
import os
from datetime import date
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
7. 결과까지 쓴다. 조건을 어기거나, 갚지 못하거나, 거절되면 그다음 어떻게 되는지가 근거에 있으면 한 문장으로 덧붙인다.
8. 질문이 특정 문서(예: 약정서)를 묻는데 [수집한 문서]에 없으면 "수집한 자료에 없어 확인 필요"라고 쓰고,
   수집한 다른 문서로 확인되는 내용만 덧붙인다. 다른 문서 내용을 그 문서의 조항처럼 쓰지 않는다.
9. 짧게 쓴다. 결론 한 문장 → 조건·예외 → 결과 → 필요하면 확인할 점. 6문장 이내.

출력은 JSON 하나만:
{"status": "answered" | "cannot_judge" | "check_needed", "answer": "답 본문(근거 번호 포함)", "citations": ["C1", "C3"]}
- citations에는 답이 실제로 기대는 근거만, 중요한 순서로 넣는다.
"""


REVIEW = """너는 fineprint의 점검 담당이다. 근거 목록, 질문, 초안 답을 받고 초안을 고친 최종 답을 낸다.
근거 목록 밖의 지식은 쓰지 않는다. 초안 규칙(근거 번호, 판단 불가, 확인 필요, 권유 금지)은 그대로 지킨다.

다음 여섯 가지를 근거 목록과 하나씩 대조한다.
1. 빠진 것: 질문에 답하는 데 필요한데 초안에 없는 것을 근거 목록에서 찾는다.
   - 예외·단서 (다만, 단, 제외, ~미만이면)
   - 결과 (어기거나 갚지 못하거나 거절되면 그다음 어떻게 되는가)
   - 절차·기한·요건 (서면 통지, 며칠 이상, 언제부터, "채권보전에 현저한 위험" 같은 법 요건 문구)
   - 숫자 (금액, 비율, 기간). 근거에 계산 재료(세액표, 요율)가 있으면 질문 상황에 맞춰 계산해 쓴다
2. 섞인 것: 이름이 비슷한 다른 제도·다른 문서의 내용을 질문한 제도처럼 쓰지 않았는가.
   다른 제도라면 빼거나 "별개 제도"라고 구분한다.
3. 틀린 것: 기간·기준일·금액·요건 문구가 근거 원문과 다른 곳을 원문 표현으로 고친다.
4. 판단 불가 문항: "판단할 수 없다"는 결론은 유지하되, 근거에 있는 판단 기준·절차·결과는 덧붙인다.
   근거에 실제로 있는 조항을 "없다"고 쓰지 않았는지 확인한다.
5. 미룬 것: 근거에 분명히 적힌 사실(예: "중도상환해약금이 없다", 세액표의 금액, 처리 기준 시각)을
   "확인 필요"나 "단정할 수 없다"로 미루지 않았는가. 그렇다면 근거를 대고 단정해서 쓴다.
   "확인 필요"는 근거에 없거나, 문서끼리 실제로 다르게 적혀 있을 때만 쓴다.
6. 현재 적용 여부: 근거 문서의 시행일이 [오늘 날짜]보다 2년 이상 전이거나, 질문이 규제·의무를 묻거나
   은행끼리 비교하는 질문이면, 끝에 "수집한 문서(시행일 ○○) 기준이며, 현재도 적용되는지는 확인 필요"를 한 문장 붙인다.

더하는 것은 질문에 답하는 데 필요한 내용만이다. 질문과 관계없는 내용을 새로 덧붙이지 않는다.
고칠 것이 없으면 초안을 그대로 낸다. 최종 답은 7문장 이내, 초안보다 2문장 넘게 늘리지 않는다.

출력은 JSON 하나만:
{"status": "...", "answer": "최종 답(근거 번호 포함)", "citations": ["C1", ...], "changes": ["고친 점을 짧게", ...]}
"""


@dataclass
class Context:
    question: str
    banks: list[str]
    chunks: list[Chunk]
    warnings: list[crossref.Warning] = field(default_factory=list)
    inventory: dict[str, list[str]] = field(default_factory=dict)  # 은행 → 수집한 문서 이름

    def render(self) -> str:
        lines = [f"[질문] {self.question}"]
        if self.banks:
            lines.append(f"[질문 대상 은행] {', '.join(self.banks)}")
        if self.inventory:
            lines.append("[수집한 문서]")
            for bank, docs in self.inventory.items():
                lines.append(f"- {bank}: {'; '.join(docs)}")
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


SHORT_DOC = 3000   # 이보다 짧은 문서(추가약정서 등)는 한 조각만 걸려도 통째로 넣는다
REF_PER_ARTICLE = 2  # 참조를 따라 넣는 기본약관 조각 수 (한 조당, 앞쪽 항부터)
# 의무를 어기거나 하지 않았을 때의 결과를 묻는 말
CONSEQUENCE = re.compile(r"안\s*하면|않으면|안\s*내면|어기|위반|안\s*지키|거부하면|응하지|못\s*하면")


class Agent:
    def __init__(self, max_chunks: int = 30):
        self.chunks = load()
        self.index = Index(self.chunks)
        self.max_chunks = max_chunks
        self.doc_chunks: dict[str, list[Chunk]] = {}
        for c in self.chunks:
            self.doc_chunks.setdefault(c.doc, []).append(c)
        self.doc_len = {d: sum(len(c.text) for c in cs) for d, cs in self.doc_chunks.items()}
        self.inventory: dict[str, list[str]] = {}
        for d, cs in self.doc_chunks.items():
            self.inventory.setdefault(cs[0].bank, []).append(f"{cs[0].title}({cs[0].version})")
        self.basic: dict[str, dict[str, str]] = {}
        self.basic_chunks: dict[tuple[str, str], list[Chunk]] = {}
        for c in self.chunks:
            if c.layer == 1 and c.article:
                self.basic.setdefault(c.bank, {})[c.article] = c.article_title or ""
                self.basic_chunks.setdefault((c.bank, c.article), []).append(c)

    # 1. 검색과 근거 묶기 -------------------------------------------------
    def context(self, question: str, banks: list[str] | None = None) -> Context:
        banks = banks or detect_banks(question)
        hits = [c for c, _ in self.index.search_layered(question, banks=banks)]
        # 우선순위대로 담고 마지막에 자른다: 검색 결과(+짧은 문서 전체, 참조된 기본약관 조) → 같은 조의 다른 항
        chunks: list[Chunk] = []
        keep: set[str] = set()  # 콕 집어 넣은 조각(항까지 가리킨 참조, 결과 조항)은 상한에서 자르지 않는다(1.5)

        def add(c: Chunk, must: bool = False):
            if c not in chunks:
                chunks.append(c)
            if must:
                keep.add(c.id)

        def follow(c: Chunk):
            # 참조 따라가기: 약정서·설명서가 "기본약관 제N조"를 가리키면 그 조를 바로 뒤에 넣는다(1차 평가 Q23)
            if c.layer == 1:
                return
            for m in crossref.REF.finditer(c.text):
                art = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
                paras = self.basic_chunks.get((c.bank, art), [])
                # 항까지 가리키면 그 항부터 넣는다: "제7조 제4항 제2호" → 제7조 ④ (1.5, Q25)
                pm = re.match(r"\s*제\s*(\d+)\s*항", c.text[m.end(): m.end() + 12])
                if pm and 1 <= int(pm.group(1)) <= 20:
                    mark = chr(0x2460 + int(pm.group(1)) - 1)
                    for b in paras:
                        if b.paragraph == mark:
                            add(b, must=True)
                for b in paras[:REF_PER_ARTICLE]:
                    add(b)

        for c in hits:
            add(c)
            follow(c)
            # 짧은 문서는 통째로, 걸린 조각 바로 뒤에: 목적 조항만 걸리고 의무 조항을 놓치는 일을 막는다(1차 평가 Q25)
            # 통째로 넣은 조각의 참조도 따라간다(1.4까지는 검색에 걸린 조각만 따라가 추가약정서 제3조의 "제7조 제4항"을 놓쳤다)
            if self.doc_len[c.doc] <= SHORT_DOC:
                for x in self.doc_chunks[c.doc]:
                    if x not in chunks:
                        add(x)
                        follow(x)
        # 결과 조항 잇기: "안 하면 어떻게 되나"처럼 의무를 어긴 결과를 물으면, 위반 시 결과를 정한
        # 기본약관 제7조(기한의 이익 상실) ③·④를 넣는다. 의무 조항(회보, 용도 등)은 제7조를 직접 가리키지 않는다(1.5, H07)
        if CONSEQUENCE.search(question):
            for bank in banks or sorted({c.bank for c in hits}):
                for b in self.basic_chunks.get((bank, "제7조"), []):
                    if b.paragraph in ("③", "④"):
                        add(b, must=True)
        # 같은 조의 다른 항: 예외는 대개 같은 조의 다른 항이나 단서에 있다
        for c in self.index.with_siblings(hits):
            add(c)
        room = self.max_chunks - len(keep)
        out = []
        for c in chunks:
            if c.id in keep or room > 0:
                out.append(c)
                room -= c.id not in keep
        chunks = out
        warnings = []
        for c in list(chunks):
            for w in crossref.check(c, self.basic.get(c.bank, {})):
                warnings.append(w)
                # 가리킨 조와 제목이 맞는 조를 근거에 같이 넣어 비교할 수 있게 한다
                for art in [w.ref] + w.suggest[:1]:
                    for b in self.basic_chunks.get((c.bank, art), []):
                        if b not in chunks:
                            chunks.append(b)
        inv = {b: self.inventory[b] for b in (banks or sorted({c.bank for c in chunks}))}
        return Context(question, banks, chunks, warnings, inv)

    # 2. 답 만들기 ---------------------------------------------------------
    def prompt(self, ctx: Context) -> tuple[str, str]:
        return SYSTEM, ctx.render()

    def review_prompt(self, ctx: Context, draft: str) -> tuple[str, str]:
        """점검 단계 프롬프트: 같은 근거 목록 + 초안"""
        today = date.today().isoformat()
        return REVIEW, f"[오늘 날짜] {today}\n" + ctx.render() + "\n\n[초안 답]\n" + draft.strip()

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
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    def ask(self, question: str, banks: list[str] | None = None, model: str | None = None,
            review: bool = True) -> Answer:
        ctx = self.context(question, banks)
        system, user = self.prompt(ctx)
        draft = self.generate(system, user, model)
        if not review:
            return self.parse(ctx, draft)
        system, user = self.review_prompt(ctx, draft)
        return self.parse(ctx, self.generate(system, user, model))
