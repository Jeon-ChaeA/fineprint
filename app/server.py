"""fineprint 소비자용 프로토타입 서버 (표준 라이브러리만 씀).

    python app/server.py            → http://localhost:8000
    GEMINI_API_KEY(또는 ANTHROPIC_API_KEY)가 있으면 직접 쓴 질문에 실시간으로 답한다(초안 → 점검, 문항당 LLM 2번).
    없으면 데모 모드: 요약과 예시 질문의 답만 보여 준다.

공개 배포용 설정(환경 변수)
    PORT                     호스팅이 정해 주면 0.0.0.0에 연다
    FINEPRINT_DAILY_LIMIT    하루 질문 수 상한 (기본 100, 한국 시간 자정에 초기화)
    FINEPRINT_IP_LIMIT       한 사람(IP)이 10분에 할 수 있는 질문 수 (기본 5)

조항 원문은 로컬 data/processed에서 읽는다(레포에 없음). 이해 확인 응답은 app/feedback.local.jsonl에 쌓인다.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import state  # noqa: E402
from fineprint.present import answer as present  # noqa: E402
from fineprint.agent import provider  # noqa: E402
from fineprint.retrieve import detect_banks  # noqa: E402

AGENT = state.load_agent()
CARD_AGENT = state.load_card_agent()  # 사이클 2 신용카드 (D-011)
PROVIDER = provider()
LIVE = PROVIDER is not None and AGENT is not None

# 무료 API 한도와 남용을 막는 간단한 제한 (메모리에만 둔다, 질문 내용은 저장하지 않는다)
KST = timezone(timedelta(hours=9))
DAILY_LIMIT = int(os.environ.get("FINEPRINT_DAILY_LIMIT", 100))
IP_LIMIT = int(os.environ.get("FINEPRINT_IP_LIMIT", 5))
_lock = threading.Lock()
_day = {"date": None, "count": 0}
_ips: dict[str, deque] = defaultdict(deque)


def allow(ip: str) -> str | None:
    """질문을 받아도 되면 None, 아니면 사용자에게 보여 줄 이유."""
    now, today = time.time(), datetime.now(KST).date()
    with _lock:
        if _day["date"] != today:
            _day.update(date=today, count=0)
        if _day["count"] >= DAILY_LIMIT:
            return "오늘 받을 수 있는 질문 수를 다 썼어요. 내일 다시 물어봐 주세요. 예시 질문의 답은 계속 볼 수 있어요."
        q = _ips[ip]
        while q and now - q[0] > 600:
            q.popleft()
        if len(q) >= IP_LIMIT:
            return "질문이 많아 잠깐 쉬어 가요. 10분쯤 뒤에 다시 물어봐 주세요."
        q.append(now)
        _day["count"] += 1
    return None
PAGE = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
        "<style>[hidden]{display:none!important}</style></head><body>")


SUMMARIES = json.loads((HERE / "data" / "summaries.json").read_text(encoding="utf-8"))
SUMMARIES += json.loads((HERE / "data" / "summaries-card.json").read_text(encoding="utf-8"))


def ask(question: str, bank: str) -> dict:
    card = bank in state.CARD_BANKS and CARD_AGENT is not None
    agent = CARD_AGENT if card else AGENT
    named = detect_banks(question, "card" if card else "loan")
    banks = named if named else [bank]
    ctx = agent.context(question, banks)
    ctx.flags = agent.classify(question, ctx.banks)  # 안전장치용 AI 분류기 (eval/results-guard.md)
    ctx.summary_flags = [(it["topic"], it["line"]) for s in SUMMARIES if s["bank"] in ctx.banks
                         for it in s["items"] if "확인 필요" in it["line"]]
    system, user = agent.prompt(ctx)
    draft = agent.generate(system, user)
    system, user = agent.review_prompt(ctx, draft)
    out = present(ctx, agent.parse(ctx, agent.generate(system, user)))
    out["chunks"] = state.chunk_payload(agent, [r["chunk_id"] for r in out["refs"]])
    out["live"] = PROVIDER  # 화면이 실시간 답(베타)과 예시 답을 구분한다 (D-010)
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
        path = self.path.split("?", 1)[0]  # ?bank=카카오뱅크 같은 쿼리는 화면(JS)이 읽는다
        if path in ("/", "/index.html"):
            html = PAGE + (HERE / "ui.html").read_text(encoding="utf-8") + "</body></html>"
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._json(state.build(AGENT, LIVE, CARD_AGENT) | {"provider": PROVIDER if LIVE else None})
        elif path == "/healthz":
            self._send(200, b"ok", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > 8000:
            return self._json({"error": "요청이 너무 커요."}, 413)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "요청 형식이 잘못됐어요."}, 400)
        if self.path == "/api/ask":
            if not LIVE:
                return self._json({"error": "API 키가 없어 데모 모드예요. GEMINI_API_KEY를 넣고 다시 실행해 주세요."}, 400)
            q = (data.get("question") or "").strip()[:500]
            if not q:
                return self._json({"error": "질문이 비어 있어요."}, 400)
            ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
            why = allow(ip)
            if why:
                return self._json({"error": why}, 429)
            bank = data.get("bank") if data.get("bank") in state.BANKS + state.CARD_BANKS else "토스뱅크"
            try:
                self._json(ask(q, bank))
            except Exception as e:  # LLM 호출 실패 등. 자세한 내용은 서버 로그에만
                print(f"[ask error] {type(e).__name__}: {str(e)[:300]}", flush=True)
                busy = "429" in str(e)
                self._json({"error": "지금 답을 만드는 곳이 붐벼요. 잠시 뒤 다시 물어봐 주세요." if busy
                            else "답을 만들다 문제가 생겼어요. 잠시 뒤 다시 물어봐 주세요."}, 503 if busy else 500)
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
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"  # 호스팅에서는 밖에서 들어오게
    if AGENT is None:
        print("data/processed가 없어 조항 원문과 실시간 답변을 쓸 수 없어요. 요약·예시 답의 표기만 보여 줘요.")
    print(f"fineprint {'실시간(' + PROVIDER + ')' if LIVE else '데모'} 모드 → http://localhost:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
