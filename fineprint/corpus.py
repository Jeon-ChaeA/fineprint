"""조항 분할 결과(data/processed/*.json)를 검색과 인용에 쓰는 조각(chunk)으로 바꾼다.

- 약관·약정서: 항(①②…)이 있으면 항 하나가 조각 하나, 없으면 조 하나가 조각 하나.
- 상품설명서: 쪽이 길어서 약 500자 창으로 나눈다. 인용은 쪽 단위로 한다.
- 조각마다 인용에 필요한 은행·문서·버전·조(항)·쪽을 함께 들고 다닌다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANKS = {"toss": "토스뱅크", "kakao": "카카오뱅크", "hana": "하나은행"}
LAYER_NAME = {1: "기본약관", 2: "약정서", 3: "상품설명서"}


@dataclass
class Chunk:
    id: str
    doc: str
    bank: str
    title: str          # 문서 이름
    version: str        # 시행일
    layer: int
    text: str
    article: str | None = None
    article_title: str | None = None
    paragraph: str | None = None
    page: int | None = None
    siblings: list[str] = field(default_factory=list)  # 같은 조의 다른 항 조각 id

    def cite(self) -> dict:
        c = {"doc": self.doc, "version": self.version}
        if self.article:
            c["article"] = self.article
            if self.paragraph:
                c["paragraph"] = self.paragraph
        else:
            c["page"] = self.page
        return c

    def label(self) -> str:
        """사람이 읽는 인용 표기: 토스뱅크 · 대출거래약정서 (가계용) · 2026-07-30 · 제12조 제2항"""
        where = f"{self.page}쪽" if self.page and not self.article else self.article
        if self.article and self.article_title:
            where += f"({self.article_title})"
        if self.paragraph:
            where += f" {self.paragraph}"
        return f"{self.bank} · {self.title} · {self.version} · {where}"


def _windows(text: str, size: int = 500, overlap: int = 120) -> list[str]:
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        # 문장 끝에서 자르기
        cut = max(text.rfind(". ", start, end), text.rfind("다. ", start, end))
        if end < len(text) and cut > start + size // 2:
            end = cut + 1
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def load(processed: Path | str = ROOT / "data" / "processed") -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(processed).glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        bank = BANKS[d["id"].split("_")[0]]
        base = dict(doc=d["id"], bank=bank, title=d["title"], version=d["effective"], layer=d["layer"])
        for u in d["units"]:
            if d["unit"] == "page":
                for i, w in enumerate(_windows(u["text"])):
                    chunks.append(Chunk(id=f"{d['id']}:p{u['page']}#{i}", text=w, page=u["page"], **base))
                continue
            if u.get("section", "본문") != "본문":
                continue  # 부칙은 검색 대상에서 뺀다
            paras = [p for p in u.get("paragraphs", []) if p.get("paragraph")]
            art_id = f"{d['id']}:{u['article']}"
            if not paras:
                chunks.append(Chunk(id=art_id, text=u["text"], article=u["article"],
                                    article_title=u.get("title"), page=u.get("page"), **base))
                continue
            ids = [f"{art_id}{p['paragraph']}" for p in paras]
            for p, cid in zip(paras, ids):
                chunks.append(Chunk(id=cid, text=p["text"], article=u["article"], article_title=u.get("title"),
                                    paragraph=p["paragraph"], page=u.get("page"),
                                    siblings=[x for x in ids if x != cid], **base))
    return chunks


def article_titles(chunks: list[Chunk]) -> dict[tuple[str, str], str]:
    """(doc, 조) → 조 제목"""
    return {(c.doc, c.article): c.article_title or "" for c in chunks if c.article}
