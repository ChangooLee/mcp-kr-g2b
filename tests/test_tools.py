"""도구 계층(common_tools) + 유틸 동작 테스트 (네트워크 불필요)."""
import json

from mcp_kr_g2b.utils import cache as cache_util
from mcp_kr_g2b.utils.ctx_helper import as_json_text


def test_as_json_text_wraps_scalar_strings():
    # 스칼라/비표준 토큰 문자열은 JSON 통과시키지 않고 래핑
    for s in ("true", "123", "null", "NaN", "-1"):
        out = json.loads(as_json_text(s).text)
        assert out == {"raw": s}, f"{s!r} 가 래핑되지 않음"
    # 진짜 JSON 객체/배열은 통과
    assert json.loads(as_json_text('{"a":1}').text) == {"a": 1}
    assert json.loads(as_json_text("[1,2]").text) == [1, 2]


def test_cache_variant_keys_differ():
    p_all = cache_util.cache_path_for("getX", {"a": "1"}, variant="all")
    p_page = cache_util.cache_path_for("getX", {"a": "1"}, variant="p2_n500")
    assert p_all != p_page, "전체조회와 페이지 캐시 경로가 충돌함"


def _make_cache(tmp_path, monkeypatch, items):
    monkeypatch.setenv("MCP_G2B_CACHE_DIR", str(tmp_path))
    result = {"operation": "getX", "header": {"resultCode": "00"}, "items": items,
              "totalCount": len(items), "fetchedCount": len(items)}
    return cache_util.save_result("getX", {"k": "v"}, result, variant="all")


def test_cache_data_field_not_found(tmp_path, monkeypatch):
    from mcp_kr_g2b.tools.common_tools import get_g2b_cache_data
    # bidNtceNm 없는(비-bid) 캐시에 텍스트 필터를 걸면 무음 0건이 아니라 명시적 에러
    path = _make_cache(tmp_path, monkeypatch, [{"prdctClsfcNo": "1", "x": "a"}])
    out = json.loads(get_g2b_cache_data(path, field_value_substring="a").text)
    assert out.get("error") == "FIELD_NOT_FOUND"
    assert "prdctClsfcNo" in out.get("available_fields", [])


def test_cache_data_filters_with_explicit_field(tmp_path, monkeypatch):
    from mcp_kr_g2b.tools.common_tools import get_g2b_cache_data
    items = [{"bidNtceNm": "재활용 폐기물 처리"}, {"bidNtceNm": "AI 재활 동작분석"}]
    path = _make_cache(tmp_path, monkeypatch, items)
    # exclude 로 재활용 제거 → 1건
    out = json.loads(get_g2b_cache_data(path, field_name="bidNtceNm", exclude_substrings=["재활용"]).text)
    assert out["matched_count"] == 1
    assert out["items"][0]["bidNtceNm"] == "AI 재활 동작분석"
    # regex 재활(?!용) → 1건
    out2 = json.loads(get_g2b_cache_data(path, field_value_regex="재활(?!용)").text)
    assert out2["matched_count"] == 1
    # cachedAt/age 노출
    assert "cachedAt" in out and "ageSeconds" in out


def test_cache_data_clamps_offset_limit(tmp_path, monkeypatch):
    from mcp_kr_g2b.tools.common_tools import get_g2b_cache_data
    items = [{"bidNtceNm": f"n{i}"} for i in range(5)]
    path = _make_cache(tmp_path, monkeypatch, items)
    out = json.loads(get_g2b_cache_data(path, offset=-3, limit=2).text)
    assert out["offset"] == 0 and out["limit"] == 2 and out["returned"] == 2
