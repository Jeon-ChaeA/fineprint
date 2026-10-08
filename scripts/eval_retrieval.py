"""검색만 따로 평가한다: 정답 근거 조항이 검색 결과 상위 k개 안에 들어오는가.

LLM 없이 돌릴 수 있다. 답이 틀렸을 때 검색 탓인지, 답 생성 탓인지 나누어 보려고 만든다.

사용법:
    python scripts/eval_retrieval.py --k 8
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fineprint.corpus import load  # noqa: E402
from fineprint.retrieve import Index  # noqa: E402


def same(c, cite):
    if c.doc != cite["doc"]:
        return False
    if "article" in cite:
        return c.article == cite["article"]
    return c.page == cite.get("page")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(ROOT / "eval" / "credit-loan-v1.jsonl"))
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()
    idx = Index(load())
    rows = [json.loads(l) for l in open(args.eval, encoding="utf-8")]
    hit_any = hit_first = total = 0
    for q in rows:
        if not q["citations"] or q["answerable"] in ("no", "no_advice"):
            continue
        total += 1
        banks = None if q["bank"] == "공통" else [q["bank"]]
        hits = [c for c, _ in idx.search(q["question"], banks=banks, k=args.k)]
        got_any = any(same(c, ct) for c in hits for ct in q["citations"])
        got_first = any(same(c, q["citations"][0]) for c in hits)
        hit_any += got_any
        hit_first += got_first
        mark = "OK " if got_first else ("ok " if got_any else "-- ")
        top = ", ".join(f"{c.doc}:{c.article or 'p' + str(c.page)}" for c in hits[:4])
        print(f"{mark}{q['id']} {q['question'][:28]:<28} | {top}")
    print(f"\n상위 {args.k}개 안에 첫 번째 정답 근거: {hit_first}/{total} ({hit_first/total:.0%})")
    print(f"상위 {args.k}개 안에 정답 근거 중 하나라도: {hit_any}/{total} ({hit_any/total:.0%})")


if __name__ == "__main__":
    main()
