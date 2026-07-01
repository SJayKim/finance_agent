"""키 유효성 라이브 검증 (docs/plans/05 Step 1).

build_default_connectors()로 만든 6개 커넥터를 각각 fetch() 1회 라이브 호출하고
예외를 분류한다. 적재(upsert)는 하지 않는다 — 키가 살아있는지만 본다.

판정:
  ok        정상 응답(또는 edgar처럼 ciks=[] no-op)
  미설정     키 미로드(설정 문제) — 커넥터 자체 Error
  무효키     401/403 — 키 교체 필요
  쿼터       429
  네트워크   Connect/Timeout/TLS
  기타       위에 안 맞는 예외
"""

import sys

import httpx

from app.runner import build_default_connectors


def classify(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "무효키", f"HTTP {code}"
        if code == 429:
            return "쿼터", f"HTTP {code}"
        return "기타", f"HTTP {code}"
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return "네트워크", type(exc).__name__
    name = type(exc).__name__
    if "미설정" in str(exc):
        return "미설정", str(exc)[:120]
    return "기타", f"{name}: {str(exc)[:120]}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(f"{'source':<14} {'verdict':<8} detail")
    print("-" * 60)
    for name, connector in build_default_connectors():
        try:
            count = 0
            for _payload in connector.fetch():
                count += 1
                break  # 1건이면 라이브 호출이 성공한 것 — 더 안 끌어온다
            verdict, detail = "ok", f"{count} item(s) pulled"
        except Exception as exc:  # noqa: BLE001
            verdict, detail = classify(exc)
        print(f"{name:<14} {verdict:<8} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
