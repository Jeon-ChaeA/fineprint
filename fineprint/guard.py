"""답의 안전장치 (D-010): 모델이 놓쳐도 코드가 '판단할 수 없음'·'확인 필요'를 붙인다.

Gemini 비교(eval/results-gemini.md)에서 가벼운 모델은 판단할 수 없는 질문에도 조항만 옮기고 답을 마치고,
수집하지 않은 문서를 물어도 '확인 필요'를 쓰지 않았다. 모델과 상관없이 아래 세 경우는 코드가 표시한다.

1. 결과 예측 질문: 은행이 받아들일지·승인할지, 개인의 금리·한도·점수가 얼마일지, 내 상황이 해당하는지
2. 없는 문서: 질문이 이름으로 지목한 문서(예: 하나은행 약정서, 'OO 상품설명서')가 수집 문서에 없을 때
3. 표기 불일치: 인용한 근거에 조항 번호와 제목이 맞지 않는다는 경고(crossref)가 있을 때

모델이 이미 그렇게 답했으면 아무것도 바꾸지 않는다. 문서 내용은 그대로 두고 앞이나 뒤에 문장을 붙인다.
"""
from __future__ import annotations

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


def apply(question: str, banks: list[str], inventory: dict[str, list[str]], status: str, text: str,
          warnings_used: list[str]) -> tuple[str, str, list[str]]:
    """(status, text, 붙인 안전장치 이름들)을 돌려준다."""
    fired = []
    if status == "answered" and any(p.search(question) for p in PREDICT) and not CANNOT.search(text):
        status, text = "cannot_judge", PREDICT_LEAD + text
        fired.append("predict")
    missing = missing_docs(question, banks, inventory)
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
    return status, text, fired
