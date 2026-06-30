# syntax=docker/dockerfile:1
# 대시보드(FastAPI) 클라우드 이미지 — Fly.io용. DB는 Supabase(외부)라 여기엔 포함 안 함.
# 풀 배포: embeddings extra 포함 + bge-m3를 빌드타임에 캐시에 구워 런타임 오프라인으로 쓴다.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    HF_HOME=/app/.hf-cache \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) 의존성만 먼저(레이어 캐시). embeddings extra → sentence-transformers/torch 설치.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra embeddings --no-dev

# 2) 앱 소스 + 프로젝트 설치.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra embeddings --no-dev

# 3) bge-m3(~2GB)를 빌드타임에 HF_HOME 캐시로 다운로드. 빌더 환경엔 사내 TLS 가로채기가
#    없어 일반 HF 다운로드가 된다(런타임엔 네트워크 차단).
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# 런타임: 캐시만 사용, HF 허브 HEAD 요청 차단 — 미차단 시 CERTIFICATE_VERIFY_FAILED로 첫
# /chat이 500 (CLAUDE.md gotcha). 서버는 네트워크가 불필요(캐시만 쓰면 됨).
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
