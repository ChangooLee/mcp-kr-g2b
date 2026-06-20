"""번들 명세(specs/*.json) 무결성 + 레지스트리 카탈로그 테스트 (네트워크 불필요)."""
import re
import json

import pytest

from mcp_kr_g2b.apis.service import (
    SERVICE_MODULES,
    SERVICE_LABELS,
    load_spec,
    spec_path,
    G2BService,
)

BASEURL_RE = re.compile(r"^https?://apis\.data\.go\.kr/1230000/[a-z]+/[A-Za-z0-9]+$")
OPNAME_RE = re.compile(r"^[a-z][A-Za-z0-9]+$")


def test_all_modules_have_spec_files():
    for m in SERVICE_MODULES:
        assert spec_path(m).exists(), f"명세 파일 누락: {m}"
    assert set(SERVICE_MODULES) == set(SERVICE_LABELS), "SERVICE_MODULES 와 SERVICE_LABELS 불일치"


@pytest.mark.parametrize("module", SERVICE_MODULES)
def test_spec_integrity(module):
    spec = load_spec(module)
    assert spec.get("module") == module
    assert spec.get("serviceId"), f"{module}: serviceId 누락"
    base = spec.get("baseUrl", "")
    assert BASEURL_RE.match(base), f"{module}: baseUrl 형식 이상: {base}"
    assert base.rstrip("/").split("/")[-1] == spec["serviceId"], f"{module}: baseUrl 말단이 serviceId 와 다름"

    ops = spec.get("operations", [])
    assert ops, f"{module}: 오퍼레이션 없음"
    names = [o["opNameEn"] for o in ops]
    assert len(names) == len(set(names)), f"{module}: 중복 오퍼레이션"
    for o in ops:
        ne = o["opNameEn"]
        assert OPNAME_RE.match(ne), f"{module}: 비정상 opNameEn '{ne}'"
        assert o.get("requestParams"), f"{module}.{ne}: requestParams 없음"
        assert o.get("responseFields"), f"{module}.{ne}: responseFields 없음"
        for p in o["requestParams"]:
            assert p.get("nameEn"), f"{module}.{ne}: 빈 파라미터명"


def test_total_operation_count():
    total = sum(len(load_spec(m).get("operations", [])) for m in SERVICE_MODULES)
    assert total == 156, f"오퍼레이션 총수 {total} (기대 156)"


def test_servcinfo_request_params_are_not_response_fields():
    """contract 의 ServcInfo 계열 3개 오퍼레이션 requestParams 가 응답필드 복사본이 아니어야 함(파서 결함 회귀 방지)."""
    spec = load_spec("contract")
    targets = {
        "getCntrctInfoListCnstwkServcInfo",
        "getCntrctInfoListGnrlServcServcInfo",
        "getCntrctInfoListTechServcServcInfo",
    }
    for op in spec["operations"]:
        if op["opNameEn"] in targets:
            req = {p["nameEn"] for p in op["requestParams"]}
            # 응답 전용 필드가 요청 파라미터에 섞여 있으면 안 됨
            assert "resultCode" not in req and "totalCount" not in req, f"{op['opNameEn']}: 요청/응답 표 혼동"
            assert "untyCntrctNo" in req, f"{op['opNameEn']}: 필수 untyCntrctNo 누락"


def test_service_rejects_unknown_operation():
    spec = load_spec("bid")
    svc = G2BService(client=None, spec=spec, module="bid")
    with pytest.raises(ValueError):
        svc.fetch("doesNotExist")


def test_service_required_params_excludes_auto():
    spec = load_spec("bid")
    svc = G2BService(client=None, spec=spec, module="bid")
    for op in svc.operation_names():
        for rp in svc.required_params(op):
            assert rp not in {"serviceKey", "ServiceKey", "numOfRows", "pageNo", "type"}
