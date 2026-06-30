# 00. 시스템 전체 개요

## 한 줄 요약

이 프로젝트는 여러 뉴스/공시 소스를 매일 수집하고, 중복 제거와 근거 기반 AI 분석을 거쳐 대시보드와 채팅에서 볼 수 있는 "뉴스/공시 기반 영향 분석"을 만든다.

## 비개발자 설명

시스템은 매일 아침 여러 외부 소스에서 문서를 가져온다. 가져온 문서는 먼저 공통 형식으로 저장되고, 비슷한 문서끼리 묶인 뒤, 실제 문서에서 인용 가능한 근거가 있을 때만 영향 분석 결과로 바뀐다.

최종 화면은 크게 세 가지를 보여준다.

- 오늘 어떤 소스가 정상 수집됐는지
- 오늘의 핵심 흐름을 요약한 일일 다이제스트
- 개별 뉴스/공시가 어떤 종목이나 자산군에 영향을 줄 수 있는지와 그 근거

이 문서는 투자 추천을 설명하지 않는다. 코드는 "매수/매도 판단"이 아니라, 수집된 뉴스와 공시 근거 안에서 영향 가능성을 정리하는 구조로 되어 있다.

## 설계도

```mermaid
flowchart TD
    User[사용자] --> FastAPI[FastAPI 화면/API]
    Scheduler[Windows 작업 스케줄러] --> Runner[일일 실행기]
    FastAPI --> Trigger[/trigger: 분석만 실행]
    FastAPI --> Daily[/run-daily: 수집 포함 실행]
    Daily --> Runner
    Runner --> Collectors[수집 커넥터]
    Collectors --> Raw[(raw_documents)]
    Trigger --> Pipeline[분석 파이프라인]
    Runner --> Pipeline
    Raw --> Pipeline
    Pipeline --> Clusters[(clusters)]
    Pipeline --> Briefs[(brief_items)]
    Pipeline --> Citations[(citations)]
    Pipeline --> Tickers[(brief_item_tickers)]
    Pipeline --> Embeddings[(RawDocument.embedding)]
    Runner --> Digest[일일 다이제스트 생성]
    Briefs --> Dashboard[대시보드]
    Digest --> Dashboard
    Citations --> Chat[근거 기반 채팅]
    Embeddings --> Chat
```

### 다이어그램 코드 매핑

| 설계도 박스 | 담당 코드 |
| --- | --- |
| `FastAPI 화면/API` | [`app/main.py`](../../app/main.py) |
| `/trigger` | `app/main.py::trigger`, `app.pipeline.pipeline::run_pipeline` |
| `/run-daily` | `app/main.py::run_daily_endpoint`, `app.runner::run_daily` |
| `일일 실행기` | [`app/runner.py`](../../app/runner.py) |
| `수집 커넥터` | [`app/collector/base.py`](../../app/collector/base.py), `app/collector/*.py` |
| `raw_documents` 등 DB 저장소 | [`app/models.py`](../../app/models.py) |
| `분석 파이프라인` | [`app/pipeline/pipeline.py`](../../app/pipeline/pipeline.py) |
| `일일 다이제스트 생성` | [`app/pipeline/digest.py`](../../app/pipeline/digest.py) |
| `대시보드` | `app/main.py::dashboard`, [`app/web/queries.py`](../../app/web/queries.py), `app/web/templates/*.html` |
| `근거 기반 채팅` | `app/main.py::chat`, [`app/web/chat.py`](../../app/web/chat.py) |

## 코드/폴더 매핑

| 영역 | 역할 |
| --- | --- |
| [`app/main.py`](../../app/main.py) | FastAPI 앱, `/health`, `/trigger`, `/run-daily`, `/`, `/chat` 라우트 |
| [`app/runner.py`](../../app/runner.py) | 매일 한 번 실행되는 전체 작업. 수집, 분석, 임베딩, 다이제스트를 순서대로 호출 |
| [`app/collector/`](../../app/collector) | RSS, Naver, OpenDART, EDGAR, Marketaux, Finnhub 수집기 |
| [`app/pipeline/`](../../app/pipeline) | 중복 제거, 클러스터링, AI 분석, 종목 연결, 임베딩, 다이제스트 |
| [`app/web/`](../../app/web) | 화면 조회용 쿼리, 채팅 분석, HTML 템플릿, CSS |
| [`app/models.py`](../../app/models.py) | SQLAlchemy ORM 모델. 업무 데이터가 어떤 테이블로 저장되는지 정의 |
| [`migrations/versions/`](../../migrations/versions) | 실제 DB 스키마 변경 이력 |
| [`tests/`](../../tests) | 수집기, 파이프라인, 다이제스트, RAG 채팅, 화면 검증 테스트 |

## 왜 이렇게 만들었나

하나의 큰 AI 호출로 모든 것을 처리하지 않고, 수집, 정규화, 중복 제거, 분석, 종목 연결, 화면 조회를 나눈다. 이렇게 하면 어느 단계에서 문제가 생겼는지 알기 쉽고, 외부 API 하나가 실패해도 전체 시스템이 멈추지 않게 만들 수 있다.

DB가 중심 저장소다. 수집 원문, 분석 결과, 인용 근거, 다이제스트, 실행 로그가 모두 테이블로 남기 때문에 화면과 채팅은 같은 근거를 다시 조회해 보여줄 수 있다.

## 관련 테스트

| 테스트 파일 | 막는 사고 |
| --- | --- |
| [`tests/test_runner.py`](../../tests/test_runner.py) | 일일 실행이 수집기 실패를 격리하고 중복 실행을 막는지 검증 |
| [`tests/test_pipeline.py`](../../tests/test_pipeline.py) | 문서가 클러스터와 브리프 결과로 안정적으로 바뀌는지 검증 |
| [`tests/test_digest.py`](../../tests/test_digest.py) | 근거 없는 다이제스트를 만들지 않는지 검증 |
| [`tests/test_web.py`](../../tests/test_web.py) | 대시보드와 날짜/채팅 화면이 필요한 데이터를 보여주는지 검증 |
| [`tests/test_rag_chat.py`](../../tests/test_rag_chat.py) | 누적 근거 검색 기반 채팅이 근거 없이 답하지 않는지 검증 |

## 다음에 읽을 문서

1. [01. 데이터 수집 구조](./01-data-collection.md)
2. [02. 일일 실행과 트리거](./02-daily-run-and-trigger.md)
3. [03. 영향 분석 파이프라인](./03-impact-pipeline.md)
