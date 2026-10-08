"""평가 질문셋의 정답 근거가 실제 원문에 있는지 확인한다.

사용법:
    python scripts/check_eval.py --eval eval/credit-loan-v1.jsonl --processed data/processed

- 인용한 문서·조·항(또는 쪽)이 조항 분할 결과에 있는지
- evidence 문구가 첫 번째 인용의 본문에 실제로 들어 있는지 (공백 무시)
- 인용한 문서의 버전이 data/sources.json의 버전과 같은지
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
norm = lambda s: re.sub(r"\s+", "", s or "")
BANKS = {"toss": "토스뱅크", "kakao": "카카오뱅크", "hana": "하나은행"}


def find_unit(doc, cite):
    for u in doc["units"]:
        if "page" in cite and doc["unit"] == "page" and u["page"] == cite["page"]:
            return u
        if "article" in cite and u.get("section", "본문") == "본문" and u.get("article") == cite["article"]:
            return u
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(ROOT / "eval" / "credit-loan-v1.jsonl"))
    ap.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    args = ap.parse_args()
    versions = {d["id"]: d["effective"] for d in json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))["documents"]}
    docs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in Path(args.processed).glob("*.json")}
    problems = 0
    unverified = 0
    for line in Path(args.eval).read_text(encoding="utf-8").splitlines():
        q = json.loads(line)
        issues = []
        for c in q["citations"]:
            if q["bank"] != "공통" and BANKS[c["doc"].split("_")[0]] != q["bank"]:
                issues.append(f"{c['doc']}는 질문 은행({q['bank']}) 문서가 아님 → related로")
        for i, c in enumerate(q["citations"] + q.get("related", [])):
            if versions.get(c["doc"]) != c["version"]:
                issues.append(f"{c['doc']} 버전 불일치")
            doc = docs.get(c["doc"])
            if not doc:
                issues.append(f"{c['doc']} 없음")
                continue
            u = find_unit(doc, c)
            if not u:
                issues.append(f"{c['doc']} {c.get('article') or 'p.' + str(c.get('page'))} 없음")
                continue
            p = c.get("paragraph")
            if p and p in "①②③④⑤⑥⑦⑧⑨⑩" and p not in [x["paragraph"] for x in u.get("paragraphs", [])]:
                issues.append(f"{c['doc']} {c['article']} {p} 없음")
            if p and p.isdigit():
                unverified += 1  # 숫자 항(토스뱅크 약정서)은 파싱 결과에서 나뉘지 않아 조 단위까지만 검증된다
            if i == 0 and q.get("evidence") and norm(q["evidence"]) not in norm(u["text"]):
                issues.append(f"evidence가 {c['doc']} {c.get('article') or 'p.' + str(c.get('page'))}에 없음")
        status = "OK " if not issues else "NG "
        problems += bool(issues)
        print(status, q["id"], q["category"], "; ".join(issues))
    print(f"\n문항 {sum(1 for _ in Path(args.eval).read_text(encoding='utf-8').splitlines())}개, 문제 {problems}개")
    print(f"참고: 숫자 항 인용 {unverified}건은 조 단위까지만 검증됨")


if __name__ == "__main__":
    main()
