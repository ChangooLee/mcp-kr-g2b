"""
FastMCP 서버 메인 엔트리포인트 (조달청 나라장터 MCP)

구조는 mcp-opendart 를 따른다:
- G2BContext: 클라이언트 + 서비스(모듈별 G2BService) 보관
- 전역 컨텍스트 + with_context 폴백
- lifespan 에서 초기화, 하단에서 도구 모듈 import 하여 @mcp.tool 등록
"""

import sys
import logging
import threading
import importlib
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional

from fastmcp import FastMCP

from .config import MCPConfig, G2BConfig, mcp_config, g2b_config
from .apis.client import G2BClient
from .apis.service import G2BService, SERVICE_MODULES, load_all_specs

# ── 로깅 ──────────────────────────────────────────────────────────
level_name = mcp_config.log_level.upper()
level = getattr(logging, level_name, logging.INFO)
logger = logging.getLogger("mcp-kr-g2b")
logging.basicConfig(
    level=level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

# ── 전역 컨텍스트 (fallback용) ─────────────────────────────────────
_global_context: Optional["G2BContext"] = None
_context_lock = threading.Lock()


def set_global_context(ctx: "G2BContext") -> None:
    global _global_context
    with _context_lock:
        _global_context = ctx
        logger.info("✅ Global G2BContext 저장됨")


def get_global_context() -> Optional["G2BContext"]:
    with _context_lock:
        return _global_context


@dataclass
class G2BContext:
    """조달청 MCP 서버 컨텍스트."""

    client: Optional[G2BClient] = None
    services: Dict[str, G2BService] = field(default_factory=dict)


def build_context() -> G2BContext:
    """번들 명세를 로드하고, 키가 있으면 클라이언트/서비스를 초기화한다."""
    specs = load_all_specs()
    client: Optional[G2BClient] = None
    services: Dict[str, G2BService] = {}

    if g2b_config is not None:
        try:
            client = G2BClient(g2b_config)
            for module in SERVICE_MODULES:
                if module in specs:
                    services[module] = G2BService(client, specs[module], module)
            logger.info(f"G2B 서비스 {len(services)}개 초기화 완료")
        except Exception as e:
            logger.warning(f"G2B 클라이언트 초기화 실패(키 미설정 가능): {e}")
    else:
        logger.warning(
            "서비스키가 설정되지 않아 조회 기능이 비활성화됩니다. "
            "디스커버리 도구(list_g2b_services 등)는 사용 가능합니다."
        )
    return G2BContext(client=client, services=services)


@asynccontextmanager
async def g2b_lifespan(app: FastMCP) -> AsyncIterator[G2BContext]:
    logger.info("Initializing KR-G2B FastMCP server...")
    logger.info(f"Server Name: {mcp_config.server_name}")
    logger.info(f"Transport: {mcp_config.transport}  Port: {mcp_config.port}")
    ctx = build_context()
    set_global_context(ctx)
    try:
        yield ctx
    finally:
        global _global_context
        with _context_lock:
            _global_context = None
        logger.info("Shutting down KR-G2B FastMCP server...")


# ── FastMCP 인스턴스 ───────────────────────────────────────────────
mcp = FastMCP(
    "KR G2B MCP",
    instructions=(
        "조달청 나라장터/누리장터(국가종합전자조달, G2B) OpenAPI MCP 서버. "
        "입찰공고·사전규격·낙찰·계약·발주계획·가격정보·공공조달통계 등을 조회합니다."
    ),
    lifespan=g2b_lifespan,
)

# 임포트 시점에도 전역 컨텍스트를 준비(stdio 외 경로 대비)
set_global_context(build_context())

# ── 도구 모듈 등록 ─────────────────────────────────────────────────
_TOOL_MODULES = [f"{m}_tools" for m in SERVICE_MODULES] + ["common_tools"]
for _mod in _TOOL_MODULES:
    try:
        importlib.import_module(f"mcp_kr_g2b.tools.{_mod}")
    except Exception as e:  # pragma: no cover
        logger.error(f"도구 모듈 로드 실패({_mod}): {e}")


def main() -> None:
    logger.info("✅ Initializing KR-G2B FastMCP server...")
    transport = mcp_config.transport
    if transport == "sse":
        logger.info(f"Starting SSE on http://{mcp_config.host}:{mcp_config.port}")
        mcp.run(transport="sse", host=mcp_config.host, port=mcp_config.port)
    elif transport in ("streamable-http", "http"):
        logger.info(f"Starting streamable-http on http://{mcp_config.host}:{mcp_config.port}/mcp")
        mcp.run(transport="streamable-http", host=mcp_config.host, port=mcp_config.port)
    else:  # stdio (기본)
        logger.info("Starting stdio transport")
        mcp.run()


if __name__ == "__main__":
    main()
