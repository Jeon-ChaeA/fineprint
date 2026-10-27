"""프로토타입 데이터 만들기 (로컬 실행 원자료 → app/data).

- summaries.json: 은행별 불리할 수 있는 조건 요약. 줄마다 근거 조각 id만 둔다(원문은 넣지 않는다).
- samples.json: 예시 질문과 1.6의 답(전 문항 채점 O인 답에서 고름). 근거 조각 id와 표기만 둔다.

사용법: python scripts/make_app_data.py --summaries runs/_proto/sum.out.jsonl
API 키가 있으면 --summaries 없이 요약을 새로 만든다(fineprint.summary.summarize).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fineprint import summary  # noqa: E402
from fineprint.agent import Agent  # noqa: E402
from fineprint.present import answer as present  # noqa: E402

OUT = ROOT / "app" / "data"
BANKS = ["토스뱅크", "카카오뱅크", "하나은행"]
# 은행마다 상황이 다른 질문 4개 + 은행 비교(권유하지 않는 예). 상태(답변·판단할 수 없음·확인 필요)가 고루 섞이게 골랐다
SAMPLES = ["Q09", "H07", "K01", "Q29", "J04", "L06", "Q19", "K09", "L09", "H03", "J09", "Q31", "Q32"]
RUN = {"Q": "v1.6", "H": "v1.6-holdout", "J": "v1.6-holdout2", "K": "v1.6-holdout3", "L": "v1.6-holdout4"}
EVAL = {"Q": "credit-loan-v1", "H": "credit-loan-holdout-v1", "J": "credit-loan-holdout-v2",
        "K": "credit-loan-holdout-v3", "L": "credit-loan-holdout-v4"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summaries", default=None, help="요약 LLM 출력(jsonl: bank, raw). 없으면 API로 만든다")
    args = ap.parse_args()
    agent = Agent()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.summaries:
        raws = {json.loads(l)["bank"]: json.loads(l)["raw"] for l in open(args.summaries, encoding="utf-8")}
        sums = [summary.parse(summary.context(agent, b), raws[b]) for b in BANKS]
    else:
        sums = [summary.summarize(agent, b) for b in BANKS]
    for s in sums:
        s.pop("invalid", None)
    (OUT / "summaries.json").write_text(json.dumps(sums, ensure_ascii=False, indent=1), encoding="utf-8")

    by = {c.id: c for c in agent.chunks}
    samples = []
    for qid in SAMPLES:
        run = ROOT / "runs" / RUN[qid[0]]
        q = next(json.loads(l) for l in open(ROOT / "eval" / f"{EVAL[qid[0]]}.jsonl", encoding="utf-8")
                 if json.loads(l)["id"] == qid)
        p = next(json.loads(l) for l in open(run / "prompts.jsonl", encoding="utf-8") if json.loads(l)["id"] == qid)
        raw = next(json.loads(l)["raw"] for l in open(run / "answers_r1.jsonl", encoding="utf-8")
                   if json.loads(l)["id"] == qid)
        banks = None if q["bank"] == "공통" or q["answerable"] == "no_advice" else [q["bank"]]
        ctx = agent.context(q["question"], banks)
        ctx.chunks = [by[i] for i in p["chunks"]]
        ans = agent.parse(ctx, raw)
        samples.append({"id": qid, "bank": q["bank"], "question": q["question"], **present(ctx, ans)})
    (OUT / "samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"요약 {sum(len(s['items']) for s in sums)}줄, 예시 답 {len(samples)}개 → {OUT}")


if __name__ == "__main__":
    main()
