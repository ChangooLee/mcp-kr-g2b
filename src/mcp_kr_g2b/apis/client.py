"""
조달청 나라장터/누리장터 OpenAPI 공통 HTTP 클라이언트

공공데이터포털(apis.data.go.kr) 게이트웨이의 특성:
- 인증키(serviceKey)는 URL 인코딩된 값을 그대로 사용해야 한다.
  (requests의 params= 로 전달하면 이중 인코딩되므로, 완성된 URL 문자열로 호출)
- 일부 환경/서비스에서 SSL/UA 문제가 있어 curl 우선 호출 + requests 폴백을 사용.
- type=json 을 요청해도 서비스에 따라 XML을 반환할 수 있어, 응답을 자동 판별한다.
- 페이지네이션: numOfRows / pageNo / totalCount.

mcp-kr-realestate 의 데이터포털 호출 방식(curl 우선 + requests 폴백 + 페이지네이션)과
mcp-opendart 의 클라이언트 구조를 결합하였다.
"""

import io
import json
import shutil
import logging
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, quote, unquote

import requests

from ..config import G2BConfig, g2b_config

logger = logging.getLogger("mcp-kr-g2b")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 공공데이터포털 정상 결과 코드
_OK_CODES = {"00", "0", "000"}


class G2BAPIError(Exception):
    """조달청 OpenAPI 에러 응답."""

    def __init__(self, code: str, message: str, operation: str = ""):
        self.code = code
        self.message = message
        self.operation = operation
        super().__init__(f"[{code}] {message} (operation={operation})")


class G2BClient:
    """조달청 나라장터 OpenAPI 클라이언트."""

    def __init__(self, config: Optional[G2BConfig] = None):
        self.config = config or g2b_config
        if self.config is None:
            raise ValueError(
                "G2BConfig 가 초기화되지 않았습니다. 서비스키 환경변수를 확인하세요."
            )
        self.api_key = self.config.api_key
        if not self.api_key:
            raise ValueError("조달청 OpenAPI 서비스키가 설정되지 않았습니다.")

        # 공공데이터포털 인증키는 서비스/HTTP 계층에 따라 Encoding/Decoding 형식 중
        # 동작하는 형식이 다르다. 사용자가 어떤 형식을 넣든 동작하도록 후보 wire-form 을
        # 도출하고(정규 인코딩 우선), 키 오류 시 대체 형식으로 자동 재시도한다.
        self._key_forms = self._derive_key_forms(self.api_key)
        self._key_form_idx_by_base: Dict[str, int] = {}

    @staticmethod
    def _derive_key_forms(raw_key: str) -> list:
        """입력 키로부터 시도할 serviceKey wire-form 목록을 생성(정규 인코딩 우선)."""
        raw = (raw_key or "").strip()
        try:
            decoded = unquote(raw)
        except Exception:
            decoded = raw
        encoded = quote(decoded, safe="")  # 항상 단일 %-인코딩 형식
        forms = []
        for f in (encoded, raw, decoded):
            if f and f not in forms:
                forms.append(f)
        return forms

    # ------------------------------------------------------------------ #
    # URL / HTTP
    # ------------------------------------------------------------------ #
    def _build_url(self, base_url: str, operation: str, params: Dict[str, Any], key_form: str) -> str:
        """serviceKey 를 제외한 파라미터를 인코딩하고, 인증키 wire-form 을 원문 그대로 부착."""
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        qs = urlencode(clean, doseq=True)
        base = base_url.rstrip("/")
        url = f"{base}/{operation}" if operation else base
        sep = "&" if qs else ""
        return f"{url}?{qs}{sep}serviceKey={key_form}"

    @staticmethod
    def _is_key_error(header: Dict[str, str], text: str) -> bool:
        """인증키 형식/등록 오류 여부(대체 형식 재시도 트리거)."""
        code = str(header.get("resultCode", "")).strip()
        if code in {"30", "31"}:
            return True
        t = text or ""
        for s in (
            "SERVICE_KEY_IS_NOT_REGISTERED",
            "NOT_REGISTERED",
            "Unauthorized",
            "등록되지",
            "서비스키가",
            "인증키가 유효",
        ):
            if s in t:
                return True
        return False

    def _get_with_key_failover(self, base_url: str, operation: str, params: Dict[str, Any]) -> Tuple[Dict[str, str], List[Dict[str, Any]], int]:
        """캐시된 키 형식부터 시도하고, 키 오류 시 대체 형식으로 재시도하며 성공 형식을 캐시."""
        start = self._key_form_idx_by_base.get(base_url, 0)
        order = [start] + [i for i in range(len(self._key_forms)) if i != start]
        last: Tuple[Dict[str, str], List[Dict[str, Any]], int] = ({"resultCode": "", "resultMsg": ""}, [], 0)
        for idx in order:
            url = self._build_url(base_url, operation, params, self._key_forms[idx])
            text = self._http_get(url)
            header, items, total = self._parse_response(text)
            if not self._is_key_error(header, text):
                if self._key_form_idx_by_base.get(base_url) != idx:
                    self._key_form_idx_by_base[base_url] = idx
                    logger.info(f"🔑 {base_url} → 키 형식[{idx}] 사용")
                return header, items, total
            logger.warning(f"🔑 키 형식[{idx}] 거부(code={header.get('resultCode')}) → 대체 형식 시도")
            last = (header, items, total)
        return last

    def _http_get(self, url: str) -> str:
        """curl 우선, 실패 시 requests 폴백으로 응답 본문(text)을 반환."""
        timeout = self.config.request_timeout
        curl_path = shutil.which("curl")
        if curl_path:
            try:
                result = subprocess.run(
                    [curl_path, "-s", "-g", "-H", f"User-Agent: {_USER_AGENT}", url],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding="utf-8",
                )
                if result.returncode == 0 and result.stdout and result.stdout.strip():
                    return result.stdout
                logger.debug(f"curl 빈 응답/실패(rc={result.returncode}), requests 폴백")
            except Exception as e:  # pragma: no cover
                logger.debug(f"curl 호출 예외, requests 폴백: {e}")

        try:  # requests 폴백 (SSL 검증 경고 무시)
            import urllib3

            urllib3.disable_warnings()
        except Exception:
            pass
        resp = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, verify=False, timeout=timeout
        )
        resp.raise_for_status()
        return resp.text

    # ------------------------------------------------------------------ #
    # 응답 파싱
    # ------------------------------------------------------------------ #
    def _parse_response(self, text: str) -> Tuple[Dict[str, str], List[Dict[str, Any]], int]:
        """응답 본문을 (header, items, totalCount) 로 정규화. JSON/XML 자동 판별."""
        text = (text or "").strip()
        if not text:
            return {"resultCode": "", "resultMsg": "empty response"}, [], 0
        first = text[0]
        if first in "{[":
            return self._parse_json(text)
        return self._parse_xml(text)

    def _parse_json(self, text: str) -> Tuple[Dict[str, str], List[Dict[str, Any]], int]:
        obj = json.loads(text)
        # 공공데이터포털 표준: {"response": {"header": {...}, "body": {...}}}
        root = obj.get("response", obj) if isinstance(obj, dict) else obj
        header: Dict[str, str] = {}
        body: Any = {}
        if isinstance(root, dict):
            header = root.get("header", {}) or {}
            body = root.get("body", root)

        # 에러 envelope (cmmMsgHeader) 처리
        if isinstance(obj, dict) and "cmmMsgHeader" in str(obj)[:200] and not header:
            cmm = self._find_key(obj, "cmmMsgHeader") or {}
            header = {
                "resultCode": str(cmm.get("returnReasonCode", "")),
                "resultMsg": str(cmm.get("errMsg") or cmm.get("returnAuthMsg", "")),
            }

        items = self._extract_items(body)
        total = self._to_int(self._dig(body, "totalCount"), default=len(items))
        return self._normalize_header(header), items, total

    def _parse_xml(self, text: str) -> Tuple[Dict[str, str], List[Dict[str, Any]], int]:
        root = ET.fromstring(text)
        header = {
            "resultCode": (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip(),
            "resultMsg": (root.findtext(".//resultMsg") or root.findtext(".//errMsg") or root.findtext(".//returnAuthMsg") or "").strip(),
        }
        items: List[Dict[str, Any]] = []
        for item in root.findall(".//item"):
            rec: Dict[str, Any] = {}
            for child in item:
                tag = child.tag.split("}")[-1]
                rec[tag] = child.text.strip() if child.text else None
            if rec:
                items.append(rec)
        total = self._to_int((root.findtext(".//totalCount") or "").strip(), default=len(items))
        return self._normalize_header(header), items, total

    # ------------------------------------------------------------------ #
    # 단건/전체 조회
    # ------------------------------------------------------------------ #
    def fetch_page(
        self,
        base_url: str,
        operation: str,
        params: Optional[Dict[str, Any]] = None,
        num_of_rows: Optional[int] = None,
        page_no: int = 1,
    ) -> Dict[str, Any]:
        """단일 페이지 조회."""
        params = dict(params or {})
        params.setdefault("type", "json")
        # 공공데이터포털은 numOfRows 최대 999. 1000 이상이면 서비스가 기본값(10)으로
        # 떨어뜨리는 사례가 있어 [1, 999] 로 클램프한다.
        rows = num_of_rows or self.config.default_num_of_rows
        params["numOfRows"] = max(1, min(int(rows), 999))
        params["pageNo"] = page_no
        logger.info(f"📡 G2B GET {operation} (page={page_no}) → {base_url}")
        header, items, total = self._get_with_key_failover(base_url, operation, params)
        self._raise_for_status(header, operation, allow_no_data=True)
        return {
            "operation": operation,
            "header": header,
            "items": items,
            "totalCount": total,
            "pageNo": page_no,
            "numOfRows": params["numOfRows"],
        }

    def fetch_all(
        self,
        base_url: str,
        operation: str,
        params: Optional[Dict[str, Any]] = None,
        num_of_rows: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> Dict[str, Any]:
        """totalCount 까지 모든 페이지를 순회하여 전체 item 을 수집."""
        params = dict(params or {})
        num_of_rows = num_of_rows or self.config.default_num_of_rows
        max_pages = max_pages or self.config.max_pages

        all_items: List[Dict[str, Any]] = []
        total_count: Optional[int] = None
        header: Dict[str, str] = {}
        page_no = 1
        pages_fetched = 0

        while page_no <= max_pages:
            page = self.fetch_page(base_url, operation, params, num_of_rows, page_no)
            header = page["header"]
            if total_count is None:
                total_count = page["totalCount"]
            items = page["items"]
            all_items.extend(items)
            pages_fetched += 1

            if not items:
                break
            if total_count is not None and len(all_items) >= total_count:
                break
            page_no += 1

        return {
            "operation": operation,
            "base_url": base_url,
            "header": header,
            "request_params": {k: v for k, v in params.items() if k not in ("type", "numOfRows", "pageNo")},
            "items": all_items,
            "totalCount": total_count if total_count is not None else len(all_items),
            "fetchedCount": len(all_items),
            "pagesFetched": pages_fetched,
            "truncated": bool(total_count and len(all_items) < total_count),
        }

    # ------------------------------------------------------------------ #
    # 유틸
    # ------------------------------------------------------------------ #
    def _raise_for_status(self, header: Dict[str, str], operation: str, allow_no_data: bool = True) -> None:
        code = str(header.get("resultCode", "")).strip()
        msg = str(header.get("resultMsg", "")).strip()
        if code == "" or code in _OK_CODES:
            return
        # No Data(03/07) 는 정상 흐름으로 간주(빈 결과)
        if allow_no_data and code in {"03", "07", "3", "7"}:
            return
        raise G2BAPIError(code, msg or "조달청 OpenAPI 오류", operation)

    @staticmethod
    def _normalize_header(header: Dict[str, Any]) -> Dict[str, str]:
        if not isinstance(header, dict):
            return {"resultCode": "", "resultMsg": ""}
        return {
            "resultCode": str(header.get("resultCode", header.get("returnReasonCode", ""))),
            "resultMsg": str(header.get("resultMsg", header.get("errMsg", ""))),
        }

    @staticmethod
    def _extract_items(body: Any) -> List[Dict[str, Any]]:
        """body.items 의 다양한 형태(list / {item:[...]} / {item:{...}} / "")를 list 로 정규화."""
        if body is None:
            return []
        items = body.get("items") if isinstance(body, dict) else body
        if items in (None, "", []):
            return []
        if isinstance(items, dict):
            inner = items.get("item", items)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
            if isinstance(inner, dict):
                return [inner]
            return []
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
        return []

    @staticmethod
    def _dig(body: Any, key: str) -> Any:
        if isinstance(body, dict):
            return body.get(key)
        return None

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(str(value).replace(",", "").strip())
        except (ValueError, TypeError):
            return default

    @classmethod
    def _find_key(cls, obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                found = cls._find_key(v, key)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = cls._find_key(v, key)
                if found is not None:
                    return found
        return None
