"""G2BClient 파싱/키처리 단위 테스트 (네트워크 불필요)."""
import pytest

from mcp_kr_g2b.config import G2BConfig
from mcp_kr_g2b.apis.client import G2BClient


@pytest.fixture
def client():
    return G2BClient(G2BConfig(api_key="DUMMYKEY"))


def test_derive_key_forms_encoded_input():
    forms = G2BClient._derive_key_forms("ab%2Bcd%3D%3D")
    # 정규 %-인코딩 형식이 항상 첫 번째
    assert forms[0] == "ab%2Bcd%3D%3D"


def test_derive_key_forms_decoded_input():
    forms = G2BClient._derive_key_forms("ab+cd==")
    # 디코딩 키를 넣어도 정규 인코딩 형식이 후보에 포함되어 첫 번째여야 함
    assert forms[0] == "ab%2Bcd%3D%3D"
    assert "ab+cd==" in forms


def test_is_key_error_only_on_error_codes():
    # 정상 코드면 본문에 트리거 문자열이 있어도 키오류로 보지 않음(오탐 방지)
    assert G2BClient._is_key_error({"resultCode": "00"}, "…등록되지 않은…") is False
    # 키 등록 오류 코드
    assert G2BClient._is_key_error({"resultCode": "30"}, "") is True
    # 코드 없음 + 인증 실패 본문
    assert G2BClient._is_key_error({"resultCode": ""}, "SERVICE_KEY_IS_NOT_REGISTERED_ERROR") is True
    assert G2BClient._is_key_error({"resultCode": ""}, "Unauthorized") is True


def test_extract_items_shapes():
    assert G2BClient._extract_items({"items": [{"a": 1}, {"b": 2}]}) == [{"a": 1}, {"b": 2}]
    assert G2BClient._extract_items({"items": {"item": [{"a": 1}]}}) == [{"a": 1}]
    assert G2BClient._extract_items({"items": {"item": {"a": 1}}}) == [{"a": 1}]
    assert G2BClient._extract_items({"items": ""}) == []
    assert G2BClient._extract_items(None) == []


def test_parse_json_standard_envelope(client):
    text = (
        '{"response":{"header":{"resultCode":"00","resultMsg":"정상"},'
        '"body":{"items":[{"bidNtceNm":"테스트"}],"numOfRows":10,"pageNo":1,"totalCount":1}}}'
    )
    header, items, total, total_present = client._parse_response(text)
    assert header["resultCode"] == "00"
    assert len(items) == 1 and items[0]["bidNtceNm"] == "테스트"
    assert total == 1 and total_present is True


def test_parse_json_empty_items(client):
    text = '{"response":{"header":{"resultCode":"00","resultMsg":"정상"},"body":{"items":"","totalCount":0}}}'
    header, items, total, total_present = client._parse_response(text)
    assert items == [] and total == 0 and total_present is True


def test_parse_json_missing_total(client):
    # totalCount 가 없으면 total_present=False (fetch_all 이 1페이지에서 멈추지 않도록)
    text = '{"response":{"header":{"resultCode":"00"},"body":{"items":[{"a":1}]}}}'
    _h, items, _t, total_present = client._parse_response(text)
    assert items == [{"a": 1}] and total_present is False


def test_parse_html_is_safe(client):
    header, items, total, total_present = client._parse_response("<!DOCTYPE html><html>점검</html>")
    assert items == [] and total == 0 and total_present is False


def test_parse_broken_json_is_safe(client):
    header, items, total, total_present = client._parse_response('{"response": {bad')
    assert header["resultCode"] == "PARSE_ERROR" and items == []


def test_parse_xml(client):
    text = (
        "<response><header><resultCode>00</resultCode><resultMsg>정상</resultMsg></header>"
        "<body><items><item><a>1</a><b>x</b></item><item><a>2</a></item></items>"
        "<totalCount>2</totalCount></body></response>"
    )
    header, items, total, total_present = client._parse_response(text)
    assert header["resultCode"] == "00"
    assert items == [{"a": "1", "b": "x"}, {"a": "2"}]
    assert total == 2 and total_present is True


def test_build_url_appends_key_literally(client):
    url = client._build_url("http://h/svc", "getX", {"a": "1", "b": ""}, "K%2B")
    assert url.endswith("serviceKey=K%2B")
    assert "b=" not in url  # 빈 값 제거
    assert "a=1" in url


def test_to_int():
    assert G2BClient._to_int("1,234") == 1234
    assert G2BClient._to_int("") == 0
    assert G2BClient._to_int(None, default=5) == 5
