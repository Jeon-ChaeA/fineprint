"""1차 평가: 에이전트 답을 평가 질문셋으로 채점한다.

    # 1) 문항마다 근거를 찾고 프롬프트를 만든다 (LLM 없이)
    python scripts/run_eval.py prompts --run runs/v1

    # 2) 답 만들기: API 키가 있으면
    ANTHROPIC_API_KEY=... python scripts/run_eval.py generate --run runs/v1
    #    키가 없으면 runs/v1/prompts.jsonl로 다른 방법으로 답을 만들어
    #    runs/v1/answers.jsonl ({"id": "Q01", "raw": "..."} 한 줄씩)에 넣는다.

    # 3) 채점
    python scripts/run_eval.py score --run runs/v1

자동 채점은 인용, 판단 불가, 확인 필요 표시, 권유 표현만 본다.
답 내용이 맞는지(답 정확도)는 runs/v1/grading.md를 보고 사람이 채점한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fineprint.agent import Agent, Context  # noqa: E402

CANNOT = re.compile(r"판단할 수 없|판단하기 어렵|확인할 수 없|알 수 없|답할 수 없")
ADVICE = re.compile(r"추천(합니다|드립니다|해요)|더 (낫|유리)|이 낫습니다|가 낫습니다|(을|를) 권(합니다|해요)|고르시는 (게|것이) 좋|선택하시는 (게|것이) 좋")
BANKS = {"toss": "토스뱅크", "kakao": "카카오뱅크", "hana": "하나은행"}
SAME_PAGE = {("hana_manual", 1): 4, ("hana_manual", 2): 5, ("hana_manual", 3): 6}
SAME_PAGE.update({(d, b): a for (d, a), b in list(SAME_PAGE.items())})


def key(c: dict) -> tuple:
    if "article" in c:
        return (c["doc"], c["article"])
    return (c["doc"], c.get("page"))


def gold_keys(q: dict, with_related: bool = False) -> set:
    cs = q["citations"] + (q.get("related", []) if with_related else [])
    out = set()
    for c in cs:
        k = key(c)
        out.add(k)
        if k in SAME_PAGE:
            out.add((k[0], SAME_PAGE[k]))
    return out


def load_eval(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def cmd_prompts(args):
    agent = Agent()
    run = Path(args.run)
    run.mkdir(parents=True, exist_ok=True)
    with open(run / "prompts.jsonl", "w", encoding="utf-8") as f:
        for q in load_eval(args.eval):
            banks = None if q["bank"] == "공통" else [q["bank"]]
            if q["answerable"] == "no_advice":
                banks = None  # 두 은행을 묻는 질문은 질문에서 은행을 찾는다
            ctx = agent.context(q["question"], banks)
            system, user = agent.prompt(ctx)
            f.write(json.dumps({"id": q["id"], "system": system, "user": user,
                                "chunks": [c.id for c in ctx.chunks],
                                "warnings": [w.text() for w in ctx.warnings]}, ensure_ascii=False) + "\n")
    print(f"프롬프트 {len(load_eval(args.eval))}개 → {run / 'prompts.jsonl'}")


def cmd_generate(args):
    agent = Agent()
    run = Path(args.run)
    prompts = [json.loads(l) for l in open(run / "prompts.jsonl", encoding="utf-8")]
    with open(run / "answers.jsonl", "w", encoding="utf-8") as f:
        for p in prompts:
            raw = agent.generate(p["system"], p["user"], args.model)
            f.write(json.dumps({"id": p["id"], "raw": raw}, ensure_ascii=False) + "\n")
            print(p["id"], "done")


def cmd_score(args):
    agent = Agent()
    run = Path(args.run)
    qs = {q["id"]: q for q in load_eval(args.eval)}
    prompts = {p["id"]: p for p in (json.loads(l) for l in open(run / "prompts.jsonl", encoding="utf-8"))}
    answers = {a["id"]: a for a in (json.loads(l) for l in open(run / "answers.jsonl", encoding="utf-8"))}
    by_id = {c.id: c for c in agent.chunks}

    def parsed(qid):
        """프롬프트를 만들 때의 근거 목록으로 C번호를 되돌려 답을 읽는다"""
        a = answers.get(qid)
        if not a:
            return None
        ctx = Context(qs[qid]["question"], [], [by_id[i] for i in prompts[qid]["chunks"]])
        return agent.parse(ctx, a["raw"])

    rows, m = [], {"cite_n": 0, "cite_hit": 0, "cite_first": 0, "no_n": 0, "no_ok": 0,
                   "check_n": 0, "check_ok": 0, "advice": 0, "invalid": 0, "precise_n": 0, "precise_hit": 0}
    for qid, q in qs.items():
        ans = parsed(qid)
        if not ans:
            rows.append((qid, "답 없음", "", ""))
            continue
        text = ans.answer
        got = {key(c) for c in ans.citations}
        notes = []
        m["invalid"] += len(ans.invalid)
        if ans.invalid:
            notes.append(f"없는 근거 {ans.invalid}")
        if ADVICE.search(text):
            m["advice"] += 1
            notes.append("권유 표현")
        verdict = ""
        if q["answerable"] in ("yes", "check") and q["citations"]:
            m["cite_n"] += 1
            gold = gold_keys(q)
            hit = bool(got & gold)
            m["cite_hit"] += hit
            m["cite_first"] += key(q["citations"][0]) in got or (
                key(q["citations"][0]) in SAME_PAGE and (q["citations"][0]["doc"], SAME_PAGE[key(q["citations"][0])]) in got)
            # 답이 댄 근거 중 정답·관련 근거이거나 같은 은행 문서인 비율(엉뚱한 은행 인용 탐지)
            related = gold_keys(q, True)
            for c in ans.citations:
                m["precise_n"] += 1
                m["precise_hit"] += key(c) in related or q["bank"] == BANKS[c["doc"].split("_")[0]]
            verdict = "인용 OK" if hit else "인용 X"
        if q["answerable"] == "no":
            m["no_n"] += 1
            ok = bool(CANNOT.search(text)) or ans.status == "cannot_judge"
            m["no_ok"] += ok
            verdict = "판단 불가 OK" if ok else "판단 불가 X"
        if q["answerable"] == "check":
            m["check_n"] += 1
            ok = "확인 필요" in text
            m["check_ok"] += ok
            verdict += " / 확인 필요 OK" if ok else " / 확인 필요 X"
        if q["answerable"] == "no_advice":
            verdict = "권유 X" if "권유 표현" in notes else "권유 없음 OK"
        rows.append((qid, verdict, ", ".join(ans.labels[:3]), "; ".join(notes)))

    pct = lambda a, b: f"{a}/{b} ({a / b:.0%})" if b else "-"
    summary = {
        "인용 정확도 (정답 근거 중 하나 이상)": pct(m["cite_hit"], m["cite_n"]),
        "첫 번째 정답 근거 인용": pct(m["cite_first"], m["cite_n"]),
        "인용 정밀도 (정답·관련 근거이거나 질문 은행 문서)": pct(m["precise_hit"], m["precise_n"]),
        "판단 불가 응답률": pct(m["no_ok"], m["no_n"]),
        "함정 탐지 ('확인 필요' 표시)": pct(m["check_ok"], m["check_n"]),
        "권유 표현": f"{m['advice']}건",
        "근거 목록에 없는 인용": f"{m['invalid']}건",
    }
    out = run / "score.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("# 자동 채점 결과\n\n| 지표 | 결과 |\n|---|---|\n")
        for k, v in summary.items():
            f.write(f"| {k} | {v} |\n")
        f.write("\n| 문항 | 판정 | 답이 댄 근거 (앞 3개) | 메모 |\n|---|---|---|---|\n")
        for r in rows:
            f.write("| " + " | ".join(x.replace("|", "/") for x in r) + " |\n")
    # 사람 채점용 시트. 이미 있으면 채점 내용을 지키려고 grading.new.md로 쓴다
    sheet = run / ("grading.new.md" if (run / "grading.md").exists() else "grading.md")
    with open(sheet, "w", encoding="utf-8") as f:
        f.write("# 답 정확도 채점지\n\n문항마다 '정답 요지'를 빠짐없이, 틀린 말 없이 담았으면 O, 일부만 맞으면 △, 틀리면 X.\n\n")
        for qid, q in qs.items():
            ans = parsed(qid)
            f.write(f"## {qid} ({q['answerable']}) {q['question']}\n\n")
            f.write(f"- **정답 요지**: {q['expected']}\n")
            if q.get("note"):
                f.write(f"- **채점 메모**: {q['note']}\n")
            f.write(f"- **에이전트 답**: {ans.answer if ans else '(없음)'}\n")
            if ans:
                f.write(f"- **에이전트 근거**: {'; '.join(ans.labels) or '(없음)'}\n")
            f.write("- **채점**: \n\n")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"→ {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prompts", "generate", "score"])
    ap.add_argument("--run", default=str(ROOT / "runs" / "v1"))
    ap.add_argument("--eval", default=str(ROOT / "eval" / "credit-loan-v1.jsonl"))
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    {"prompts": cmd_prompts, "generate": cmd_generate, "score": cmd_score}[args.cmd](args)


if __name__ == "__main__":
    main()
