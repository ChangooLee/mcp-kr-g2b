"""
조회 결과 캐싱 유틸리티

mcp-kr-realestate 의 캐시 전략을 차용한다:
- API 전체 조회 결과(raw items)를 JSON 파일로 저장하고, 도구는 요약/미리보기만 반환.
- LLM 컨텍스트 효율을 위해 대량 데이터는 파일로 두고 필요한 부분만 로드/필터한다.

견고성:
- 캐시 키에 호출 변형(variant: 전체조회 vs 특정 페이지)을 포함해 덮어쓰기 충돌 방지.
- cachedAt 타임스탬프로 신선도(age) 판단 가능.
- 임시파일+os.replace 로 원자적 기록(부분 손상/경합 방지).
"""

import os
import sys
import json
import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_cache_dir() -> Path:
    """크로스 플랫폼 사용자 캐시 디렉토리.

    우선순위: MCP_G2B_CACHE_DIR → 패키지 내부(utils/_cache_store/raw_data) →
    OS 표준 사용자 캐시 → 임시 디렉토리.
    (디렉토리명을 cache.py 모듈과 겹치지 않게 _cache_store 로 둔다.)
    """
    env_dir = os.environ.get("MCP_G2B_CACHE_DIR")
    if env_dir:
        p = Path(env_dir)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass

    pkg_cache = Path(__file__).parent / "_cache_store" / "raw_data"
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


def cache_path_for(operation: str, params: Optional[Dict[str, Any]], variant: str = "all") -> Path:
    """operation + 파라미터 해시 + 호출 변형(variant)으로 캐시 파일 경로 생성."""
    key = make_cache_key(params)
    safe_variant = "".join(c for c in str(variant) if c.isalnum() or c in "_-") or "all"
    return get_cache_dir() / f"{operation}_{key}_{safe_variant}.json"


def save_result(
    operation: str,
    params: Optional[Dict[str, Any]],
    result: Dict[str, Any],
    variant: str = "all",
) -> str:
    """fetch 결과(dict)를 JSON 파일로 원자적으로 저장하고 경로 반환."""
    path = cache_path_for(operation, params, variant)
    payload = {
        "operation": operation,
        "request_params": params or {},
        "cachedAt": datetime.now(timezone.utc).isoformat(),
        "totalCount": result.get("totalCount"),
        "fetchedCount": result.get("fetchedCount", len(result.get("items", []))),
        "truncated": result.get("truncated", False),
        "maxPagesReached": result.get("maxPagesReached", False),
        "missingCount": result.get("missingCount"),
        "header": result.get("header", {}),
        "items": result.get("items", []),
    }
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return str(path)


def load_result(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def age_seconds(cached_at: Optional[str]) -> Optional[float]:
    """ISO8601 cachedAt 으로부터 경과 초. 파싱 불가 시 None."""
    if not cached_at:
        return None
    try:
        dt = datetime.fromisoformat(cached_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def summarize_result(result: Dict[str, Any], saved_path: str, preview_n: int = 5) -> Dict[str, Any]:
    """대량 item 대신 요약 + 미리보기 + 캐시 경로 + 신선도/절단 안내를 반환."""
    items: List[Dict[str, Any]] = result.get("items", [])
    fields = sorted({k for it in items[:50] if isinstance(it, dict) for k in it.keys()})
    header = result.get("header", {}) or {}
    truncated = result.get("truncated", False)
    summary: Dict[str, Any] = {
        "operation": result.get("operation"),
        "resultCode": header.get("resultCode", ""),
        "resultMsg": header.get("resultMsg", ""),
        "totalCount": result.get("totalCount"),
        "totalCountKnown": result.get("totalCountPresent", True),
        "fetchedCount": result.get("fetchedCount", len(items)),
        "pagesFetched": result.get("pagesFetched"),
        "truncated": truncated,
        "maxPagesReached": result.get("maxPagesReached", False),
        "missingCount": result.get("missingCount"),
        "cachedAt": datetime.now(timezone.utc).isoformat(),
        "request_params": result.get("request_params", {}),
        "result_fields": fields,
        "preview": items[:preview_n],
        "cache_file": saved_path,
        "hint": (
            "전체 데이터는 cache_file 에 저장됨. get_g2b_cache_data 로 필드 필터/페이지/재정렬 조회 가능."
        ),
    }
    if truncated:
        summary["truncation_hint"] = (
            "결과가 일부만 수집됨(max_pages 도달 또는 페이지 오류). "
            "조회 기간을 좁히거나 G2B_MAX_PAGES 를 늘려 재조회하세요."
        )
    if result.get("error"):
        summary["warning_error"] = result["error"]
    return summary
