"""
조회 결과 캐싱 유틸리티

mcp-kr-realestate 의 캐시 전략을 차용한다:
- API 전체 조회 결과(raw items)를 JSON 파일로 저장하고, 도구는 요약/미리보기만 반환.
- LLM 컨텍스트 효율을 위해 대량 데이터는 파일로 두고 필요한 부분만 로드/필터한다.
"""

import os
import sys
import json
import hashlib
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_cache_dir() -> Path:
    """크로스 플랫폼 사용자 캐시 디렉토리.

    우선순위:
    1. MCP_G2B_CACHE_DIR 환경변수
    2. 패키지 내부 utils/cache/raw_data (기본)
    3. OS 표준 사용자 캐시 디렉토리
    4. 임시 디렉토리(최후)
    """
    env_dir = os.environ.get("MCP_G2B_CACHE_DIR")
    if env_dir:
        p = Path(env_dir)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass

    pkg_cache = Path(__file__).parent / "cache" / "raw_data"
    try:
        pkg_cache.mkdir(parents=True, exist_ok=True)
        return pkg_cache
    except Exception:
        pass

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        os_dir = Path(base) / "mcp-kr-g2b-cache"
    else:
        os_dir = Path(os.path.expanduser("~/.cache/mcp-kr-g2b"))
    try:
        os_dir.mkdir(parents=True, exist_ok=True)
        return os_dir
    except Exception:
        pass

    tmp = Path(tempfile.gettempdir()) / "mcp-kr-g2b-cache"
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp


def make_cache_key(params: Optional[Dict[str, Any]]) -> str:
    """요청 파라미터로부터 안정적인 짧은 해시 키 생성."""
    if not params:
        return "all"
    norm = {k: v for k, v in sorted(params.items()) if v is not None and v != ""}
    if not norm:
        return "all"
    raw = json.dumps(norm, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def cache_path_for(operation: str, params: Optional[Dict[str, Any]]) -> Path:
    """operation + 파라미터 해시로 캐시 파일 경로 생성."""
    key = make_cache_key(params)
    return get_cache_dir() / f"{operation}_{key}.json"


def save_result(operation: str, params: Optional[Dict[str, Any]], result: Dict[str, Any]) -> str:
    """fetch_all 결과(dict)를 JSON 파일로 저장하고 경로 반환."""
    path = cache_path_for(operation, params)
    payload = {
        "operation": operation,
        "request_params": params or {},
        "totalCount": result.get("totalCount"),
        "fetchedCount": result.get("fetchedCount", len(result.get("items", []))),
        "header": result.get("header", {}),
        "items": result.get("items", []),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return str(path)


def load_result(path: str) -> Optional[Dict[str, Any]]:
    """캐시 파일 로드."""
    p = Path(path)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def summarize_result(
    result: Dict[str, Any],
    saved_path: str,
    preview_n: int = 5,
) -> Dict[str, Any]:
    """대량 item 을 그대로 반환하지 않고 요약 + 미리보기 + 캐시 경로를 반환."""
    items: List[Dict[str, Any]] = result.get("items", [])
    fields = sorted({k for it in items[:50] if isinstance(it, dict) for k in it.keys()})
    header = result.get("header", {}) or {}
    return {
        "operation": result.get("operation"),
        "resultCode": header.get("resultCode", ""),
        "resultMsg": header.get("resultMsg", ""),
        "totalCount": result.get("totalCount"),
        "fetchedCount": result.get("fetchedCount", len(items)),
        "pagesFetched": result.get("pagesFetched"),
        "truncated": result.get("truncated", False),
        "request_params": result.get("request_params", {}),
        "result_fields": fields,
        "preview": items[:preview_n],
        "cache_file": saved_path,
        "hint": (
            "전체 데이터는 cache_file 에 저장되어 있습니다. "
            "get_g2b_cache_data 도구로 필드 필터링/페이지 조회가 가능합니다."
        ),
    }
