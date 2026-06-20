"""
환경변수 및 설정 관리

조달청 나라장터/누리장터 OpenAPI는 공공데이터포털(data.go.kr)을 통해 제공됩니다.
따라서 인증키는 공공데이터포털에서 발급받은 서비스키(Encoding 키)를 사용합니다.
"""

import os
import logging
from typing import Literal, Optional, cast
from dataclasses import dataclass

from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

logger = logging.getLogger(__name__)

_ALLOWED_TRANSPORTS = {"stdio", "streamable-http", "sse", "http"}


def _int_env(name: str, default: int) -> int:
    """정수 환경변수를 안전하게 파싱(실패 시 기본값 + 경고). import 실패 방지."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning(f"환경변수 {name}='{raw}' 정수 변환 실패 → 기본값 {default} 사용")
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning(f"환경변수 {name}='{raw}' 실수 변환 실패 → 기본값 {default} 사용")
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass
class G2BConfig:
    """조달청 나라장터 OpenAPI configuration."""

    api_key: str
    base_host: str = "http://apis.data.go.kr/1230000"
    request_timeout: int = 60
    default_num_of_rows: int = 500
    max_pages: int = 50
    max_retries: int = 3
    retry_backoff: float = 0.6
    tls_verify: bool = True
    rerank_model: str = "jhgan/ko-sroberta-multitask"
    rerank_max_candidates: int = 2000
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_file: str = "g2b.log"

    @classmethod
    def from_env(cls) -> "G2BConfig":
        api_key = (
            os.getenv("PUBLIC_DATA_API_KEY_ENCODED")
            or os.getenv("G2B_SERVICE_KEY")
            or os.getenv("G2B_API_KEY")
        )
        if not api_key:
            raise ValueError(
                "조달청 OpenAPI 서비스키가 설정되지 않았습니다. "
                "공공데이터포털(https://www.data.go.kr)에서 발급받은 키를 "
                "PUBLIC_DATA_API_KEY_ENCODED(또는 G2B_SERVICE_KEY) 환경변수에 설정하세요."
            )
        return cls(
            api_key=api_key,
            base_host=os.getenv("G2B_BASE_HOST", "http://apis.data.go.kr/1230000"),
            request_timeout=_int_env("G2B_REQUEST_TIMEOUT", 60),
            default_num_of_rows=_int_env("G2B_NUM_OF_ROWS", 500),
            max_pages=_int_env("G2B_MAX_PAGES", 50),
            max_retries=_int_env("G2B_MAX_RETRIES", 3),
            retry_backoff=_float_env("G2B_RETRY_BACKOFF", 0.6),
            tls_verify=_bool_env("G2B_TLS_VERIFY", True),
            rerank_model=os.getenv("G2B_RERANK_MODEL", "jhgan/ko-sroberta-multitask"),
            rerank_max_candidates=_int_env("G2B_RERANK_MAX_CANDIDATES", 2000),
            log_format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
            log_file=os.getenv("LOG_FILE", "g2b.log"),
        )


@dataclass
class MCPConfig:
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "INFO"
    server_name: str = "mcp-kr-g2b"
    transport: Literal["stdio", "streamable-http", "sse", "http"] = "stdio"

    @classmethod
    def from_env(cls) -> "MCPConfig":
        raw_transport = (os.getenv("TRANSPORT", "stdio") or "stdio").strip().lower()
        if raw_transport not in _ALLOWED_TRANSPORTS:
            logger.warning(
                f"알 수 없는 TRANSPORT='{raw_transport}' → 'stdio' 로 폴백합니다. "
                f"허용값: {sorted(_ALLOWED_TRANSPORTS)}"
            )
            raw_transport = "stdio"
        return cls(
            host=os.getenv("HOST", "0.0.0.0"),
            port=_int_env("PORT", 8002),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            server_name=os.getenv("MCP_SERVER_NAME", "mcp-kr-g2b"),
            transport=cast(Literal["stdio", "streamable-http", "sse", "http"], raw_transport),
        )


def _try_make_config() -> Optional[G2BConfig]:
    try:
        return G2BConfig.from_env()
    except Exception as e:  # pragma: no cover - 키 미설정 시 None
        logger.warning(f"G2BConfig 초기화 실패(서비스키 미설정 가능): {e}")
        return None


# 설정 인스턴스 생성
g2b_config = _try_make_config()
mcp_config = MCPConfig.from_env()
