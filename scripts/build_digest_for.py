"""특정일 다이제스트만 재생성(신규 수집 없음).

build_digest는 그날 status=ok brief_items + citations만 입력으로 본다(수집·클러스터링
없음) → 과거 날짜를 오염 없이 집계만 한다.
"""

import argparse
import sys
from datetime import date

from app.db import SessionLocal
from app.llm.factory import make_digester
from app.pipeline.digest import build_digest


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="특정일 다이제스트만 재생성(수집 없음)")
    parser.add_argument("--date", required=True, help="대상 brief_date YYYY-MM-DD")
    brief_date = date.fromisoformat(parser.parse_args().date)
    digester = make_digester()
    assert digester is not None, "digest provider 키 미설정 (DIGEST_PROVIDER·해당 키 확인)"
    with SessionLocal() as session:
        build_digest(session, brief_date, digester=digester)
        session.commit()
    print(f"digest built for {brief_date.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
