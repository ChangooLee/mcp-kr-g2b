"""
공통 디스커버리/캐시 도구

- list_g2b_services       : 14개 서비스와 오퍼레이션 개요 목록
- get_g2b_operation_info  : 특정 오퍼레이션의 상세 스펙(파라미터/응답필드)
- get_g2b_cache_data      : 저장된 캐시 파일을 필드 필터/페이지로 조회
"""

import json
import logging
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field
from mcp.types import TextContent

from mcp_kr_g2b.server import mcp
from mcp_kr_g2b.apis.service import (
    SERVICE_MODULES,
    SERVICE_LABELS,
    load_spec,
    spec_path,
)
from mcp_kr_g2b.utils.ctx_helper import as_json_text

logger = logging.getLogger("mcp-kr-g2b")

_AUTO_PARAMS = {"serviceKey", "ServiceKey", "numOfRows", "pageNo", "type"}
_DESC_MAX = 400


def _truncate(text: Optional[str], n: int = _DESC_MAX) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + " …(생략)"


@mcp.tool(
    name="list_g2b_services",
    description=(
        "조달청 나라장터/누리장터 MCP가 제공하는 14개 서비스와 각 서비스의 오퍼레이션 개요를 조회합니다. "
        "어떤 서비스/오퍼레이션을 호출할지 결정하기 위한 출발점입니다. "
        "각 서비스는 get_<module>_data 도구로 호출하며, 상세 파라미터는 get_g2b_operation_info 로 확인합니다."
    ),
    tags={"조달청", "나라장터", "디스커버리", "서비스목록"},
)
def list_g2b_services(
    include_operations: Annotated[bool, Field(description="각 서비스의 오퍼레이션 목록 포함 여부")] = True,
) -> TextContent:
    services: List[Dict[str, Any]] = []
    for module in SERVICE_MODULES:
        if not spec_path(module).exists():
            continue
        try:
            spec = load_spec(module)
        except Exception as e:
            logger.warning(f"명세 로드 실패({module}): {e}")
            continue
        entry: Dict[str, Any] = {
            "module": module,
            "label": spec.get("serviceNameKo") or SERVICE_LABELS.get(module, module),
            "serviceId": spec.get("serviceId", ""),
            "tool": f"get_{module}_data",
            "operationCount": len(spec.get("operations", [])),
        }
        if include_operations:
            entry["operations"] = [
                {"operation": op.get("opNameEn"), "korean": op.get("opNameKo", "")}
                for op in spec.get("operations", [])
            ]
        services.append(entry)
    return as_json_text({"serviceCount": len(services), "services": services})


@mcp.tool(
    name="get_g2b_operation_info",
    description=(
        "특정 서비스 오퍼레이션의 상세 명세(요청 파라미터·필수여부·응답 필드·예제 URL)를 조회합니다. "
        "get_<module>_data 를 호출하기 전에 params 에 넣을 정확한 파라미터명을 확인할 때 사용하세요. "
        "operation 을 생략하면 해당 서비스의 전체 오퍼레이션 목록을 반환합니다."
    ),
    tags={"조달청", "나라장터", "오퍼레이션", "파라미터", "스펙"},
)
def get_g2b_operation_info(
    module: Annotated[str, Field(description="서비스 모듈명 (예: bid, scsbid, contract, price …). list_g2b_services 로 확인")],
    operation: Annotated[Optional[str], Field(description="오퍼레이션명(영문). 생략 시 서비스의 전체 오퍼레이션 목록 반환")] = None,
) -> TextContent:
    if not spec_path(module).exists():
        return as_json_text(
            {"error": f"알 수 없는 서비스 모듈 '{module}'", "available_modules": SERVICE_MODULES}
        )
    spec = load_spec(module)
    label = spec.get("serviceNameKo") or SERVICE_LABELS.get(module, module)
    ops = spec.get("operations", [])

    if operation is None:
        return as_json_text(
            {
                "module": module,
                "label": label,
                "serviceId": spec.get("serviceId", ""),
                "baseUrl": spec.get("baseUrl", ""),
                "tool": f"get_{module}_data",
                "operations": [
                    {
                        "operation": op.get("opNameEn"),
                        "korean": op.get("opNameKo", ""),
                        "type": op.get("opType", ""),
                    }
                    for op in ops
                ],
            }
        )

    op = next((o for o in ops if o.get("opNameEn") == operation), None)
    if op is None:
        return as_json_text(
            {
                "error": f"'{operation}' 오퍼레이션을 {module} 서비스에서 찾을 수 없습니다.",
                "available_operations": [o.get("opNameEn") for o in ops],
            }
        )

    req_params = []
    for p in op.get("requestParams", []):
        name = p.get("nameEn")
        if not name:
            continue
        req_params.append(
            {
                "name": name,
                "korean": p.get("nameKo", ""),
                "required": bool(p.get("required")),
                "auto_handled": name in _AUTO_PARAMS,
                "size": p.get("size", ""),
                "sample": p.get("sample", ""),
                "description": _truncate(p.get("desc")),
            }
        )
    resp_fields = [
        {"name": f.get("nameEn"), "korean": f.get("nameKo", ""), "description": _truncate(f.get("desc"))}
        for f in op.get("responseFields", [])
        if f.get("nameEn")
    ]
    user_params = [p for p in req_params if not p["auto_handled"]]
    required = [p["name"] for p in user_params if p["required"]]

    return as_json_text(
        {
            "module": module,
            "label": label,
            "tool": f"get_{module}_data",
            "operation": operation,
            "korean": op.get("opNameKo", ""),
            "type": op.get("opType", ""),
            "description": _truncate(op.get("description"), 800),
            "required_params": required,
            "request_params": user_params,
            "auto_params": [p["name"] for p in req_params if p["auto_handled"]],
            "response_fields": resp_fields,
            "sample_uri": op.get("sampleUri", ""),
            "usage_example": {
                "tool": f"get_{module}_data",
                "operation": operation,
                "params": {p: "<값>" for p in required} or {"<조회조건>": "<값>"},
            },
        }
    )


@mcp.tool(
    name="get_g2b_cache_data",
    description=(
        "get_<module>_data 호출로 저장된 캐시 파일(cache_file)에서 전체 결과를 필드 필터/페이지 단위로 조회합니다. "
        "대량 조회 결과를 미리보기 이후 상세 탐색할 때 사용합니다."
    ),
    tags={"조달청", "나라장터", "캐시", "필터", "조회"},
)
def get_g2b_cache_data(
    cache_file: Annotated[str, Field(description="get_<module>_data 가 반환한 cache_file 경로")],
    field_name: Annotated[Optional[str], Field(description="필터링할 응답 필드명")] = None,
    field_value_substring: Annotated[Optional[str], Field(description="필드 값에 포함될 부분 문자열")] = None,
    offset: Annotated[int, Field(description="시작 인덱스(0부터)")] = 0,
    limit: Annotated[int, Field(description="반환 최대 건수")] = 20,
) -> TextContent:
    path = Path(cache_file)
    if not path.exists():
        return as_json_text({"error": f"캐시 파일이 존재하지 않습니다: {cache_file}"})
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return as_json_text({"error": f"캐시 파일 로드 실패: {e}"})

    items: List[Dict[str, Any]] = data.get("items", [])
    if field_name and field_value_substring:
        items = [
            it
            for it in items
            if isinstance(it, dict) and field_value_substring in str(it.get(field_name, ""))
        ]

    sliced = items[offset : offset + limit]
    unique_values = []
    if field_name:
        seen = []
        for it in items:
            if isinstance(it, dict):
                v = it.get(field_name)
                if v is not None and v not in seen:
                    seen.append(v)
            if len(seen) >= 50:
                break
        unique_values = seen

    return as_json_text(
        {
            "operation": data.get("operation"),
            "cache_file": cache_file,
            "matched_count": len(items),
            "offset": offset,
            "limit": limit,
            "returned": len(sliced),
            "unique_values_for_field": unique_values,
            "items": sliced,
        }
    )
