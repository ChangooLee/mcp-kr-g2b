"""
도구 메타데이터 관리

mcp-kr-realestate 의 ToolRegistry 구조를 차용. 모든 오퍼레이션을 카탈로그로 보관하여
get_g2b_operation_info 도구가 임의 오퍼레이션의 상세 스펙(파라미터/연관도구)을 반환할 수 있게 한다.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger("mcp-kr-g2b")


class ToolMetadata:
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        korean_name: Optional[str] = None,
        service: Optional[str] = None,
        linked_tools: Optional[List[str]] = None,
    ):
        self.name = name
        self.korean_name = korean_name
        self.description = description
        self.parameters = parameters
        self.service = service
        self.linked_tools = linked_tools or []

    def rich_description(self) -> str:
        lines = []
        if self.korean_name:
            lines.append(f"[도구 이름] {self.korean_name}")
        if self.service:
            lines.append(f"[서비스] {self.service}")
        if self.description:
            lines.append(f"[설명] {self.description}")
        props = self.parameters.get("properties", {})
        required = set(self.parameters.get("required", []))
        if props:
            lines.append("[입력 파라미터]")
            for key, schema in props.items():
                desc = schema.get("description", "")
                mark = " (필수)" if key in required else ""
                lines.append(f"- `{key}`: {desc}{mark}")
        if self.linked_tools:
            lines.append(f"[연관 도구] {', '.join(self.linked_tools)}")
        return "\n".join(lines)

    def to_function_schema(self) -> dict:
        return {"name": self.name, "description": self.rich_description(), "parameters": self.parameters}

    def to_mcp_tool(self) -> dict:
        return {"name": self.name, "description": self.rich_description(), "inputSchema": self.parameters}

    def brief_summary(self) -> str:
        kor = f" ({self.korean_name})" if self.korean_name else ""
        return f"- {self.name}{kor}: {self.description}"


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, ToolMetadata] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        korean_name: Optional[str] = None,
        service: Optional[str] = None,
        linked_tools: Optional[List[str]] = None,
    ):
        self.tools[name] = ToolMetadata(
            name=name,
            description=description,
            parameters=parameters,
            korean_name=korean_name,
            service=service,
            linked_tools=linked_tools,
        )

    def list_tools(self) -> List[dict]:
        return [tool.to_mcp_tool() for tool in self.tools.values()]

    def export_function_schemas(self) -> List[dict]:
        return [tool.to_function_schema() for tool in self.tools.values()]

    def export_brief_summary(self) -> str:
        return "\n".join(tool.brief_summary() for tool in self.tools.values())

    def get_tool(self, name: str) -> Optional[ToolMetadata]:
        return self.tools.get(name)

    def by_service(self, service: str) -> List[ToolMetadata]:
        return [t for t in self.tools.values() if t.service == service]
