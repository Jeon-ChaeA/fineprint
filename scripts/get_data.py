"""비공개 레포 fineprint-data에서 약관 처리 데이터를 받아 data/processed에 푼다 (D-010).

약관 원문이 들어 있어 공개 레포에는 두지 않는다. fineprint-data에는 json 11개를 tar.xz로 묶어
base64로 바꾼 조각(b64/part_*)이 있다.

    # PC: fineprint-data를 클론한 뒤 그 경로를 준다
    git clone https://github.com/Jeon-ChaeA/fineprint-data ..\\fineprint-data
    python scripts/get_data.py --from ..\\fineprint-data

    # 배포 서버: 읽기 전용 토큰으로 GitHub API에서 바로 받는다
    FINEPRINT_DATA_TOKEN=... python scripts/get_data.py

받은 묶음은 SHA-256으로 확인하고, 다르면 풀지 않는다.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed"
REPO = "Jeon-ChaeA/fineprint-data"
PARTS = 4
SHA256 = "b31f5d469c8458f4747786c0f01d4178f1a3e156bcb3575c144ee293c516da66"
# 사이클 2 신용카드 (D-011): card/b64/part_* → data/processed/card. 없으면 카드 없이 뜬다
CARD = {"prefix": "card/", "parts": 1, "out": ROOT / "data" / "processed" / "card",
        "sha256": "d6a83d9e8c9be97b86ea460976d1929a5140a9e5a5cc9a385032fbf9aa895e6e"}


def from_dir(path: Path, prefix: str = "", parts: int = PARTS) -> str:
    return "".join((path / prefix / "b64" / f"part_{i}").read_text(encoding="ascii") for i in range(parts))


def from_github(token: str, prefix: str = "", parts: int = PARTS) -> str:
    out = []
    for i in range(parts):
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/{prefix}b64/part_{i}", headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=30) as r:
            out.append(base64.b64decode(json.loads(r.read())["content"]).decode("ascii"))
    return "".join(out)


def unpack(text: str, sha: str, out: Path) -> int:
    blob = base64.b64decode(text)  # 줄바꿈은 무시된다
    if hashlib.sha256(blob).hexdigest() != sha:
        sys.exit(f"받은 데이터가 원본과 달라요(SHA-256 불일치). 풀지 않았어요: {out}")
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as tar:
        names = [m.name for m in tar.getmembers()]
        if any(not n.endswith(".json") or "/" in n.lstrip("./") or ".." in n for n in names):
            sys.exit(f"예상하지 못한 파일이 있어요: {names}")
        for m in tar.getmembers():
            (out / Path(m.name).name).write_bytes(tar.extractfile(m).read())
    return len(names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default=None, help="fineprint-data를 클론한 폴더")
    args = ap.parse_args()
    token = os.environ.get("FINEPRINT_DATA_TOKEN")
    if args.src:
        get = lambda prefix="", parts=PARTS: from_dir(Path(args.src), prefix, parts)  # noqa: E731
    elif token:
        get = lambda prefix="", parts=PARTS: from_github(token, prefix, parts)  # noqa: E731
    else:
        sys.exit("--from <fineprint-data 폴더> 또는 FINEPRINT_DATA_TOKEN이 필요해요.")
    print(f"json {unpack(get(), SHA256, OUT)}개 → {OUT}")
    try:
        text = get(CARD["prefix"], CARD["parts"])
    except Exception as e:  # noqa: BLE001  카드 데이터가 아직 없으면 대출만으로 뜬다
        print(f"[건너뜀] 카드 데이터 없음 ({type(e).__name__})")
        return
    print(f"카드 json {unpack(text, CARD['sha256'], CARD['out'])}개 → {CARD['out']}")


if __name__ == "__main__":
    main()
