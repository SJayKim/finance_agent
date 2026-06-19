"""애플리케이션 설정. Stage 0/§11 미결 값은 빈 채로 두고 config 경계로만 받는다
(STAGE1_DESIGN §2 규칙: 막힌 칸 하드코딩 금지)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 저장소
    database_url: str = "postgresql+psycopg://localhost/finance_agent"

    # 임베딩 (§11.3 OPEN — 모델/차원 미정. 인터페이스 경계로만 노출, 확정 전 빈 값)
    embedding_model: str | None = None
    embedding_dim: int | None = None

    # 신선도 윈도우 (§5.7) — published_at 기준 필터. 시간 단위.
    freshness_window_hours: int = 24

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
