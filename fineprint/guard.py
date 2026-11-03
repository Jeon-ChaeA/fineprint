"""답의 안전장치 (D-010): 모델이 놓쳐도 코드가 '판단할 수 없음'·'확인 필요'를 붙인다.

Gemini 비교(eval/results-gemini.md)에서 가벼운 모델은 판단할 수 없는 질문에도 조항만 옮기고 답을 마치고,
수집하지 않은 문서를 물어도 '확인 필요'를 쓰지 않았다. 모델과 상관없이 아래 세 경우는 코드가 표시한다.

1. 결과 예측 질문: 은행이 받아들일지·승인할지, 개인의 금리·한도·점수가 얼마일지, 내 상황이 해당하는지
2. 없는 문서: 질문이 이름으로 지목한 문서(예: 하나은행 약정서, 'OO 상품설명서')가 수집 문서에 없을 때
3. 표기 불일치: 인용한 근거에 조항 번호와 제목이 맞지 않는다는 경고(crossref)가 있을 때

모델이 이미 그렇게 답했으면 아무것도 바꾸지 않는다. 문서 내용은 그대로 두고 앞이나 뒤에 문장을 붙인다.
"""
from __future__ import annotations

import json
import re

CANNOT = re.compile(r"판단할 수 없|판단하기 어렵|알 수 없|답할 수 없|단정할 수 없")
CHECK = re.compile(r"확인\s*(?:이\s*)?필요")

# 1. 결과 예측 질문
PREDICT = [
    re.compile(r"(받아들여|받아\s*주|받아\s*줄|수용|승인|통과|들어\s*주|허락)[가-힣\s]{0,6}(질까|될까|줄까|할까|일까|까요)"),
    re.compile(r"(은행|뱅크)[이가은는]?\s.{0,40}(라고|으라고|하라고)\s*할까요"),
    re.compile(r"(얼마로|몇\s*%로|몇\s*퍼센트로|몇\s*점)\s*[가-힣]{0,6}\s*(줄어|나오|떨어|오르|바뀌|내려)"),
    re.compile(r"(저한테|저에게|제가|저는|제\s).{0,40}(상황인가요|해당(하나요|할까요|될까요|되나요))"),
]
PREDICT_LEAD = ("결론부터 말하면, 이 질문의 결과(은행의 승인·수용 여부나 개인별 금리·한도·점수, 내 상황이 해당하는지)는 "
                "은행 심사와 개인 조건에 달려 있어 수집한 문서만으로는 판단할 수 없어요. 아래는 문서가 정한 조건과 절차예요.\n\n")

PREDICT_TAIL_SOFT = ("참고: 결과가 은행 판단이나 개인 사정에 따라 달라질 수 있는 부분은 수집한 문서만으로는 단정할 수 없어요. "
                     "위 내용은 문서가 정한 조건이에요.")
PREDICT_LEAD_SOFT = ("결과가 은행 판단이나 개인 사정에 따라 달라질 수 있는 부분은 수집한 문서만으로는 단정할 수 없어요. "
                     "문서로 확인되는 조건은 아래와 같아요.\n\n")

# 2. 질문이 지목한 문서
DOC = re.compile(r"([가-힣A-Za-z0-9Ⅰ-Ⅹ]+)?\s*(상품설명서|추가약정서|약정서|보증약관|기본약관)")
GENERIC = {"신용대출", "대출", "대출거래", "가계용", "가계", "가계대출", "은행", "여신거래", "은행여신거래", "기본", "이",
           "하나은행", "토스뱅크", "카카오뱅크", "그", "해당", "제", "내", "그런", "모든", "어느", "각", "두", "은행의", "대출의",
           "신용대출의", "에", "의"}
LAYER_WORD = {"약정서": "약정서", "추가약정서": "추가약정서", "상품설명서": "상품설명서", "기본약관": "기본약관",
              "보증약관": "보증약관"}


def _titles(inventory: dict[str, list[str]], bank: str) -> list[str]:
    return [t.replace(" ", "") for t in inventory.get(bank, [])]


def missing_docs(question: str, banks: list[str], inventory: dict[str, list[str]]) -> list[str]:
    """질문이 지목했는데 수집 문서에 없는 문서 이름들."""
    out = []
    for m in DOC.finditer(question):
        qual, kind = (m.group(1) or "").strip(), m.group(2)
        if re.search(r"(가|이|은|는|을|를|나|와|과|도|만)$", qual):
            qual = ""  # '사유가 약정서나'처럼 조사로 끝나면 문서 이름이 아니다
        qual = re.sub(r"(의|에|용)$", "", qual) if qual not in GENERIC else qual
        for bank in banks or list(inventory):
            titles = _titles(inventory, bank)
            if not titles:
                continue
            if kind == "약정서":
                has = any("약정서" in t and "추가" not in t for t in titles)
            elif kind == "기본약관":
                has = any("기본약관" in t for t in titles)
            else:
                has = any(kind in t for t in titles)
            named = qual and qual not in GENERIC and len(qual) >= 2
            if not has or (named and not any(qual in t for t in titles)):
                name = f"{bank} {(qual + ' ') if named else ''}{kind}".strip()
                if name not in out:
                    out.append(name)
    return out


# --- AI 분류기 (2026-11-03) -------------------------------------------------
# 처음 보는 45문항에서 정규식은 판단 불가 15개 중 4개만 잡았다(eval/results-guard.md). 말을 바꾸면 놓치므로,
# 답을 쓰기 전에 모델에게 질문 종류만 따로 묻는다. 정규식과 분류기 중 하나라도 걸리면 표시한다.
# 지시문 v1은 평가 문항을 보지 않고 정의만으로 썼다. v2(2026-11-03)는 평가 72문항의 오탐 7개(사정을 길게 말한 규칙 질문)를 보고
# '사정이 길어도 규칙으로 정해지면 false'를 더했다. 예시는 평가 문항과 다른 내용으로 지었다. 그래서 v2는 새 질문셋(guard-holdout-v2)으로 다시 확인한다.
CLASSIFY_VERSION = "v2"
CLASSIFY_SYSTEM = """너는 대출 약관 질문을 분류한다. 질문에 답하지 말고, 질문의 종류만 JSON으로 낸다.

predict: 질문의 답이 문서에 적힌 규칙만으로는 정해지지 않고, 은행의 재량·심사 판단이나 질문자의 비공개 정보(신용점수, 소득, 심사 기록 등)가 있어야만 정해지는가?
- true: 내 신청이 승인·수용·거절될지, 은행이 재량으로 나에게 어떤 조치를 실제로 할지, 내 금리·한도·점수·감면액이 얼마로 나올지, 내 사정이 '현저한', '상당한' 같은 판단이 필요한 사유에 해당하는지.
- false: 질문자가 자기 사정을 길게 설명하더라도, 그 사정에 문서의 규칙(기한, 처리 순서, 자동 효과, 통지 의무, 계산식, 조건)을 적용하면 답이 정해지는 경우. "이 경우 어떻게 되나요", "제가 해야 하나요", "그대로 써도 되나요", "다 갚아야 하나요"는 대개 규칙을 묻는 것이다. 절차·기간·서류·계산식·정의를 묻는 것도 false.
- '승인', '거절', '얼마', '점수' 같은 말이 있어도 규칙을 묻는 것이면 false. 여러 물음 중 하나라도 true에 해당하면 true.

missing_doc: 질문이 특정 문서(약관, 약정서, 설명서, 내규, 고시표, 보증서, 특정 상품 전용 문서 등)를 지목하거나 그 문서 기준으로 답해 달라고 하는데, 그 문서가 [수집한 문서] 목록에 없으면 그 문서 이름을 짧게 적는다. 목록에 있거나 문서를 지목하지 않았으면 null.

예) "이 대출 갚을 때 원금부터 빠지나요 이자부터 빠지나요?" → {"predict": false, "missing_doc": null}
예) "주말에 이사하느라 이자를 이틀 늦게 냈어요. 그동안 연체이자가 붙나요?" → {"predict": false, "missing_doc": null}
예) "제 사업이 어려워졌는데 은행이 만기를 늘려 줄까요?" → {"predict": true, "missing_doc": null}
예) "주택담보대출 전용 약관에서는 연체 기준이 며칠이에요?" (목록에 없음) → {"predict": false, "missing_doc": "주택담보대출 전용 약관"}

출력은 {"predict": true 또는 false, "missing_doc": "문서 이름" 또는 null} 하나만."""


def classify_prompt(question: str, inventory: dict[str, list[str]]) -> tuple[str, str]:
    docs = "\n".join(f"- {b}: {', '.join(ds)}" for b, ds in inventory.items())
    return CLASSIFY_SYSTEM, f"[수집한 문서]\n{docs}\n\n[질문]\n{question}"


def parse_classify(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}
    md = d.get("missing_doc")
    return {"predict": d.get("predict") is True, "missing_doc": md if isinstance(md, str) and md.strip() else None}


MORTGAGE_Q = re.compile(r"주택|담보|주담대|아파트|전세")


def mortgage_mixed(question: str, text: str) -> bool:
    """신용대출 질문의 답이 주택담보대출 조건을 구분 없이 앞세웠는가.
    "1개월(주택담보대출은 2개월)"처럼 괄호로 구분했거나 신용대출 기준(1개월·2회)을 함께 쓴 답은 괜찮다."""
    if "주택담보" not in text or MORTGAGE_Q.search(question):
        return False
    bare = re.sub(r"\([^()]*주택담보[^()]*\)", "", text)
    if "주택담보" not in bare:
        return False
    return not re.search(r"1\s*개월|2\s*회", bare)


def apply(question: str, banks: list[str], inventory: dict[str, list[str]], status: str, text: str,
          warnings_used: list[str], flags: dict | None = None, n_refs: int | None = None) -> tuple[str, str, list[str]]:
    """(status, text, 붙인 안전장치 이름들)을 돌려준다. flags는 AI 분류기 결과({predict, missing_doc}),
    n_refs는 답이 실제로 댄 근거 개수(None이면 검사하지 않는다)."""
    flags = flags or {}
    fired = []
    by_rule = any(p.search(question) for p in PREDICT)
    by_ai = flags.get("predict") is True
    if status == "answered" and (by_rule or by_ai) and not CANNOT.search(text):
        if by_rule:
            status, text = "cannot_judge", PREDICT_LEAD + text
            fired.append("predict")
        else:
            # 분류기만 걸린 경우는 규칙 질문을 잘못 잡았을 수 있어(새 문항 오탐 약 4~13%), 모델이 쓴 결론을 앞에 두고
            # 뒤에 한 줄을 붙인다 (2026-11-03 가상 사용자 테스트: 앞에 붙이면 결론이 밀려 "또 모른다는 거야" 반응)
            status, text = "check_needed", text + "\n\n" + PREDICT_TAIL_SOFT
            fired.append("predict_ai")
    missing = missing_docs(question, banks, inventory)
    if not missing and flags.get("missing_doc"):
        missing = [flags["missing_doc"]]
    if missing and not CHECK.search(text):
        text += ("\n\n확인 필요: 질문하신 " + ", ".join(f"'{m}'" for m in missing) +
                 "은(는) 수집한 문서에 없어요. 위 내용은 수집한 다른 문서 기준이라, 그 문서의 실제 내용은 은행에 확인해 주세요.")
        if status == "answered":
            status = "check_needed"
        fired.append("missing_doc")
    if warnings_used and not CHECK.search(text):
        text += "\n\n확인 필요: " + " ".join(warnings_used)
        if status in ("answered", "flag_missing"):
            status = "check_needed"
        fired.append("crossref")
    # 4. 근거 없는 답 (2026-11-03 가상 사용자 테스트: 근거 0개로 "해약금 없음"이라고만 답함)
    if n_refs == 0 and status in ("answered", "check_needed"):
        text += "\n\n확인 필요: 이 답에는 근거 조항이 달리지 않았어요. 문서로 확인한 답이 아니니 은행에 확인해 주세요."
        status = "check_needed"
        fired.append("no_refs")
    # 5. 신용대출 질문에 주택담보대출 조건이 섞인 답 (같은 테스트: 이자 '2개월' 기준을 앞세움)
    if mortgage_mixed(question, text):
        text += ("\n\n확인 필요: 위 답에 주택담보대출 조건이 섞여 있어요. 신용대출은 기준(기간·횟수)이 다를 수 있으니 "
                 "근거 원문에서 신용대출에 해당하는 부분을 확인해 주세요.")
        if status == "answered":
            status = "check_needed"
        fired.append("mortgage_mix")
    return status, text, fired
