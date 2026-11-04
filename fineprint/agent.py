"""근거 인용 에이전트 (1.6).

흐름: 질문 → 층별 조항 검색 → 같은 조의 다른 항·짧은 문서 전체·참조된 기본약관 조 붙이기 → 교차 참조 확인
     → 근거 목록과 함께 LLM에 묻기 → 답이 댄 근거가 실제로 준 근거인지 확인.

1.2에서 점검 단계(초안 → 근거 목록과 대조해 빠진 예외·결과·숫자 보충, 다른 제도 섞임, 원문 표현 → 최종)를 만들었다.
1.2에서는 새 문항에서 효과가 없고 답만 길어져 껐다(eval/results-v1.2.md).
1.4에서 점검 항목(법 요건 문구, 근거에 명시된 결론을 미루지 않기, 현재 적용 여부, 길이 제한)을 고쳐
문항당 3회 평가로 다시 쟀고, 처음 보는 문항에서도 오르고 내려간 문항이 없어 기본값으로 켰다(eval/results-v1.4.md).
1.5에서 검색을 보강했다: 같은 내용 조각 빼기, 설명서 한 쪽 2조각, 항까지 참조 따라가기, 결과 조항 잇기,
상실 여부 질문 잇기, 콕 집어 넣은 조각은 상한에서 자르지 않기. 근거 재현율(항 단위) 86% → 97%,
3회 다수결 72문항 O 63 → 68(eval/results-v1.5.md).
1.6에서 점검 단계에 '짝'(비교 질문의 만나는 지점, 나란히 적힌 사유)을 더했다. O 68 → 70(eval/results-v1.6.md).

LLM이 하는 일은 "준 근거 안에서 답 쓰기"뿐이다. 검색, 교차 참조 확인, 인용 검증은 코드가 한다.
그래서 LLM이 근거에 없는 조항을 지어내면 코드에서 걸러진다.
"""
from __future__ import annotations

import json
import os
from datetime import date
import re
from dataclasses import dataclass, field

from . import crossref, guard
from .corpus import ROOT, Chunk, load
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

다음 일곱 가지를 근거 목록과 하나씩 대조한다.
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
7. 짝: 질문이 묻는 것과 근거에서 나란히 적힌 것을 빠뜨리지 않았는가.
   - 두 가지를 비교하는 질문이면, 차이만이 아니라 둘이 만나는 지점(한쪽을 하려 할 때 다른 쪽으로 처리되는 경우 등)이 근거에 있으면 쓴다.
   - 질문이 묻는 사유·조건이 근거의 같은 목록·같은 문장에서 다른 사유와 나란히 같은 결과로 이어지면, 그 나란한 사유도 함께 쓴다.

더하는 것은 질문에 답하는 데 필요한 내용만이다. 질문과 관계없는 내용을 새로 덧붙이지 않는다.
문장 수가 모자라면 질문에서 먼 내용(부활, 다른 대출 유형의 특례, 질문하지 않은 후속 절차)부터 뺀다.
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
    flags: dict = field(default_factory=dict)  # AI 분류기 결과 (guard.classify): {predict, missing_doc}
    summary_flags: list = field(default_factory=list)  # 고른 은행 요약 중 '확인 필요' 줄 [(주제, 줄)] (화면 서버만)

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
    chunk_ids: list[str] = field(default_factory=list)  # 인용한 근거 조각 id (화면에서 원문을 펼칠 때 쓴다)

    def to_dict(self) -> dict:
        return self.__dict__


SHORT_DOC = 3000   # 이보다 짧은 문서(추가약정서 등)는 한 조각만 걸려도 통째로 넣는다
REF_PER_ARTICLE = 2  # 참조를 따라 넣는 기본약관 조각 수 (한 조당, 앞쪽 항부터)
# 의무를 어기거나 하지 않았을 때의 결과를 묻는 말
CONSEQUENCE = re.compile(r"안\s*하면|않으면|안\s*내면|어기|위반|안\s*지키|거부하면|응하지|못\s*하면")
# 대출 전체를 곧 갚아야 하는지(기한의 이익 상실 여부)를 묻는 말 (1.5, L06)
ACCELERATION = re.compile(r"(?:당장|한꺼번에|전부|전액|모두)\s*(?:다\s*)?갚|다\s*갚으라|기한(?:의)?\s*이익")


class Agent:
    def __init__(self, max_chunks: int = 30, product: str = "loan"):
        # product="card"는 사이클 2(신용카드) 문서(data/processed/card)를 읽는다 (D-011)
        self.product = product
        self.chunks = load(ROOT / "data" / "processed" / "card") if product == "card" else load()
        self.index = Index(self.chunks, product=product)
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
        banks = banks or detect_banks(question, self.product)
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
        # 대출 전체를 곧 갚아야 하느냐고 물으면 상실 사유와 절차 전체(①~④)를 넣는다. "연체정보 등록"처럼
        # 질문의 사유가 ③의 각 호에 있어도 검색에서 ①·②만 걸려, 사유가 없다고 잘못 답했다(1.5, L06)
        want = (("①", "②", "③", "④") if ACCELERATION.search(question)
                else ("③", "④") if CONSEQUENCE.search(question) else ())
        if want:
            for bank in banks or sorted({c.bank for c in hits}):
                for b in self.basic_chunks.get((bank, "제7조"), []):
                    if b.paragraph in want:
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
        cites, labels, invalid, cids = [], [], [], []
        for i in ids:
            n = int(i[1:]) if i[1:].isdigit() else 0
            if 1 <= n <= len(ctx.chunks):
                c = ctx.chunks[n - 1]
                cites.append(c.cite())
                labels.append(c.label())
                cids.append(c.id)
            else:
                invalid.append(i)
        status = data.get("status", "answered")
        # 평가 채점처럼 근거 목록만으로 만든 Context에는 은행·문서 목록·경고가 없을 수 있어 여기서 채운다
        banks = ctx.banks or detect_banks(ctx.question, self.product) or sorted({c.bank for c in ctx.chunks})
        inventory = ctx.inventory or {b: self.inventory.get(b, []) for b in banks}
        warnings = ctx.warnings or [w for c in ctx.chunks for w in crossref.check(c, self.basic.get(c.bank, {}))]
        used = {ctx.chunks[int(i[1:]) - 1].id for i in ids if i not in invalid}
        used_warn = [w.text() for w in warnings if w.chunk_id in used]
        # 안전장치(D-010): 모델이 놓친 '판단할 수 없음'·'확인 필요'를 코드가 붙인다
        status, text, _ = guard.apply(ctx.question, banks, inventory, status, text, used_warn, ctx.flags, len(cids),
                                     ctx.summary_flags)
        return Answer(status, text, cites, labels, invalid, [w.text() for w in warnings], raw, cids)

    def generate(self, system: str, user: str, model: str | None = None, reminder: bool = True) -> str:
        """LLM으로 답을 만든다. 어느 쪽을 쓸지는 provider()가 정한다."""
        if provider() == "gemini":
            return gemini_generate(system, user, model or os.environ.get("FINEPRINT_MODEL", GEMINI_DEFAULT),
                                   reminder=reminder)
        import anthropic  # 선택 의존성

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model or os.environ.get("FINEPRINT_MODEL", "claude-sonnet-4-5"),
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    def classify(self, question: str, banks: list[str] | None = None, model: str | None = None) -> dict:
        """안전장치용 AI 분류기: 결과 예측 질문인지, 없는 문서를 지목했는지. 실패하면 빈 dict(정규식만 쓴다)."""
        inv = {b: self.inventory[b] for b in (banks or sorted(self.inventory))}
        system, user = guard.classify_prompt(question, inv)
        try:
            return guard.parse_classify(self.generate(system, user, model, reminder=False))
        except Exception:  # noqa: BLE001
            return {}

    def ask(self, question: str, banks: list[str] | None = None, model: str | None = None,
            review: bool = True) -> Answer:
        ctx = self.context(question, banks)
        ctx.flags = self.classify(question, ctx.banks, model)
        system, user = self.prompt(ctx)
        draft = self.generate(system, user, model)
        if not review:
            return self.parse(ctx, draft)
        system, user = self.review_prompt(ctx, draft)
        return self.parse(ctx, self.generate(system, user, model))


# --- LLM 공급자 -------------------------------------------------------------
# 평가(1.0~1.6)는 Claude로 했다. 공개 데모의 실시간 답변은 무료인 Gemini API로 돌린다(D-010).
GEMINI_DEFAULT = "gemini-3.5-flash-lite"  # 2026-11-02 점검: 1.2초, 생각 0. flash-latest는 98초
GEMINI_URL = os.environ.get("FINEPRINT_GEMINI_URL",  # 시험용으로 바꿀 수 있다
                            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent")


def provider() -> str | None:
    """FINEPRINT_LLM(gemini|anthropic)을 따르고, 없으면 있는 키로 고른다. 키가 없으면 None."""
    want = os.environ.get("FINEPRINT_LLM", "").lower()
    if want in ("gemini", "anthropic"):
        return want
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


# 가벼운 모델은 긴 프롬프트의 앞쪽 지시를 놓치기 쉬워, 끝에 한 번 더 짧게 적는다 (Gemini 비교에서 놓친 것들)
GEMINI_REMINDER = """

[답을 쓰기 전에 마지막으로 확인]
1. 질문이 은행이 받아들일지·승인할지, 내 금리·한도·점수가 얼마일지, 내 상황이 해당하는지를 묻는다면 status는 cannot_judge이고, 답 첫 문장에서 문서만으로는 판단할 수 없다고 말한다. 그다음 문서가 정한 조건·절차를 적는다.
2. 질문이 지목한 문서가 [수집한 문서]에 없거나, 근거 경고가 있으면 '확인 필요'를 쓴다.
3. 법·약관의 요건 문구(예: '채권보전에 현저한 위험', '도달일부터 10일 이상', '객관적으로 적정한 조치 없이')는 줄이지 말고 그대로 옮긴다.
4. 짧게 쓰려고 질문이 직접 묻는 요소(기간, 금액, 대상, 예외)를 빼지 않는다. 질문에 물음이 여러 개면 하나씩 모두 답한다.
5. 답의 첫 문장은 질문에 대한 결론 한 줄이다(예: "네, …", "아니요, …", "문서만으로는 판단할 수 없어요. …"). 근거와 조건은 그다음에 쓴다. 질문이 다른 은행 대출·기존 대출·갈아타기를 말하면 첫 문장에 어느 은행 문서 기준인지 밝힌다.
5-1. 질문에 내 경우의 숫자(열흘, 2번, 1천만원 등)가 있으면 그 숫자를 문서 기준에 대어 결론을 쓴다(예: "열흘이면 휴일에 따라 5영업일을 넘을 수 있어, 단기연체정보 제공 대상일 수 있어요"). 날짜를 영업일로 바꿀 때는 휴일에 따라 달라지므로 "넘는다"고 단정하지 말고 "넘을 수 있다"고 쓴다. 기준이 바뀌는 경계도 함께 쓴다(예: "1개월이 지나면 원금 전체에 연체이자").
6. 질문이 신용대출·마이너스통장이면 주택담보대출 조건(2개월, 3회 등)을 결론으로 쓰지 않는다. 함께 적을 때는 "주택담보대출은 다르다"고 구분한다.
7. 모든 사실 문장에 근거 번호(C번호)를 단다. 근거가 없는 사실은 쓰지 않는다.
8. 답의 마지막 문장은 줄을 바꿔 "지금 할 수 있는 일:"로 시작하고, 근거에 적힌 절차·방법(예: 만기 전 앱에서 연장 신청, 고객센터 문의, 금리인하요구 신청) 중 질문에 맞는 하나를 근거 번호와 함께 쓴다. 근거에 그런 절차가 없으면 이 문장을 쓰지 않는다.
9. 형식은 지시대로 JSON 하나만 낸다."""


def gemini_generate(system: str, user: str, model: str, retries: int = 3, reminder: bool = True) -> str:
    """Gemini REST API를 표준 라이브러리로 부른다. 429·5xx는 잠깐 기다렸다 다시 한다."""
    import time
    import urllib.error
    import urllib.request

    cfg = {"temperature": 0.2, "maxOutputTokens": 8192}
    level = os.environ.get("FINEPRINT_THINKING", "low")  # 생각을 짧게 (긴 프롬프트에서 시간 초과를 막는다). none이면 보내지 않는다
    if level != "none":
        cfg["thinkingConfig"] = {"thinkingLevel": level}

    def request(cfg: dict):
        body = json.dumps({
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user + (GEMINI_REMINDER if reminder else "")}]}],
            "generationConfig": cfg,
        }).encode("utf-8")
        return urllib.request.Request(GEMINI_URL.format(model=model), data=body, method="POST", headers={
            "Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})

    req = request(cfg)
    timeout = float(os.environ.get("FINEPRINT_TIMEOUT", 180))
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 400 and "thinking" in detail.lower() and "thinkingConfig" in cfg:
                cfg.pop("thinkingConfig")  # 이 모델은 생각 설정을 받지 않는다
                req = request(cfg)
                continue
            if attempt < retries and (e.code == 429 or e.code >= 500):
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(f"Gemini {e.code}: {detail}") from None
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:  # 응답이 늦거나 연결이 끊김
            if attempt < retries:
                print(f"  Gemini 응답 지연({type(e).__name__}), 다시 시도해요...", flush=True)
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(f"Gemini 응답이 {timeout:.0f}초 안에 오지 않았어요") from None
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        raise RuntimeError(f"Gemini가 빈 답을 줬어요 (finishReason={cand.get('finishReason')})")
    return text
