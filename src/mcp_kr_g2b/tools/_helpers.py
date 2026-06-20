"""
서비스 도구 공통 헬퍼

각 서비스별 도구(get_<module>_data)는 동일한 디스패치 로직을 공유한다:
1) 전역 컨텍스트의 G2BService 로 오퍼레이션 호출(페이지네이션 포함)
2) 전체 결과를 캐시 파일로 저장
3) 요약 + 미리보기 + 캐시경로만 반환(LLM 컨텍스트 효율)
"""

import logging
from typing import Any, Dict, Optional

from mcp.types import TextContent

from ..apis.service import load_spec, SERVICE_LABELS
from ..apis.client import G2BAPIError
from ..utils.ctx_helper import as_json_text
from ..utils.cache import save_result, summarize_result

logger = logging.getLogger("mcp-kr-g2b")


def build_service_tool_description(module: str) -> str:
    """번들 명세로부터 서비스 도구의 풍부한 설명(오퍼레이션 목록 포함)을 생성."""
    try:
        spec = load_spec(module)
    except Exception:
        return f"[{SERVICE_LABELS.get(module, module)}] 조달청 OpenAPI 조회 도구"

    label = spec.get("serviceNameKo") or SERVICE_LABELS.get(module, module)
    ops = spec.get("operations", [])
    lines = [
        f"[{label}] 조달청 나라장터 OpenAPI 조회 도구.",
        "operation 에 아래 오퍼레이션명(영문) 중 하나를 지정하고, params 에 해당 오퍼레이션의 "
        "조회조건을 dict 로 전달하세요. numOfRows/pageNo/type/serviceKey 는 자동 처리됩니다.",
        f"각 오퍼레이션의 정확한 파라미터/응답필드는 get_g2b_operation_info('{module}', '<operation>') 로 확인하세요.",
        "",
        f"사용 가능한 오퍼레이션 ({len(ops)}개):",
    ]
    for op in ops:
        lines.append(f"- {op.get('opNameEn')}: {op.get('opNameKo', '')}")
    lines.append("")
    lines.append(
        "자주 쓰는 조회조건: inqryDiv(조회구분 코드, 보통 1=등록/공고일시), "
        "inqryBgnDt/inqryEndDt(YYYYMMDDHHMM 조회기간), bidNtceNo(입찰공고번호), "
        "dminsttNm(수요기관명), indstrytyNm(업종명), prdctClsfcNo(품목분류번호) 등."
    )
    lines.append(
        "⚠️ 날짜 기반 조회(inqryBgnDt/inqryEndDt 등)는 보통 한 번에 1개월 이내 범위만 허용됩니다. "
        "기간이 길면 월 단위로 나눠 호출하세요. 'PPSSrch' 오퍼레이션은 bidNtceNm(공고명 일부)/"
        "indstrytyNm/추정가격 범위 등 상세 검색조건을 지원합니다."
    )
    return "\n".join(lines)


def dispatch_service_fetch(
    module: str,
    operation: str,
    params: Optional[Dict[str, Any]] = None,
    fetch_all: bool = True,
    num_of_rows: int = 500,
    page_no: Optional[int] = None,
) -> TextContent:
    """서비스 오퍼레이션을 호출하고 결과를 캐시한 뒤 요약을 반환."""
    logger.info(f"📌 Tool: get_{module}_data:{operation} 호출됨")

    # 이 서버의 도구는 ctx 를 주입받지 않으므로 전역 컨텍스트를 직접 사용한다.
    # (with_context 의 광범위 예외 처리에 실제 호출 오류가 가려지는 것을 방지)
    from ..server import get_global_context

    context = get_global_context()
    if context is None:
        return as_json_text(
            {"error": "NO_CONTEXT", "message": "서버 컨텍스트가 초기화되지 않았습니다.", "operation": operation}
        )

    svc = getattr(context, "services", {}).get(module)
    if svc is None:
        return as_json_text(
            {
                "error": "SERVICE_UNAVAILABLE",
                "message": (
                    f"서비스 '{module}' 가 초기화되지 않았습니다. "
                    f"서비스키(PUBLIC_DATA_API_KEY_ENCODED) 설정을 확인하세요."
                ),
                "operation": operation,
            }
        )

    try:
        result = svc.fetch(operation, params, num_of_rows, page_no, fetch_all)
    except G2BAPIError as e:
        return as_json_text(
            {"error": "G2B_API_ERROR", "code": e.code, "message": e.message, "operation": operation}
        )
    except ValueError as e:
        return as_json_text({"error": "INVALID_REQUEST", "message": str(e), "operation": operation})
    except Exception as e:  # pragma: no cover
        logger.error(f"{module}.{operation} 호출 실패: {e}", exc_info=True)
        return as_json_text({"error": "UNEXPECTED", "message": str(e), "operation": operation})

    saved = save_result(operation, params, result)
    summary = summarize_result(result, saved)
    summary["service"] = module
    if result.get("warning"):
        summary["warning"] = result["warning"]
    return as_json_text(summary)
