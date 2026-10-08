"""조항 검색: 한글 2글자 단위(bigram) BM25 + 용어 사전.

벡터 DB를 쓰지 않는다. 문서가 11개, 조각이 수백 개라 이 정도로 충분하고,
왜 그 조항이 나왔는지 사람이 따라가 볼 수 있다.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .corpus import Chunk

# 사용자가 쓰는 말 → 약관이 쓰는 말
SYNONYMS = {
    "중도상환수수료": ["중도상환해약금"],
    "중도상환": ["중도상환해약금", "기한전의 임의 상환"],
    "미리 갚": ["중도상환", "기한전의 임의 상환"],
    "연체이자": ["지연배상금", "연체이율", "연체금리"],
    "연체": ["지연배상금", "지체", "연체가산금리"],
    "늦게": ["지체", "연체"],
    "한꺼번에": ["기한의 이익", "기한이익상실"],
    "마이너스통장": ["한도대출", "한도거래"],
    "신용점수": ["신용평점", "개인신용평점", "신용등급"],
    "자동으로 연장": ["기한연장", "기한 연장"],
    "연장": ["기한연장", "기한 연장", "만기연장"],
    "만기": ["대출기간 종료일", "약정기일"],
    "취소": ["철회"],
    "마음이 바뀌": ["철회"],
    "금리를 낮춰": ["금리인하요구", "금리변경을 요구"],
    "금리": ["대출금리", "이율"],
    "약관을 바꾸": ["약관 변경", "약관등을 변경"],
    "공휴일": ["휴일", "영업일"],
    "채무조정": ["채무조정"],
    "1억": ["1억원을 초과"],
    "실행": ["대출을 실행하지"],
    "우대": ["금리 우대", "우대금리"],
    "고정금리": ["고정금리"],
    "변동금리": ["변동금리", "기준금리", "금리변동주기"],
}

BANK_ALIASES = {"토스뱅크": ["토스"], "카카오뱅크": ["카카오"], "하나은행": ["하나"]}

_TOKEN = re.compile(r"[가-힣]+|[A-Za-z]+|\d+")


def tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN.findall(text):
        if re.match(r"[가-힣]", t):
            out += [t[i:i + 2] for i in range(len(t) - 1)] or [t]
        else:
            out.append(t.lower())
    return out


def detect_banks(question: str) -> list[str]:
    found = [b for b, al in BANK_ALIASES.items() if b in question or any(a in question for a in al)]
    return found


def expand(question: str) -> str:
    extra = [s for k, v in SYNONYMS.items() if k in question for s in v]
    return question + " " + " ".join(extra)


class Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.2, b: float = 0.75):
        self.chunks = chunks
        self.by_id = {c.id: c for c in chunks}
        self.k1, self.b = k1, b
        # 조 제목은 두 번 넣어 가중치를 준다
        self.docs = [Counter(tokens(((c.article_title or "") + " ") * 2 + c.text)) for c in chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lens) / len(self.lens)
        df = Counter(t for d in self.docs for t in d)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, q: Counter, i: int) -> float:
        d, L, s = self.docs[i], self.lens[i], 0.0
        for t, qf in q.items():
            f = d.get(t)
            if f:
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * L / self.avg))
        return s

    def search(self, question: str, banks: list[str] | None = None, k: int = 8) -> list[tuple[Chunk, float]]:
        q = Counter(tokens(expand(question)))
        banks = banks or detect_banks(question)
        scored = []
        for i, c in enumerate(self.chunks):
            if banks and c.bank not in banks:
                continue
            s = self.score(q, i)
            if s > 0:
                scored.append((c, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    def with_siblings(self, hits: list[Chunk]) -> list[Chunk]:
        """찾은 항과 같은 조의 다른 항도 붙인다. 예외는 대개 같은 조의 다른 항이나 단서에 있다."""
        out, seen = [], set()
        for c in hits:
            for cid in [c.id] + c.siblings:
                if cid not in seen:
                    seen.add(cid)
                    out.append(self.by_id[cid])
        return out
