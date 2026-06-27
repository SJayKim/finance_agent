# finance-agent

증권사 애널리스트를 위한 금융 리서치 가속 도구입니다. 뉴스, 공시, 크립토/시장 데이터를 수집하고 dedup, 클러스터링, 티커 링킹, 영향도 분석을 거쳐 출처 기반 일일 브리프와 대시보드를 제공합니다.

## 주요 기능

- RSS, Naver News, OpenDART, SEC EDGAR, Marketaux, Finnhub 기반 데이터 수집
- 중복 제거, 이벤트 클러스터링, 영향도 분석, 티커 링킹 파이프라인
- 일일 다이제스트와 출처 추적 가능한 브리프 생성
- FastAPI/Jinja 기반 웹 대시보드 및 근거 기반 채팅
- GitHub Actions 또는 로컬 스케줄러로 매일 06:40 KST 실행

## 기술 스택

- Python 3.13
- FastAPI, Jinja2
- SQLAlchemy, Alembic
- PostgreSQL + pgvector
- uv
- pytest, ruff, mypy

## 시작하기

```powershell
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

대시보드는 기본적으로 `http://127.0.0.1:8000`에서 확인할 수 있습니다.

## 환경 변수

`.env` 파일 또는 실행 환경에 다음 값을 설정합니다. 키가 없는 외부 소스는 격리되어 건너뛰며, 가능한 범위에서 degraded 상태로 실행됩니다.

| 변수 | 설명 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL + pgvector 접속 문자열 |
| `ANTHROPIC_API_KEY` | 영향도 분석, 다이제스트, 채팅 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | Naver News 수집 |
| `OPENDART_API_KEY` | OpenDART 공시 수집 |
| `SEC_EDGAR_USER_AGENT` | SEC EDGAR 수집 |
| `OPENFIGI_API_KEY` | 티커/식별자 보강 |
| `COINGECKO_API_KEY` | 크립토 데이터 |
| `MARKETAUX_API_KEY` | Marketaux 뉴스 |
| `FINNHUB_API_KEY` | Finnhub 뉴스 |

## 일일 실행

로컬에서 수동 실행:

```powershell
uv run python -m app.runner
```

특정 날짜 재실행:

```powershell
uv run python -m app.runner --date 2026-06-22
```

Windows 작업 스케줄러 등록:

```cmd
scripts\schedule_daily.cmd
```

GitHub Actions 일일 실행은 `.github/workflows/daily.yml`에 정의되어 있으며, `DATABASE_URL` 등 필요한 값을 repository secrets로 주입합니다.

## 테스트와 품질 검사

```powershell
uv run pytest
uv run ruff check .
uv run mypy .
```

## 참고 문서

- `DESIGN.md`: 제품 방향과 설계 배경
- `docs/STAGE1.5_OPERATIONS.md`: 일일 실행 및 운영 방법
- `docs/`: 단계별 설계, UI, 운영 문서
