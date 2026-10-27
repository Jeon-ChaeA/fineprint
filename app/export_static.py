"""데모용 한 파일 HTML 만들기 (조항 원문 포함, 로컬에만 둔다: app/dist/는 .gitignore).

    python app/export_static.py   → app/dist/fineprint-demo.html

요약과 예시 답, 근거 원문을 페이지 안에 넣어 서버 없이 열린다. 직접 쓴 질문에는 답하지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import state  # noqa: E402


def main(full_page: bool = "--fragment" not in sys.argv):
    data = state.build(state.load_agent(), live=False)
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    ui = (HERE / "ui.html").read_text(encoding="utf-8")
    # 데이터는 화면 스크립트 바로 앞에 넣는다(<title>이 파일 앞부분에 있어야 한다)
    marker = "<script>\n(function"
    assert marker in ui
    body = ui.replace(marker, f"<script>window.FINEPRINT_STATE = {js};</script>\n" + marker, 1)
    if full_page:
        body = ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
                "<style>[hidden]{display:none!important}</style></head><body>" + body + "</body></html>")
    out = HERE / "dist" / ("fineprint-demo.html" if full_page else "fineprint-demo.fragment.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"→ {out} ({len(body) // 1024}KB)")


if __name__ == "__main__":
    main()
