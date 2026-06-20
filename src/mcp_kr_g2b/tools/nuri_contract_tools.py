"""누리장터 민간계약정보서비스 도구 (코드 생성)

서비스 ID : PrvtCntrctInfoService
오퍼레이션 : 4개
호출       : get_nuri_contract_data(operation="<영문오퍼레이션명>", params={...})
상세 스펙  : get_g2b_operation_info("nuri_contract", "<operation>")
"""

from typing import Annotated, Any, Dict, Optional

from pydantic import Field
from mcp.types import TextContent

from mcp_kr_g2b.server import mcp
from mcp_kr_g2b.tools._helpers import build_service_tool_description, dispatch_service_fetch


@mcp.tool(
    name="get_nuri_contract_data",
    description=build_service_tool_description("nuri_contract"),
    tags={"조달청", "누리장터", "민간계약"},
)
def get_nuri_contract_data(
    operation: Annotated[str, Field(description="오퍼레이션명(영문). 예: getPrvtCntrctInfoList (계약현황 민간조회)")],
    params: Annotated[
        Optional[Dict[str, Any]],
        Field(description="오퍼레이션별 조회조건 dict (예: inqryDiv, inqryBgnDt, inqryEndDt, bidNtceNo 등). 정확한 키는 get_g2b_operation_info 로 확인"),
    ] = None,
    fetch_all: Annotated[bool, Field(description="True 면 totalCount 까지 전체 페이지 수집, False 면 단일 페이지")] = True,
    num_of_rows: Annotated[int, Field(description="페이지당 결과 수(기본 500, 최대 999. 대량수집 시 요청수↓)")] = 500,
    page_no: Annotated[Optional[int], Field(description="페이지 번호. 지정하면 해당 페이지만 단건 조회")] = None,
) -> TextContent:
    """누리장터 민간계약정보서비스 의 오퍼레이션을 호출하여 결과를 캐시하고 요약을 반환합니다."""
    return dispatch_service_fetch("nuri_contract", operation, params, fetch_all, num_of_rows, page_no)
