"""dedup 1차: 제목 SimHash 해밍거리 근접중복 군집 (STAGE1_DESIGN §6.2 1차).

2차(임베딩 cosine 확정 dedup)는 §11.3 임베딩 모델 결정 후 추가한다. 여기선
저비용 후보 군집만 만든다 (PAIN_POINT §1-3 "중복 기사 많음" 1차 해소).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

_TOKEN = re.compile(r"\w+", re.UNICODE)
_BITS = 64
_MASK = (1 << _BITS) - 1


def _tokens(title: str) -> list[str]:
    return _TOKEN.findall(title.lower())


def _hash_token(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def simhash(title: str) -> int:
    """제목 → 64비트 SimHash 지문. 토큰 없으면 0."""
    tokens = _tokens(title)
    if not tokens:
        return 0
    counts = [0] * _BITS
    for token in tokens:
        h = _hash_token(token)
        for i in range(_BITS):
            counts[i] += 1 if (h >> i) & 1 else -1
    fingerprint = 0
    for i in range(_BITS):
        if counts[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & _MASK).count("1")


def near_duplicate_groups(
    items: Iterable[tuple[int, str]], max_distance: int = 3
) -> list[list[int]]:
    """(doc_id, title) 시퀀스 → 근접중복 id 군집 리스트.

    해밍거리 max_distance 이하 쌍을 union-find로 묶는다. 단독 문서는 군집에서
    제외(반환은 크기 ≥ 2 군집만). 토큰 없는 제목은 짝짓기에서 빠진다(거짓 군집 방지).
    """
    pairs = [(doc_id, simhash(title)) for doc_id, title in items if _tokens(title)]
    parent = {doc_id: doc_id for doc_id, _ in pairs}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            if hamming(pairs[i][1], pairs[j][1]) <= max_distance:
                union(pairs[i][0], pairs[j][0])

    groups: dict[int, list[int]] = {}
    for doc_id, _ in pairs:
        groups.setdefault(find(doc_id), []).append(doc_id)
    return [g for g in groups.values() if len(g) > 1]
