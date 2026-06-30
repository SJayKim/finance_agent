# Stage 1.5 운영 — 일일 실행 스케줄링

상위 문서: `STAGE1.5_DESIGN.md` (§3 스케줄, §4 트랙 B). 이 문서는 일일 오케스트레이션
(`app/runner.py`)을 실제로 매일 돌리는 법이다.

## 무엇이 도는가

`run_daily`(= `python -m app.runner`)는 한 번 호출로 **순차 실행**한다:

1. 모든 커넥터 수집(fetch→normalize→upsert) — 소스 격리(한 소스 장애가 나머지를 안 막음)
2. `run_pipeline` (dedup→cluster→generate_impact→analyze_impact→ticker_link→embed)
3. `build_digest` (그날 brief_items → 거시·섹터 다이제스트)

설계 §3은 "수집 ~06:40 KST → 다이제스트 ~07:00"인데, run_daily가 1·2·3을 한 호출에서
직렬로 끝내므로 **06:40 KST 단일 잡 하나면 충분**하다 — 수집·파이프라인이 끝나면
다이제스트가 자연히 ~07:00에 떨어진다.

동시성 가드: run_daily는 `_DAILY_LOCK_KEY`(pg advisory lock)를 잡는다. 이미 도는
인스턴스가 있으면 즉시 거절한다(중복 실행 방지). 온디맨드는 `POST /run-daily`로도 가능
(409면 이미 실행 중).

스케줄 산출물은 리포에 체크인돼 있다(`scripts/`) — 수동 명령을 옮겨 적지 말고 이걸 실행하라.
로그 경로 `logs/`는 `.gitkeep`으로 보존되고 내용은 `.gitignore` 처리된다.

## Windows 작업 스케줄러

```cmd
scripts\schedule_daily.cmd
```

- `scripts\schedule_daily.cmd` — `finance_agent_daily` 작업을 매일 06:40(OS 로컬 TZ; PC가
  KST면 06:40 KST)에 등록한다. 경로는 스크립트 위치 기준으로 도출(하드코딩 없음). 작업은
  잡 본체 `scripts\run_daily.cmd`(cd → `uv run python -m app.runner` → `logs\daily.log` append)를
  호출한다 — schtasks `/TR`에 리다이렉션을 넣지 않아 따옴표 깨짐이 없다.
- 수동 1회 실행/검증: `schtasks /Run /TN finance_agent_daily` (또는 `scripts\run_daily.cmd` 직접).
- 등록 해제: `schtasks /Delete /TN finance_agent_daily /F`.
- 특정 날짜 재실행: `uv run python -m app.runner --date 2026-06-22`.

> 참고(스크립트 없이 한 줄로): `schtasks /Create /TN finance_agent_daily /SC DAILY /ST 06:40 /F /TR "cmd /c \"<repo>\scripts\run_daily.cmd\""`

## Linux/VM cron

```sh
crontab scripts/crontab.example   # 또는: crontab -e 후 해당 줄 복사
```

`scripts/crontab.example`에 두 줄(KST 서버용 / UTC 서버용)이 들어 있다. cron은 **서버 TZ**를
쓰는데 brief_date는 항상 KST 기준일로 계산되므로(`_KST`), 서버 TZ에 맞는 줄 하나만 활성화한다
(KST=UTC+9, DST 없음 → UTC 서버는 전날 21:40). 종료코드: 정상 0, 다른 일일 실행 진행 중이면 비0.

## 필요한 환경변수 (.env)

소스별 키. **키 없는 소스는 소스 격리로 건너뛰고 실행은 degraded로 성공한다**(전부 막히지 않음).

| 키 | 소스 | 없으면 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | §7 분석·다이제스트 | brief_item status=empty, 다이제스트 degraded |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 네이버 뉴스 | naver 소스 error(격리) |
| `OPENDART_API_KEY` | DART 공시 본문 | opendart_docs 소스 error(격리) |
| `SEC_EDGAR_USER_AGENT` | SEC EDGAR 본문 | edgar_docs 소스 error(격리) |
| `MARKETAUX_API_KEY` | Marketaux 코인 뉴스 | marketaux 소스 error(격리) |
| `FINNHUB_API_KEY` | Finnhub 코인 뉴스 | finnhub 소스 error(격리) |

RSS(크립토·KR 경제지·글로벌 매크로)는 키 불필요 — 키가 하나도 없어도 RSS만으로 매일 돈다.

## 알려진 갭

- **EDGAR CIK 유니버스 미공급.** `build_default_connectors`의 `EdgarDocsConnector(ciks=[])`는
  원칙적 placeholder다(§2: 유니버스를 코드에 박지 않는다). CIK 유니버스가 DB/coverage에서
  공급되기 전까지 edgar는 문서를 가져오지 않는다(UA가 있으면 no-op, 없으면 error로 격리).
  무작위 CIK를 지어내지 않는다.
- **임베딩은 opt-in.** RAG 검색의 재료인 임베딩을 채우려면 `uv sync --extra embeddings`로
  sentence-transformers를 설치해야 한다. 미설치면 `get_embedder()`가 None → embed 단계가
  no-op(파이프라인은 정상, RAG 코퍼스만 안 쌓임). 첫 실행 시 bge-m3(~2GB)를 로드한다.
