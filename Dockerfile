FROM python:3.10-slim

WORKDIR /app

# 시스템 의존성 (curl: 공공데이터포털 호출 안정화)
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 소스 및 설정 복사
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Python 의존성 설치
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# 포트 노출 (기본값 8002)
EXPOSE 8002

# 환경 변수 기본값
ENV HOST=0.0.0.0
ENV PORT=8002
ENV TRANSPORT=streamable-http
ENV LOG_LEVEL=INFO
ENV MCP_SERVER_NAME=mcp-kr-g2b

# PUBLIC_DATA_API_KEY_ENCODED 는 런타임에 제공해야 함
#   docker run -e PUBLIC_DATA_API_KEY_ENCODED=... 또는 --env-file .env

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:${PORT}/mcp', timeout=5)" || exit 1

CMD ["python", "-c", "from mcp_kr_g2b.server import main; main()"]
