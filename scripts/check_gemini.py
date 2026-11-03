"""Gemini API 연결 점검: 키가 맞는지, 쓸 수 있는 모델이 무엇인지, 짧은 질문에 몇 초 걸리는지 본다.

    $env:GEMINI_API_KEY="..."; python scripts/check_gemini.py
    python scripts/check_gemini.py --model gemini-3.8-flash,gemini-3.5-flash-lite,gemini-2.5-flash
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"


def call(url: str, body: dict | None, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("FINEPRINT_MODEL", "gemini-flash-latest"), help="쉼표로 여러 개")
    ap.add_argument("--skip-list", action="store_true", help="모델 목록은 건너뛴다")
    args = ap.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY가 없어요.")

    if not args.skip_list:
        print("1) 모델 목록 받기 ...", flush=True)
        t = time.time()
        try:
            models = call(f"{BASE}/models?pageSize=200", None, 30).get("models", [])
        except urllib.error.HTTPError as e:
            sys.exit(f"   실패: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:300]}  (키가 틀렸거나 API가 꺼져 있을 수 있어요)")
        except Exception as e:  # noqa: BLE001
            sys.exit(f"   실패: {type(e).__name__}: {e}  (네트워크에서 Google API로 가는 길이 막혔을 수 있어요)")
        names = [m["name"].split("/", 1)[1] for m in models if "generateContent" in m.get("supportedGenerationMethods", [])]
        print(f"   성공 ({time.time() - t:.1f}초). 답을 만들 수 있는 모델 {len(names)}개:")
        for n in names:
            if "flash" in n or "pro" in n or "gemma" in n:
                print("   -", n)

    for model in [m.strip() for m in args.model.split(",") if m.strip()]:
        ask(model)


def ask(model: str):
    print(f"2) '{model}'에게 짧은 질문 ...", flush=True)
    t = time.time()
    try:
        out = call(f"{BASE}/models/{model}:generateContent",
                   {"contents": [{"role": "user", "parts": [{"text": "한 문장으로: 대출의 기한의 이익이 뭐예요?"}]}]}, 180)
    except urllib.error.HTTPError as e:
        print(f"   실패: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:200]}")
        return
    except Exception as e:  # noqa: BLE001
        print(f"   실패 ({time.time() - t:.0f}초): {type(e).__name__}: {e}")
        return
    parts = out["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    usage = out.get("usageMetadata", {})
    print(f"   성공 ({time.time() - t:.1f}초): {text.strip()[:100]}")
    print(f"   토큰: 입력 {usage.get('promptTokenCount')}, 출력 {usage.get('candidatesTokenCount')}, 생각 {usage.get('thoughtsTokenCount', 0)}", flush=True)

if __name__ == "__main__":
    main()
