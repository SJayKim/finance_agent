# 03 — 일일 자동 실행 스케줄 산출물 (blocker 6)

## Context
`run_daily`·`POST /run-daily`·CLI(`python -m app.runner`)는 동작하지만, **매일 06:40 KST 호출이 `docs/STAGE1.5_OPERATIONS.md`의 수동 안내(schtasks/cron)뿐**이라 "자동"이 미달성이다. 리포에 스케줄러 산출물(scripts/·.github·*.service·compose)이 전무하다(감사 확인). 스케줄 등록을 **체크인된 산출물**로 만들어 재현 가능하게 한다.

근거(탐색 확인):
- `docs/STAGE1.5_OPERATIONS.md:22-33` Windows schtasks 명령(06:40, `>> logs\daily.log 2>&1`), `:36-43` Linux cron 2종(KST 06:40 = UTC 21:40, DST 없음).
- CLI: `app/runner.py:237` `main()` — `--date YYYY-MM-DD`(기본 오늘 KST), 종료코드 0/1(`DailyRunAlreadyRunning`).
- `logs/` 디렉터리 부재 — 가이드가 가리키는 `logs/daily.log` 대상 없음.

## 변경

### 1. `scripts/schedule_daily.cmd` (신규, Windows)
schtasks로 `finance_agent_daily` 작업 등록(매일 06:40 로컬TZ): `uv run python -m app.runner >> logs\daily.log 2>&1`. 프로젝트 경로는 스크립트 위치 기준으로 도출(하드코딩 회피). `OPERATIONS.md:22-33`을 스크립트화.

### 2. `scripts/crontab.example` (신규, Linux/VM)
KST/UTC 두 줄(`OPERATIONS.md:36-43`). **TZ 주의 주석**: `brief_date`·신선도 컷오프가 KST 기준이므로 cron 서버 TZ를 명시(UTC 서버는 21:40).

### 3. `logs/.gitkeep` (신규) + `.gitignore`
`logs/` 디렉터리를 보존하되 내용은 제외(`.gitignore`에 `logs/` 추가). 스케줄 가이드의 `logs/daily.log` append 대상 확보.

### 4. `docs/STAGE1.5_OPERATIONS.md` (갱신)
수동 명령 나열 대신 `scripts/` 산출물 실행을 가리키도록 갱신(수동 명령은 참고로 유지).

## 영향 파일
- `scripts/schedule_daily.cmd` (신규)
- `scripts/crontab.example` (신규)
- `logs/.gitkeep` (신규)
- `.gitignore` (`logs/` 추가)
- `docs/STAGE1.5_OPERATIONS.md` (참조 갱신)

## 검증
- `scripts/schedule_daily.cmd` 실행 → `schtasks /Query /TN finance_agent_daily` 등록 확인 → `schtasks /Run /TN finance_agent_daily` → `logs/daily.log`에 run_daily 출력 append 확인.
- **주의: 실제 OS 작업 등록은 부수효과** — 실행 단계에서 사용자 확인 후 진행.

## 스코프 밖
무인 배포(Docker/compose/호스팅), 실패 능동 알림은 별건(nice-to-have). 본 문서는 스케줄 등록 산출물 + 로그 경로 확보까지.
