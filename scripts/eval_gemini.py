"""Gemini로 72문항을 돌려 Claude(1.6)와 비교할 답을 만든다 (D-010).

    $env:GEMINI_API_KEY="..."; python scripts/eval_gemini.py

질문셋 5개마다 초안 → 점검 → 자동 채점을 한다. 결과는 runs/gemini/<모델>/<셋>/에 쌓인다 (--model을 안 주면 runs/gemini/default/).
무료 API의 분당 한도 때문에 호출 사이에 쉬고(--sleep), 중간에 멈추면 같은 명령으로 이어서 한다.
답 원문(answers*.jsonl)은 레포에 올리지 않는다(.gitignore). 답 정확도는 1.6처럼 블라인드로 따로 채점한다.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETS = {"q": "credit-loan-v1", "h": "credit-loan-holdout-v1", "j": "credit-loan-holdout-v2",
        "k": "credit-loan-holdout-v3", "l": "credit-loan-holdout-v4"}


def run(*args):
    cmd = [sys.executable, str(ROOT / "scripts" / "run_eval.py"), *args]
    print(">", " ".join(args), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, env=os.environ | {"FINEPRINT_LLM": "gemini"})


def lines(p: Path) -> int:
    return sum(1 for l in open(p, encoding="utf-8") if l.strip()) if p.exists() else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default="qhjkl", help="돌릴 질문셋 (기본: 다섯 개 모두)")
    ap.add_argument("--sleep", default="7", help="호출 사이 쉬는 초")
    ap.add_argument("--model", default=None, help="기본: FINEPRINT_MODEL 또는 gemini-3.5-flash-lite")
    args = ap.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY가 없어요. PowerShell에서 $env:GEMINI_API_KEY=\"...\" 를 먼저 실행해 주세요.")
    if not list((ROOT / "data" / "processed").glob("*.json")):
        sys.exit("약관 데이터가 없어요. 먼저 python scripts/get_data.py --from ..\\fineprint-data 를 실행해 주세요.")
    model = ["--model", args.model] if args.model else []
    for key in args.sets:
        name = SETS[key]
        ev = ["--eval", str(ROOT / "eval" / f"{name}.jsonl")]
        base = ROOT / "runs" / "gemini" / (args.model or "default")  # 모델마다 폴더를 따로 둔다
        draft, final = base / f"{key}-draft", base / key
        n = lines(ROOT / "eval" / f"{name}.jsonl")
        if lines(draft / "prompts.jsonl") < n:
            run("prompts", "--run", str(draft), *ev)
        if lines(draft / "answers.jsonl") < n:
            run("generate", "--run", str(draft), "--resume", "--sleep", args.sleep, *model)
        if lines(final / "review_prompts.jsonl") < n:
            run("review", "--from", str(draft), "--run", str(final), *ev)
        if lines(final / "answers.jsonl") < n:
            run("generate", "--run", str(final), "--stage", "review", "--resume", "--sleep", args.sleep, *model)
        run("score", "--run", str(final), *ev)
    print(f"끝났어요. 결과: {ROOT / 'runs' / 'gemini' / (args.model or 'default')}")


if __name__ == "__main__":
    main()
