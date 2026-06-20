"""공공조달통계정보서비스 도구 (코드 생성)

서비스 ID : PubPrcrmntStatInfoService
오퍼레이션 : 14개
호출       : get_stats_data(operation="<영문오퍼레이션명>", params={...})
상세 스펙  : get_g2b_operation_info("stats", "<operation>")
"""

from typing import Annotated, Any, Dict, Optional

from pydantic import Field
from mcp.types import TextContent

from mcp_kr_g2b.server import mcp
from mcp_kr_g2b.tools._helpers import build_service_tool_description, dispatch_service_fetch


@mcp.tool(
    name="get_stats_data",
    description=build_service_tool_description("stats"),
    tags={"조달청", "나라장터", "조달통계"},
)
def get_stats_data(
    operation: Annotated[str, Field(description="오퍼레이션명(영문). 예: getTotlPubPrcrmntSttus (전체 공공조달 현황)")],
    params: Annotated[
        Optional[Dict[str, Any]],
        Field(description="오퍼레이션별 조회조건 dict (예: inqryDiv, inqryBgnDt, inqryEndDt, bidNtceNo 등). 정확한 키는 get_g2b_operation_info 로 확인"),
    ] = None,
    fetch_all: Annotated[bool, Field(description="True 면 totalCount 까지 전체 페이지 수집, False 면 단일 페이지")] = True,
    num_of_rows: Annotated[int, Field(description="페이지당 결과 수(기본 100)")] = 100,
    page_no: Annotated[Optional[int], Field(description="페이지 번호. 지정하면 해당 페이지만 단건 조회")] = None,
) -> TextContent:
    """공공조달통계정보서비스 의 오퍼레이션을 호출하여 결과를 캐시하고 요약을 반환합니다."""
    return dispatch_service_fetch("stats", operation, params, fetch_all, num_of_rows, page_no)
