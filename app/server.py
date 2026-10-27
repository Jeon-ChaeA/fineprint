"""fineprint 소비자용 프로토타입 서버 (표준 라이브러리만 씀).

    python app/server.py            → http://localhost:8000
    ANTHROPIC_API_KEY가 있으면 직접 쓴 질문에 실시간으로 답한다(초안 → 점검, 문항당 LLM 2번).
    없으면 데모 모드: 요약과 예시 질문의 답만 보여 준다.

조항 원문은 로컬 data/processed에서 읽는다(레포에 없음). 이해 확인 응답은 app/feedback.local.jsonl에 쌓인다.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import state  # noqa: E402
from fineprint.present import answer as present  # noqa: E402
from fineprint.retrieve import detect_banks  # noqa: E402

AGENT = state.load_agent()
LIVE = bool(os.environ.get("ANTHROPIC_API_KEY")) and AGENT is not None
PAGE = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
        "<style>[hidden]{display:none!important}</style></head><body>")


def ask(question: str, bank: str) -> dict:
    named = detect_banks(question)
    banks = named if named else [bank]
    ctx = AGENT.context(question, banks)
    system, user = AGENT.prompt(ctx)
    draft = AGENT.generate(system, user)
    system, user = AGENT.review_prompt(ctx, draft)
    out = present(ctx, AGENT.parse(ctx, AGENT.generate(system, user)))
    out["chunks"] = state.chunk_payload(AGENT, [r["chunk_id"] for r in out["refs"]])
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = PAGE + (HERE / "ui.html").read_text(encoding="utf-8") + "</body></html>"
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(state.build(AGENT, LIVE))
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/ask":
            if not LIVE:
                return self._json({"error": "API 키가 없어 데모 모드예요. ANTHROPIC_API_KEY를 넣고 다시 실행해 주세요."}, 400)
            q = (data.get("question") or "").strip()[:500]
            if not q:
                return self._json({"error": "질문이 비어 있어요."}, 400)
            try:
                self._json(ask(q, data.get("bank") or "토스뱅크"))
            except Exception as e:  # LLM 호출 실패 등
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        elif self.path == "/api/feedback":
            rec = {"at": datetime.now().isoformat(timespec="seconds"), **{k: data.get(k) for k in ("kind", "bank", "value")}}
            with open(HERE / "feedback.local.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):  # 질문 내용은 로그에 남기지 않는다
        pass


def main():
    port = int(os.environ.get("PORT", 8000))
    if AGENT is None:
        print("data/processed가 없어 조항 원문과 실시간 답변을 쓸 수 없어요. 요약·예시 답의 표기만 보여 줘요.")
    print(f"fineprint {'실시간' if LIVE else '데모'} 모드 → http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
