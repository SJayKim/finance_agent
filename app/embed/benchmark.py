"""§6 임베딩 모델 결정 지원 하니스 (STAGE1.5_DESIGN §6 게이트).

§6은 "추측 금지 — 실측 후 bge-m3 확정/교체"를 요구한다. 이 스크립트가 그 표를 채우는
산출물이다: KR 헤드라인 라벨셋에 대한 (1) dedup precision/recall 임계 스윕, (2) 검색
recall@k. 수학은 순수 stdlib(정규화 벡터의 내적 = 코사인 유사도) — numpy 없음.

    python -m app.embed.benchmark

내장 KR 샘플은 스크립트가 즉시 돌게 하는 최소 예시일 뿐이다. 운영 모델 결정은 실제
라벨셋(애널리스트 검수 헤드라인 중복쌍 + 질의/정답 세트)으로 이 표를 다시 채워야
한다. __main__은 get_embedder()(실 모델)로 두 측정을 돌려 표를 출력한다. 모델이 없으면
설치 안내 후 exit 0.
"""

from __future__ import annotations

import sys

from app.embed import Embedder, get_embedder

# 내장 KR 샘플 — 즉시 실행용 최소 예시(운영 결정엔 실 라벨셋 필요, 모듈 docstring 참조).
_LABELED_PAIRS: list[tuple[str, str, bool]] = [
    ("삼성전자, 2분기 영업이익 어닝 서프라이즈", "삼성전자 2분기 영업익 시장 기대 상회", True),
    ("한국은행 기준금리 동결 결정", "한은, 기준금리 3.50% 동결", True),
    ("비트코인 1억원 돌파", "비트코인 사상 첫 1억원 돌파", True),
    ("삼성전자 2분기 어닝 서프라이즈", "현대차 신형 전기차 출시 발표", False),
    ("한국은행 기준금리 동결", "비트코인 1억원 돌파", False),
    ("SK하이닉스 HBM 공급 확대", "엔비디아 신규 GPU 공개", False),
]

# (질의, [정답 텍스트들], 코퍼스). recall@k 측정용.
_QUERY_SETS: list[tuple[str, list[str], list[str]]] = [
    (
        "반도체 실적",
        ["삼성전자 2분기 영업익 시장 기대 상회", "SK하이닉스 HBM 공급 확대"],
        [
            "삼성전자 2분기 영업익 시장 기대 상회",
            "SK하이닉스 HBM 공급 확대",
            "한은, 기준금리 3.50% 동결",
            "비트코인 사상 첫 1억원 돌파",
            "현대차 신형 전기차 출시 발표",
        ],
    ),
    (
        "암호화폐 가격",
        ["비트코인 사상 첫 1억원 돌파"],
        [
            "비트코인 사상 첫 1억원 돌파",
            "삼성전자 2분기 영업익 시장 기대 상회",
            "한은, 기준금리 3.50% 동결",
        ],
    ),
]


def _cosine(a: list[float], b: list[float]) -> float:
    """정규화 벡터 가정 — 코사인 = 내적(순수 stdlib)."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def dedup_precision_recall(
    embedder: Embedder, labeled_pairs: list[tuple[str, str, bool]]
) -> list[tuple[float, float, float]]:
    """라벨 쌍에 임계 스윕 → [(threshold, precision, recall)]. cosine ≥ threshold면 중복 예측."""
    sims: list[tuple[float, bool]] = []
    for a, b, is_dup in labeled_pairs:
        va, vb = embedder.embed([a, b])
        sims.append((_cosine(va, vb), is_dup))
    total_dup = sum(1 for _s, d in sims if d)
    out: list[tuple[float, float, float]] = []
    for step in range(2, 10):  # 0.2 .. 0.9
        threshold = step / 10
        tp = sum(1 for s, d in sims if s >= threshold and d)
        fp = sum(1 for s, d in sims if s >= threshold and not d)
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / total_dup if total_dup else 1.0
        out.append((threshold, precision, recall))
    return out


def recall_at_k(
    embedder: Embedder, queries: list[tuple[str, list[str], list[str]]]
) -> dict[int, float]:
    """질의별 코사인 랭킹 → k∈(1,3,5) 평균 recall@k."""
    ks = (1, 3, 5)
    totals = {k: 0.0 for k in ks}
    for query, relevant, corpus in queries:
        qv = embedder.embed([query])[0]
        cvs = embedder.embed(corpus)
        ranked = sorted(corpus, key=lambda c: _cosine(qv, cvs[corpus.index(c)]), reverse=True)
        rel = set(relevant)
        for k in ks:
            hits = sum(1 for c in ranked[:k] if c in rel)
            totals[k] += hits / len(rel) if rel else 1.0
    n = len(queries) or 1
    return {k: totals[k] / n for k in ks}


def main() -> int:
    embedder = get_embedder()
    if embedder is None:
        print("임베딩 모델 미사용 — 설치: uv sync --extra embeddings")
        return 0
    print("== dedup precision/recall (임계 스윕) ==")
    print(f"{'threshold':>10} {'precision':>10} {'recall':>10}")
    for threshold, precision, recall in dedup_precision_recall(embedder, _LABELED_PAIRS):
        print(f"{threshold:>10.1f} {precision:>10.3f} {recall:>10.3f}")
    print("\n== recall@k ==")
    for k, value in recall_at_k(embedder, _QUERY_SETS).items():
        print(f"recall@{k}: {value:.3f}")
    print("\n주의: 내장 샘플은 최소 예시. 운영 결정은 실 라벨셋으로 이 표를 다시 채울 것(§6).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
