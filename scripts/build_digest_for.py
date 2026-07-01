"""특정일 다이제스트만 재생성(신규 수집 없음). docs/plans/05 Step 3.

build_digest는 그날 status=ok brief_items + citations만 입력으로 본다(수집·클러스터링
없음) → 과거 날짜를 오염 없이 집계만 한다.
"""

import argparse
import sys
from datetime import date

from app.config import settings
from app.db import SessionLocal
from app.pipeline.citations import build_client
from app.pipeline.digest import anthropic_digester, build_digest


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="특정일 다이제스트만 재생성(수집 없음)")
    parser.add_argument("--date", required=True, help="대상 brief_date YYYY-MM-DD")
    brief_date = date.fromisoformat(parser.parse_args().date)
    assert settings.anthropic_api_key, "ANTHROPIC_API_KEY 미설정"
    digester = anthropic_digester(build_client(settings.anthropic_api_key), settings.impact_model)
    with SessionLocal() as session:
        build_digest(session, brief_date, digester=digester)
        session.commit()
    print(f"digest built for {brief_date.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
