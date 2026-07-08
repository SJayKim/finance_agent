"""애플리케이션 설정. Stage 0/§11 미결 값은 빈 채로 두고 config 경계로만 받는다
(STAGE1_DESIGN §2 규칙: 막힌 칸 하드코딩 금지)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 저장소
    database_url: str = "postgresql+psycopg://localhost/finance_agent"

    # 임베딩 (§6 권장 시작점: bge-m3, dim 1024, 로컬 다국어). 차원은 models.Vector(1024)와
    # 고정 일치 — 모델 교체로 차원이 바뀌면 마이그레이션+전체 재임베딩 필요. .env로 오버라이드 가능.
    embedding_model: str | None = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_device: str = "cpu"  # bge-m3 디바이스; GPU 있으면 "cuda"

    # 신선도 윈도우 (§5.7) — published_at 기준 필터. 시간 단위.
    freshness_window_hours: int = 24

    # §7 2-패스 Citations 분석 (Anthropic). 키 없으면 analyze_impact는 비활성 → brief_item
    # status=empty 유지(골격만). impact_model은 설계 §7 고정값(claude-opus-4-8).
    anthropic_api_key: str | None = None
    impact_model: str = "claude-opus-4-8"
    # OpenAI provider 키(플랜 11 게이트웨이). openai 용도 스위치가 켜졌을 때 사용.
    openai_api_key: str | None = None

    # LLM 게이트웨이 용도별 provider 스위치 (플랜 11). 기본값 조합 = 현행 동작(전부 anthropic,
    # 모델은 impact_model 폴백). provider별 키(anthropic_api_key/openai_api_key) 없으면 해당
    # 용도는 비활성(None) — 현행 키 게이트 의미 유지. .env + 재시작으로 전환.
    impact_provider: str = "anthropic"
    digest_provider: str = "anthropic"
    chat_provider: str = "anthropic"  # 날짜 챗 + 누적 RAG 챗 공통
    digest_model: str | None = None  # None → impact_model 폴백
    chat_model: str | None = None  # None → impact_model 폴백
    # 분석 루프 상한: 클러스터당 Opus 2-패스 ~8초 실측 × 150 ≈ 20분. 무상한 루프가 수집량
    # 증가(일 ~1,000건)에 선형 폭주해 Actions timeout → 전량 롤백된 사고 방지(2026-07-04).
    # 상한 밖은 status=empty로 남아 다음 실행이 이어서 분석. env로 오버라이드 가능(백필용).
    impact_analyze_max_clusters: int = 150

    # Dashboard Basic Auth. Protected routes fail closed unless both values are set.
    dashboard_username: str | None = None
    dashboard_password: str | None = None

    # 소스 API 키 (제공 전엔 빈 값. 커넥터는 키 없으면 비활성)
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    opendart_api_key: str | None = None
    sec_edgar_user_agent: str | None = None
    openfigi_api_key: str | None = None  # §5.6 — 없으면 무료 한도(25 req/min), 있으면 상향
    coingecko_api_key: str | None = None
    marketaux_api_key: str | None = None
    finnhub_api_key: str | None = None


settings = Settings()
