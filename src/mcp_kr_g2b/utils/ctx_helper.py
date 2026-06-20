"""
컨텍스트 헬퍼

mcp-opendart 의 with_context / with_context_async / as_json_text 패턴을 차용.
MCP lifespan 컨텍스트를 우선 사용하고, 없으면 전역 컨텍스트로 폴백한다.
"""

import json
import logging
from typing import Any, Callable, Optional

from mcp.types import TextContent

logger = logging.getLogger("mcp-kr-g2b")


def _normalize_lifespan_context(lifespan_context: Any) -> Any:
    if isinstance(lifespan_context, dict):
        for key in ("app_lifespan_context", "lifespan_context", "context", "ctx"):
            if key in lifespan_context:
                return lifespan_context[key]
        if "client" in lifespan_context or hasattr(lifespan_context, "client"):
            return lifespan_context
    return lifespan_context


def _get_context_from_ctx(ctx: Any) -> Optional[Any]:
    if ctx is None:
        return None
    try:
        if hasattr(ctx, "request_context"):
            request_ctx = ctx.request_context
            if hasattr(request_ctx, "lifespan_context"):
                return _normalize_lifespan_context(request_ctx.lifespan_context)
    except Exception as e:  # pragma: no cover
        logger.debug(f"Context 추출 실패: {e}")
    return None


def as_json_text(payload: Any) -> TextContent:
    """dict/list/str/기타 데이터를 JSON TextContent 로 변환."""
    if isinstance(payload, (dict, list)):
        txt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(payload, str):
        # 이미 JSON '객체/배열'이면 그대로 통과(이중 인코딩 방지). 단, 'true'/'123'/'null'/
        # 'NaN' 같은 스칼라·비표준 토큰은 사람이 읽을 메시지일 수 있으므로 래핑한다.
        try:
            parsed = json.loads(payload, parse_constant=lambda _c: None)
            if isinstance(parsed, (dict, list)):
                txt = payload
            else:
                txt = json.dumps({"raw": payload}, ensure_ascii=False, separators=(",", ":"))
        except (json.JSONDecodeError, ValueError):
            txt = json.dumps({"raw": payload}, ensure_ascii=False, separators=(",", ":"))
    else:
        def _default(o: Any) -> Any:
            if isinstance(o, bytes):
                try:
                    return o.decode("utf-8")
                except UnicodeDecodeError:
                    return f"<bytes: {len(o)} bytes>"
            try:
                return o.model_dump()
            except Exception:
                return str(o)

        txt = json.dumps(payload, ensure_ascii=False, default=_default, separators=(",", ":"))
    return TextContent(type="text", text=txt)


def with_context(ctx: Optional[Any], tool_name: str, fallback_func: Callable[[Any], Any]) -> Any:
    """MCP context 를 안전하게 처리. 주입 컨텍스트 우선, 없으면 전역 컨텍스트 폴백."""
    logger.info(f"📌 Tool: {tool_name} 호출됨")

    g2b_ctx = _get_context_from_ctx(ctx)
    if g2b_ctx is not None:
        try:
            result = fallback_func(g2b_ctx)
            logger.info("✅ MCP 내부 컨텍스트 사용")
            return result
        except Exception as e:
            logger.warning(f"⚠️ MCPContext 접근 실패, 전역 컨텍스트로 폴백: {e}")

    try:
        from mcp_kr_g2b.server import get_global_context

        global_ctx = get_global_context()
        if global_ctx is not None:
            result = fallback_func(global_ctx)
            logger.info("✅ 전역 컨텍스트 사용 (fallback)")
            return result
    except Exception as e:
        logger.error(f"⚠️ 전역 컨텍스트 접근 실패: {e}")

    raise ValueError("G2B context is required but not provided. Lifespan context not initialized.")


async def with_context_async(ctx: Optional[Any], tool_name: str, fallback_func: Callable[[Any], Any]) -> Any:
    """with_context 의 비동기 버전."""
    logger.info(f"📌 Tool: {tool_name} 호출됨 (async)")

    g2b_ctx = _get_context_from_ctx(ctx)
    if g2b_ctx is not None:
        try:
            result = fallback_func(g2b_ctx)
            logger.info("✅ MCP 내부 컨텍스트 사용 (async)")
            return result
        except Exception as e:
            logger.warning(f"⚠️ MCPContext 접근 실패, 전역 컨텍스트로 폴백 (async): {e}")

    try:
        from mcp_kr_g2b.server import get_global_context

        global_ctx = get_global_context()
        if global_ctx is not None:
            result = fallback_func(global_ctx)
            logger.info("✅ 전역 컨텍스트 사용 (fallback, async)")
            return result
    except Exception as e:
        logger.error(f"⚠️ 전역 컨텍스트 접근 실패 (async): {e}")

    raise ValueError("G2B context is required but not provided. Lifespan context not initialized.")
