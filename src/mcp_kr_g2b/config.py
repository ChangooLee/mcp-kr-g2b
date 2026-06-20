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


@dataclass
class G2BConfig:
    """조달청 나라장터 OpenAPI configuration.

    api_key:
        공공데이터포털에서 발급받은 서비스키. URL 인코딩된(Encoding) 키를
        그대로 사용하는 것을 권장합니다(요청 시 추가 인코딩 없이 사용).
    base_host:
        조달청(기관코드 1230000) 공공데이터 게이트웨이 호스트. 각 서비스의
        실제 base_url은 서비스 명세에 정의된 전체 경로를 사용합니다.
    """

    api_key: str
    base_host: str = "http://apis.data.go.kr/1230000"
    request_timeout: int = 60
    default_num_of_rows: int = 500
    max_pages: int = 50
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_file: str = "g2b.log"

    @classmethod
    def from_env(cls) -> "G2BConfig":
        # 공공데이터포털 키: realestate 서버와 동일한 환경변수를 우선 사용하고,
        # 전용 변수(G2B_API_KEY / G2B_SERVICE_KEY)도 허용합니다.
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
            request_timeout=int(os.getenv("G2B_REQUEST_TIMEOUT", "60")),
            default_num_of_rows=int(os.getenv("G2B_NUM_OF_ROWS", "500")),
            max_pages=int(os.getenv("G2B_MAX_PAGES", "50")),
            log_format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
            log_file=os.getenv("LOG_FILE", "g2b.log"),
        )


@dataclass
class MCPConfig:
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "INFO"
    server_name: str = "mcp-kr-g2b"
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"

    @classmethod
    def from_env(cls) -> "MCPConfig":
        return cls(
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8002")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            server_name=os.getenv("MCP_SERVER_NAME", "mcp-kr-g2b"),
            transport=cast(
                Literal["stdio", "sse", "streamable-http"],
                os.getenv("TRANSPORT", "stdio"),
            ),
        )


def _try_make_config() -> Optional[G2BConfig]:
    try:
        return G2BConfig.from_env()
    except Exception as e:  # pragma: no cover - 설정 누락 시 None 반환
        logger.warning(f"G2BConfig 초기화 실패(키 미설정 가능): {e}")
        return None


# 설정 인스턴스 생성
g2b_config = _try_make_config()
mcp_config = MCPConfig.from_env()
