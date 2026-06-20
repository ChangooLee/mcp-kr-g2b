"""
데이터 기반 조달청 서비스 추상화

조달청 나라장터/누리장터 14개 서비스는 모두 동일한 공공데이터포털 게이트웨이
규약(serviceKey + numOfRows/pageNo/type + items/totalCount)을 따른다. 따라서
서비스별로 별도 클래스를 만드는 대신, 번들된 명세(JSON)를 로드하여 동작하는
하나의 제네릭 클래스 G2BService 로 모든 서비스를 처리한다.

명세 JSON 은 src/mcp_kr_g2b/specs/<module>.json 에 번들된다.
(원본: 조달청 OpenAPI 참고자료 .docx → 파싱)
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .client import G2BClient

logger = logging.getLogger("mcp-kr-g2b")

SPECS_DIR = Path(__file__).parent.parent / "specs"

# 서비스 모듈 목록 + 한글 표시명 (도구/디스커버리 출력 순서)
SERVICE_MODULES: List[str] = [
    "bid",
    "prestd",
    "scsbid",
    "contract",
    "contract_process",
    "order_plan",
    "price",
    "stats",
    "data_standard",
    "industry",
    "user_info",
    "nuri_bid",
    "nuri_scsbid",
    "nuri_contract",
]

SERVICE_LABELS: Dict[str, str] = {
    "bid": "나라장터 입찰공고정보서비스",
    "prestd": "나라장터 사전규격정보서비스",
    "scsbid": "나라장터 낙찰정보서비스",
    "contract": "나라장터 계약정보서비스",
    "contract_process": "나라장터 계약과정 통합공개서비스",
    "order_plan": "나라장터 발주계획 현황서비스",
    "price": "나라장터 가격정보 현황서비스",
    "stats": "공공조달통계정보서비스",
    "data_standard": "나라장터 공공데이터 개방표준서비스",
    "industry": "나라장터 업종 및 근거법규서비스",
    "user_info": "나라장터 사용자정보서비스",
    "nuri_bid": "누리장터 민간입찰공고서비스",
    "nuri_scsbid": "누리장터 민간낙찰정보서비스",
    "nuri_contract": "누리장터 민간계약정보서비스",
}

# 사용자가 값으로 지정할 필요가 없는 공통/자동 처리 파라미터
_AUTO_PARAMS = {"serviceKey", "ServiceKey", "numOfRows", "pageNo", "type"}


def spec_path(module: str) -> Path:
    return SPECS_DIR / f"{module}.json"


def load_spec(module: str) -> Dict[str, Any]:
    path = spec_path(module)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_specs() -> Dict[str, Dict[str, Any]]:
    specs: Dict[str, Dict[str, Any]] = {}
    for module in SERVICE_MODULES:
        p = spec_path(module)
        if p.exists():
            try:
                specs[module] = load_spec(module)
            except Exception as e:  # pragma: no cover
                logger.warning(f"명세 로드 실패({module}): {e}")
    return specs


class G2BService:
    """하나의 조달청 서비스(여러 오퍼레이션)를 명세 기반으로 호출."""

    def __init__(self, client: G2BClient, spec: Dict[str, Any], module: Optional[str] = None):
        self.client = client
        self.spec = spec
        self.module = module or spec.get("module", "")
        self.service_id = spec.get("serviceId", "")
        self.service_name = spec.get("serviceNameKo", SERVICE_LABELS.get(self.module, ""))
        self.base_url = spec.get("baseUrl", "")
        self.operations: Dict[str, Dict[str, Any]] = {
            op["opNameEn"]: op for op in spec.get("operations", []) if op.get("opNameEn")
        }

    # ---- 메타데이터 ---- #
    def operation_names(self) -> List[str]:
        return list(self.operations.keys())

    def operation_brief(self) -> List[Dict[str, str]]:
        return [
            {"operation": name, "korean": op.get("opNameKo", ""), "type": op.get("opType", "")}
            for name, op in self.operations.items()
        ]

    def get_operation(self, operation: str) -> Optional[Dict[str, Any]]:
        return self.operations.get(operation)

    def required_params(self, operation: str) -> List[str]:
        op = self.operations.get(operation) or {}
        return [
            p["nameEn"]
            for p in op.get("requestParams", [])
            if p.get("required") and p.get("nameEn") and p["nameEn"] not in _AUTO_PARAMS
        ]

    # ---- 호출 ---- #
    def fetch(
        self,
        operation: str,
        params: Optional[Dict[str, Any]] = None,
        num_of_rows: Optional[int] = None,
        page_no: Optional[int] = None,
        fetch_all: bool = True,
    ) -> Dict[str, Any]:
        if operation not in self.operations:
            raise ValueError(
                f"'{operation}' 은(는) {self.service_name}({self.module}) 의 오퍼레이션이 아닙니다. "
                f"가능한 오퍼레이션: {', '.join(self.operation_names()) or '(없음)'}"
            )

        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}

        # 필수 파라미터 누락 경고(차단하지는 않음 — 전체조회형 오퍼레이션 존재)
        missing = [p for p in self.required_params(operation) if p not in params]
        if missing:
            logger.warning(f"{operation} 필수 파라미터 누락 가능: {missing}")

        if fetch_all and page_no is None:
            result = self.client.fetch_all(self.base_url, operation, params, num_of_rows)
        else:
            result = self.client.fetch_page(self.base_url, operation, params, num_of_rows, page_no or 1)
            # fetch_page 결과를 fetch_all 과 동일한 형태로 보정
            result.setdefault("base_url", self.base_url)
            result["fetchedCount"] = len(result.get("items", []))
            result["request_params"] = params

        result["service"] = self.module
        result["serviceName"] = self.service_name
        if missing:
            result["warning"] = f"필수 파라미터 누락 가능: {missing}"
        return result
