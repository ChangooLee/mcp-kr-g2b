"""
레지스트리 초기화

번들된 서비스 명세(specs/*.json)를 로드하여 156개 오퍼레이션 전체를 카탈로그로 등록한다.
각 오퍼레이션의 호출은 해당 서비스 도구(get_<module>_data)로 수행한다.
"""

from mcp_kr_g2b.registry.tool_registry import ToolRegistry
from mcp_kr_g2b.apis.service import SERVICE_MODULES, SERVICE_LABELS, load_spec, spec_path

_AUTO_PARAMS = {"serviceKey", "ServiceKey", "numOfRows", "pageNo", "type"}


def _params_schema(op: dict) -> dict:
    props = {}
    required = []
    for p in op.get("requestParams", []):
        name = p.get("nameEn")
        if not name or name in _AUTO_PARAMS:
            continue
        desc = f"{p.get('nameKo', '')}: {p.get('desc', '')}".strip(": ").strip()
        props[name] = {"type": "string", "description": desc}
        if p.get("required"):
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def initialize_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for module in SERVICE_MODULES:
        if not spec_path(module).exists():
            continue
        try:
            spec = load_spec(module)
        except Exception:
            continue
        label = spec.get("serviceNameKo") or SERVICE_LABELS.get(module, module)
        for op in spec.get("operations", []):
            name = op.get("opNameEn")
            if not name:
                continue
            registry.register_tool(
                name=f"{module}.{name}",
                korean_name=op.get("opNameKo", ""),
                service=label,
                description=op.get("description") or op.get("opNameKo", ""),
                parameters=_params_schema(op),
                linked_tools=[f"get_{module}_data", "get_g2b_operation_info"],
            )
    return registry
