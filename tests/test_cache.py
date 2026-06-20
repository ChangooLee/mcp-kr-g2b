"""캐시 유틸 단위 테스트."""
from mcp_kr_g2b.utils import cache


def test_make_cache_key_stable_and_order_independent():
    a = cache.make_cache_key({"x": "1", "y": "2"})
    b = cache.make_cache_key({"y": "2", "x": "1"})
    assert a == b
    assert cache.make_cache_key({}) == "all"
    assert cache.make_cache_key(None) == "all"
    assert cache.make_cache_key({"x": "1"}) != cache.make_cache_key({"x": "2"})


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_G2B_CACHE_DIR", str(tmp_path))
    result = {
        "operation": "getX",
        "header": {"resultCode": "00", "resultMsg": "정상"},
        "items": [{"a": "1"}, {"a": "2"}],
        "totalCount": 2,
        "fetchedCount": 2,
    }
    path = cache.save_result("getX", {"k": "v"}, result)
    loaded = cache.load_result(path)
    assert loaded["totalCount"] == 2
    assert len(loaded["items"]) == 2
    assert loaded["operation"] == "getX"


def test_summarize_result_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_G2B_CACHE_DIR", str(tmp_path))
    items = [{"bidNtceNm": f"공고{i}", "x": i} for i in range(20)]
    result = {
        "operation": "getX",
        "header": {"resultCode": "00", "resultMsg": "정상"},
        "items": items,
        "totalCount": 20,
        "fetchedCount": 20,
    }
    path = cache.save_result("getX", {}, result)
    summary = cache.summarize_result(result, path, preview_n=5)
    assert summary["totalCount"] == 20
    assert summary["resultCode"] == "00"
    assert len(summary["preview"]) == 5
    assert "bidNtceNm" in summary["result_fields"]
    assert summary["cache_file"] == path


def test_get_cache_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_G2B_CACHE_DIR", str(tmp_path / "c"))
    d = cache.get_cache_dir()
    assert str(d).endswith("c")
    assert d.exists()
