"""안전장치 확인: 정규식과 AI 분류기가 질문을 제대로 가려내는지 본다 (eval/results-guard.md).

    $env:GEMINI_API_KEY="..."; python scripts/eval_guard.py

평가 72문항(규칙을 만든 문항)과 처음 보는 45문항(guard-holdout-v1)을 Gemini 분류기에 돌려
runs/guard/<모델>/flags.jsonl에 쌓고(중간에 멈추면 이어서 한다), 정규식만 / 분류기만 / 둘 중 하나 결과를 표로 낸다.
답을 만들지 않으므로 문항당 호출은 1번이다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FINEPRINT_LLM", "gemini")

from fineprint import guard  # noqa: E402
from fineprint.agent import Agent  # noqa: E402
from fineprint.retrieve import detect_banks  # noqa: E402

SETS = {"평가 72문항": sorted(glob.glob(str(ROOT / "eval" / "credit-loan*.jsonl"))),
        "처음 보는 45문항": [str(ROOT / "eval" / "guard-holdout-v1.jsonl")],
        "처음 보는 v2": [str(ROOT / "eval" / "guard-holdout-v2.jsonl")]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--sleep", type=float, default=4)
    args = ap.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY가 없어요.")
    agent = Agent()
    out = (ROOT / "runs" / "guard" / (args.model or os.environ.get("FINEPRINT_MODEL", "default"))
           / guard.CLASSIFY_VERSION / "flags.jsonl")  # 분류기 지시가 바뀌면 새로 돌린다
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if out.exists():
        done = {d["id"]: d for d in (json.loads(l) for l in open(out, encoding="utf-8") if l.strip())}

    table = []
    with open(out, "a", encoding="utf-8") as f:
        for name, files in SETS.items():
            files = [p for p in files if os.path.exists(p)]
            if not files:
                continue
            rows = [json.loads(l) for p in files for l in open(p, encoding="utf-8") if l.strip()]
            cnt = {k: {"n": 0, "re": 0, "ai": 0, "both": 0} for k in ("no", "check", "yes")}
            misses = []
            for r in rows:
                lab = r["answerable"]
                if lab not in cnt:
                    continue
                q = r["question"]
                banks = detect_banks(q) or ([r["bank"]] if r["bank"] != "공통" else sorted(agent.inventory))
                inv = {b: agent.inventory[b] for b in banks}
                if r["id"] not in done:
                    flags = agent.classify(q, banks, args.model)
                    done[r["id"]] = {"id": r["id"], **flags}
                    f.write(json.dumps(done[r["id"]], ensure_ascii=False) + "\n")
                    f.flush()
                    print(r["id"], flags, flush=True)
                    time.sleep(args.sleep)
                fl = done[r["id"]]
                re_p, ai_p = any(p.search(q) for p in guard.PREDICT), fl.get("predict") is True
                re_m, ai_m = bool(guard.missing_docs(q, banks, inv)), bool(fl.get("missing_doc"))
                if lab == "no":
                    hit = (re_p, ai_p)
                elif lab == "check":
                    hit = (re_m, ai_m)
                else:  # 일반 문항은 아무것도 안 걸려야 맞다
                    hit = (not (re_p or re_m), not (ai_p or ai_m))
                both = (hit[0] or hit[1]) if lab != "yes" else (hit[0] and hit[1])
                c = cnt[lab]
                c["n"] += 1
                c["re"] += hit[0]
                c["ai"] += hit[1]
                c["both"] += both
                if not both:
                    misses.append(f"{r['id']}({lab})")
            table.append((name, cnt, misses))

    print("\n| 질문셋 | 종류 | 정규식만 | 분류기만 | 둘 중 하나 |\n|---|---|---|---|---|")
    label = {"no": "판단 불가 → 걸림", "check": "없는 문서 → 걸림", "yes": "일반 → 안 걸림"}
    for name, cnt, misses in table:
        for k, c in cnt.items():
            print(f"| {name} | {label[k]} | {c['re']}/{c['n']} | {c['ai']}/{c['n']} | {c['both']}/{c['n']} |")
    for name, _, misses in table:
        print(f"{name} 틀린 문항: {', '.join(misses) or '없음'}")


if __name__ == "__main__":
    main()
