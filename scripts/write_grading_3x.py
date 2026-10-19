"""3회 블라인드 채점 결과를 실행 폴더마다 채점지(grading_3x.md)로 쓴다.

사용법: python scripts/write_grading_3x.py <blind 폴더>
"""
import json
import sys
import collections

S = sys.argv[1]
key = json.load(open(f"{S}/key.json"))
G = {}
for p in ["p1", "p2", "p3", "p4"]:
    G.update(json.load(open(f"{S}/{p}.grades.json")))
final = json.load(open(f"{S}/final.json"))
SETS = {
    "v1.3": "eval/credit-loan-v1.jsonl", "v1.4": "eval/credit-loan-v1.jsonl",
    "v1.3-holdout": "eval/credit-loan-holdout-v1.jsonl", "v1.4-holdout": "eval/credit-loan-holdout-v1.jsonl",
    "v1.3-holdout2": "eval/credit-loan-holdout-v2.jsonl", "v1.4-holdout2": "eval/credit-loan-holdout-v2.jsonl",
    "v1.3-holdout3": "eval/credit-loan-holdout-v3.jsonl", "v1.4-holdout3": "eval/credit-loan-holdout-v3.jsonl",
}
TITLE = {"v1.3": "1.3", "v1.4": "1.4"}


def text(raw):
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])["answer"]
    except Exception:
        return raw


for run, ev in SETS.items():
    by = collections.defaultdict(dict)
    for q, labs in G.items():
        for lab, v in labs.items():
            r, rep = key[q][lab].split(":")
            if r == run:
                by[q][rep] = v
    ans = {}
    for rep in ("r1", "r2", "r3"):
        for line in open(f"runs/{run}/answers_{rep}.jsonl", encoding="utf-8"):
            x = json.loads(line)
            ans[(x["id"], rep)] = text(x["raw"])
    qs = [json.loads(l) for l in open(ev, encoding="utf-8")]
    cnt = collections.Counter(final[f"{q['id']}|{run}"] for q in qs)
    ver = TITLE[run.split("-")[0]]
    out = [f"# 답 정확도 채점지 ({ver}, {run}, 문항당 3회)\n",
           "같은 프롬프트로 3번 돌린 답(r1~r3)을 1.3·1.4 답 6개와 섞어 A~F로만 표시하고 블라인드로 채점했다. "
           "문항 등급은 3회 다수결(O 2회 이상 → O, △ 2회 이상 → △, X 2회 이상 → X, 셋 다 다르면 △). 전채아 확인 전.\n",
           f"**합계**: O {cnt['O']} · △ {cnt['△']} · X {cnt['X']}\n"]
    for q in qs:
        qid = q["id"]
        out.append(f"## {qid} ({q['answerable']}) {q['question']}\n")
        out.append(f"- **정답 요지**: {q['expected']}")
        if q.get("note"):
            out.append(f"- **채점 메모**: {q['note']}")
        out.append(f"- **채점 (3회 다수결, AI 블라인드, 전채아 확인 전)**: {final[f'{qid}|{run}']}  "
                   f"(r1 {by[qid]['r1'][0]} · r2 {by[qid]['r2'][0]} · r3 {by[qid]['r3'][0]})")
        for rep in ("r1", "r2", "r3"):
            g, vb, why = by[qid][rep]
            tag = f"{g}" + (f" — {why}" if why else "") + (" (장황)" if vb == "Y" else "")
            out.append(f"\n  - **{rep} 답** [{tag}]: {ans[(qid, rep)]}")
        out.append("")
    open(f"runs/{run}/grading_3x.md", "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(run, dict(cnt))
