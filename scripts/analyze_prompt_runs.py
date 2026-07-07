"""프롬프트 버전 런 덤프 비교 — 기준(Opus) vs 후보 N개 (읽기 전용, DB 불필요. 플랜 10).

실행: uv run python -m scripts.analyze_prompt_runs --baseline DIR --candidates DIR1,DIR2,...
  [--probes 1256,1009]

각 디렉터리는 compare_providers.py --dump-dir 산출물(<dir>/<provider>/<id>.json).
공유 ok-set(기준·후보 모두 status=ok인 brief_item_id 교집합) 기준으로:
- pairwise 오프셋(후보-기준) 평균/중앙값/최소/최대 — 런 간 평균 비교보다 강건(플랜 08 방법)
- 점수 stddev(기준 대비 — 분별력 붕괴 가드: 전부 25~35로 눌러 오프셋만 "해결"하는 버전 탐지)
- confidence 분포 L1 거리(정규화 HIGH/MED/LOW, 0=동일 ~ 2=완전 불일치)
- 프로브 아이템(기본 1256·1009) 점수/confidence/direction 나란히 비교

마지막에 docs/plans/10 전사용 markdown 행도 출력한다.
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_CONF_KEYS = ("HIGH", "MED", "LOW")


def load_dump(dump_dir: Path) -> dict[int, dict[str, Any]]:
    """<dump_dir>/<provider>/<id>.json 전부 적재. summary.json은 제외."""
    items: dict[int, dict[str, Any]] = {}
    for path in dump_dir.glob("*/*.json"):
        if path.name == "summary.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        items[int(payload["brief_item_id"])] = payload
    if not items:
        raise FileNotFoundError(f"덤프 없음: {dump_dir} (컨벤션: <dir>/<provider>/<id>.json)")
    return items


def _conf_l1(base: list[dict[str, Any]], cand: list[dict[str, Any]]) -> float:
    """정규화 confidence 분포의 L1 거리."""

    def dist(items: list[dict[str, Any]]) -> dict[str, float]:
        counts = Counter(i.get("confidence") for i in items)
        total = sum(counts.get(k, 0) for k in _CONF_KEYS) or 1
        return {k: counts.get(k, 0) / total for k in _CONF_KEYS}

    b, c = dist(base), dist(cand)
    return round(sum(abs(c[k] - b[k]) for k in _CONF_KEYS), 3)


def compare(
    baseline: dict[int, dict[str, Any]], candidate: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """공유 ok-set 기준 비교 메트릭(순수)."""
    shared = [
        i
        for i in sorted(baseline.keys() & candidate.keys())
        if baseline[i]["status"] == "ok"
        and candidate[i]["status"] == "ok"
        and baseline[i]["impact_score"] is not None
        and candidate[i]["impact_score"] is not None
    ]
    if not shared:
        return {"shared_ok": 0}
    offsets = [candidate[i]["impact_score"] - baseline[i]["impact_score"] for i in shared]
    base_scores = [baseline[i]["impact_score"] for i in shared]
    cand_scores = [candidate[i]["impact_score"] for i in shared]
    base_items = [baseline[i] for i in shared]
    cand_items = [candidate[i] for i in shared]
    return {
        "shared_ok": len(shared),
        "offset_mean": round(statistics.mean(offsets), 1),
        "offset_median": statistics.median(offsets),
        "offset_min": min(offsets),
        "offset_max": max(offsets),
        "stddev_base": round(statistics.pstdev(base_scores), 1),
        "stddev_cand": round(statistics.pstdev(cand_scores), 1),
        "conf_l1": _conf_l1(base_items, cand_items),
        "confidence": dict(Counter(i.get("confidence") for i in cand_items)),
    }


def _probe_row(items: dict[int, dict[str, Any]], probe_id: int) -> str:
    item = items.get(probe_id)
    if item is None:
        return "미포함"
    if item["status"] != "ok":
        return f"status={item['status']}"
    return f"{item['impact_score']}/{item['confidence']}/{item['direction']}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="프롬프트 버전 런 덤프 비교(플랜 10)")
    parser.add_argument("--baseline", required=True, help="기준 덤프 디렉터리(Opus v0)")
    parser.add_argument("--candidates", required=True, help="후보 덤프 디렉터리들(쉼표 구분)")
    parser.add_argument("--probes", default="1256,1009", help="프로브 brief_item id(쉼표 구분)")
    args = parser.parse_args()

    baseline = load_dump(Path(args.baseline))
    probes = [int(x) for x in args.probes.split(",") if x.strip()]
    md_rows: list[str] = []
    for cand_dir in [Path(p.strip()) for p in args.candidates.split(",") if p.strip()]:
        candidate = load_dump(cand_dir)
        m = compare(baseline, candidate)
        print(f"\n=== {cand_dir.name} (vs {Path(args.baseline).name}) ===")
        for key, value in m.items():
            print(f"  {key}: {value}")
        for probe_id in probes:
            print(
                f"  probe {probe_id}: base {_probe_row(baseline, probe_id)}"
                f" → cand {_probe_row(candidate, probe_id)}"
            )
        if m.get("shared_ok"):
            probe_cells = " / ".join(_probe_row(candidate, p) for p in probes)
            md_rows.append(
                f"| {cand_dir.name} | {m['shared_ok']} | {m['offset_mean']}"
                f" | {m['offset_median']} | {m['stddev_cand']} (기준 {m['stddev_base']})"
                f" | {m['conf_l1']} | {m['confidence']} | {probe_cells} |"
            )

    print("\n--- docs/plans/10 전사용 markdown ---")
    print("| 런 | 공유ok | 오프셋평균 | 오프셋중앙 | stddev | confL1 | confidence | 프로브 |")
    print("|---|---|---|---|---|---|---|---|")
    for row in md_rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
