"""
조달청 나라장터/누리장터 OpenAPI 공통 HTTP 클라이언트

공공데이터포털(apis.data.go.kr) 게이트웨이 특성:
- 인증키(serviceKey)는 URL 인코딩된 값을 그대로 사용(이중 인코딩 금지). 서비스/계층에
  따라 Encoding/Decoding 형식 중 동작하는 것이 달라, 후보 wire-form 페일오버를 둔다.
- 일부 환경/서비스에서 SSL/UA 문제가 있어 curl 우선 + requests 폴백을 사용.
- 게이트웨이가 간헐적 5xx/타임아웃/HTML 점검페이지를 반환하므로 재시도+백오프를 둔다.
- type=json 을 요청해도 XML 을 반환할 수 있어 응답을 자동 판별한다.
- 페이지네이션: numOfRows / pageNo / totalCount.
"""

import json
import time
import shutil
import logging
import threading
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

_OK_CODES = {"00", "0", "000"}
_NO_DATA_CODES = {"03", "07", "3", "7"}
_KEY_ERR_CODES = {"30", "31"}
# resultCode 가 비었을 때만(헤더 파싱 실패/인증 게이트웨이 차단) 본문에서 탐지하는 토큰
_KEY_ERR_TOKENS = (
    "SERVICE_KEY_IS_NOT_REGISTERED",
    "NOT_REGISTERED_ERROR",
    "등록되지 않은 서비스",
    "인증키가 유효하지",
    "Unauthorized",
)

# (header, items, totalCount, totalCountPresent)
ParseResult = Tuple[Dict[str, str], List[Dict[str, Any]], int, bool]


class G2BAPIError(Exception):
    """조달청 OpenAPI 에러 응답."""

    def __init__(self, code: str, message: str, operation: str = ""):
        self.code = code
        self.message = message
        self.operation = operation
        super().__init__(f"[{code}] {message} (operation={operation})")


class G2BClient:
    """조달청 나라장터 OpenAPI 클라이언트(스레드 안전)."""

    def __init__(self, config: Optional[G2BConfig] = None):
        self.config = config or g2b_config
        if self.config is None:
            raise ValueError("G2BConfig 가 초기화되지 않았습니다. 서비스키 환경변수를 확인하세요.")
        self.api_key = self.config.api_key
        if not self.api_key:
            raise ValueError("조달청 OpenAPI 서비스키가 설정되지 않았습니다.")

        # 인증키 wire-form 후보(정규 %-인코딩 우선) + base_url별 성공 형식 캐시(락 보호)
        self._key_forms = self._derive_key_forms(self.api_key)
        self._key_form_idx_by_base: Dict[str, int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _derive_key_forms(raw_key: str) -> List[str]:
        raw = (raw_key or "").strip()
        try:
            decoded = unquote(raw)
        except Exception:
            decoded = raw
        encoded = quote(decoded, safe="")  # 항상 단일 %-인코딩 형식
        forms: List[str] = []
        for f in (encoded, raw, decoded):
            if f and f not in forms:
                forms.append(f)
        return forms

    # ------------------------------------------------------------------ #
    # URL / HTTP
    # ------------------------------------------------------------------ #
    def _build_url(self, base_url: str, operation: str, params: Dict[str, Any], key_form: str) -> str:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        qs = urlencode(clean, doseq=True)
        base = base_url.rstrip("/")
        url = f"{base}/{operation}" if operation else base
        sep = "&" if qs else ""
        return f"{url}?{qs}{sep}serviceKey={key_form}"

    def _curl_get(self, url: str, timeout: int) -> Optional[str]:
        """curl 호출. HTTP>=400(--fail) 또는 빈 응답이면 None 을 반환해 requests 폴백을 유도."""
        curl_path = shutil.which("curl")
        if not curl_path:
            return None
        try:
            r = subprocess.run(
                [curl_path, "-s", "-g", "--fail", "-H", f"User-Agent: {_USER_AGENT}", url],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
            )
            if r.returncode == 0 and r.stdout and r.stdout.strip():
                return r.stdout
        except Exception as e:  # pragma: no cover
            logger.debug(f"curl 호출 예외(→requests 폴백): {e}")
        return None

    def _http_get(self, url: str) -> str:
        """curl 우선 + requests 폴백, transient 오류에 재시도+지수 백오프."""
        timeout = self.config.request_timeout
        retries = max(1, int(self.config.max_retries))
        backoff = float(self.config.retry_backoff)
        verify = bool(self.config.tls_verify)
        last_err: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            txt = self._curl_get(url, timeout)
            if txt is not None and txt.strip():
                return txt
            try:
                if not verify:
                    try:
                        import urllib3

                        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                    except Exception:
                        pass
                resp = requests.get(
                    url, headers={"User-Agent": _USER_AGENT}, verify=verify, timeout=timeout
                )
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as e:
                last_err = e
                logger.warning(f"요청 실패(attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * (2 ** (attempt - 1)))

        raise last_err if last_err else RuntimeError("HTTP 요청 실패")

    # ------------------------------------------------------------------ #
    # 응답 파싱
    # ------------------------------------------------------------------ #
    def _parse_response(self, text: str) -> ParseResult:
        text = (text or "").strip()
        if not text:
            return {"resultCode": "", "resultMsg": "empty response"}, [], 0, False
        head = text[:256].lstrip().lower()
        if head.startswith("<!doctype html") or head.startswith("<html") or "<html" in head:
            return {"resultCode": "", "resultMsg": "HTML 응답(게이트웨이 점검/차단 추정)"}, [], 0, False
        try:
            if text[0] in "{[":
                return self._parse_json(text)
            return self._parse_xml(text)
        except (json.JSONDecodeError, ET.ParseError) as e:
            logger.warning(f"응답 파싱 실패: {e}; head={text[:120]!r}")
            return {"resultCode": "PARSE_ERROR", "resultMsg": str(e)}, [], 0, False

    def _parse_json(self, text: str) -> ParseResult:
        obj = json.loads(text)
        root = obj.get("response", obj) if isinstance(obj, dict) else obj
        header: Dict[str, Any] = {}
        body: Any = {}
        if isinstance(root, dict):
            header = root.get("header", {}) or {}
            body = root.get("body", root)

        if isinstance(obj, dict) and "cmmMsgHeader" in str(obj)[:200] and not header:
            cmm = self._find_key(obj, "cmmMsgHeader") or {}
            header = {
                "resultCode": str(cmm.get("returnReasonCode", "")),
                "resultMsg": str(cmm.get("errMsg") or cmm.get("returnAuthMsg", "")),
            }

        items = self._extract_items(body)
        total_raw = self._dig(body, "totalCount")
        total_present = total_raw not in (None, "")
        total = self._to_int(total_raw, default=len(items))
        return self._normalize_header(header), items, total, total_present

    def _parse_xml(self, text: str) -> ParseResult:
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
        tc = root.findtext(".//totalCount")
        total_present = tc not in (None, "")
        total = self._to_int((tc or "").strip(), default=len(items))
        return self._normalize_header(header), items, total, total_present

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
        params = dict(params or {})
        params.setdefault("type", "json")
        rows = num_of_rows or self.config.default_num_of_rows
        rows = max(1, min(int(rows), 999))
        params["numOfRows"] = rows
        params["pageNo"] = page_no
        logger.info(f"📡 G2B GET {operation} (page={page_no}) → {base_url}")
        header, items, total, total_present = self._get_with_key_failover(base_url, operation, params)
        self._raise_for_status(header, operation, allow_no_data=True)
        return {
            "operation": operation,
            "header": header,
            "items": items,
            "totalCount": total,
            "totalCountPresent": total_present,
            "pageNo": page_no,
            "numOfRows": rows,
        }

    def fetch_all(
        self,
        base_url: str,
        operation: str,
        params: Optional[Dict[str, Any]] = None,
        num_of_rows: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> Dict[str, Any]:
        params = dict(params or {})
        num_of_rows = max(1, min(int(num_of_rows or self.config.default_num_of_rows), 999))
        max_pages = max_pages or self.config.max_pages

        all_items: List[Dict[str, Any]] = []
        total_count: Optional[int] = None
        total_present = False
        header: Dict[str, str] = {}
        page_no = 1
        pages_fetched = 0
        reached_end = False
        page_error: Optional[str] = None

        while page_no <= max_pages:
            try:
                page = self.fetch_page(base_url, operation, params, num_of_rows, page_no)
            except Exception as e:
                if page_no == 1:
                    raise
                page_error = str(e)
                logger.warning(f"페이지 {page_no} 실패 → 부분결과 반환: {e}")
                break
            header = page["header"]
            if page_no == 1:
                total_count = page["totalCount"]
                total_present = page["totalCountPresent"]
            items = page["items"]
            all_items.extend(items)
            pages_fetched += 1

            if not items or len(items) < num_of_rows:
                reached_end = True
                break
            if total_present and total_count is not None and len(all_items) >= total_count:
                reached_end = True
                break
            page_no += 1

        max_pages_reached = (not reached_end) and page_error is None
        if total_present and total_count is not None:
            missing: Optional[int] = max(0, total_count - len(all_items))
        else:
            total_count = len(all_items) if reached_end else total_count
            missing = 0 if reached_end else None
        truncated = bool(max_pages_reached or page_error or (missing or 0))

        result: Dict[str, Any] = {
            "operation": operation,
            "base_url": base_url,
            "header": header,
            "request_params": {k: v for k, v in params.items() if k not in ("type", "numOfRows", "pageNo")},
            "items": all_items,
            "totalCount": total_count if total_count is not None else len(all_items),
            "totalCountPresent": total_present,
            "fetchedCount": len(all_items),
            "pagesFetched": pages_fetched,
            "maxPages": max_pages,
            "numOfRows": num_of_rows,
            "maxPagesReached": max_pages_reached,
            "missingCount": missing,
            "truncated": truncated,
        }
        if page_error:
            result["error"] = f"페이지 수집 중 오류(부분결과 반환): {page_error}"
        return result

    # ------------------------------------------------------------------ #
    # 키 형식 페일오버
    # ------------------------------------------------------------------ #
    def _get_with_key_failover(self, base_url: str, operation: str, params: Dict[str, Any]) -> ParseResult:
        with self._lock:
            start = self._key_form_idx_by_base.get(base_url, 0)
        order = [start] + [i for i in range(len(self._key_forms)) if i != start]
        last: ParseResult = ({"resultCode": "", "resultMsg": ""}, [], 0, False)
        for idx in order:
            url = self._build_url(base_url, operation, params, self._key_forms[idx])
            text = self._http_get(url)
            header, items, total, total_present = self._parse_response(text)
            if not self._is_key_error(header, text):
                with self._lock:
                    if self._key_form_idx_by_base.get(base_url) != idx:
                        self._key_form_idx_by_base[base_url] = idx
                        logger.info(f"🔑 {base_url} → 키 형식[{idx}] 사용")
                return header, items, total, total_present
            logger.warning(f"🔑 키 형식[{idx}] 거부(code={header.get('resultCode')}) → 대체 형식 시도")
            last = (header, items, total, total_present)
        return last

    @staticmethod
    def _is_key_error(header: Dict[str, str], text: str) -> bool:
        """인증키 형식/등록 오류 여부. resultCode 를 우선해 정상 응답 오탐을 방지."""
        code = str(header.get("resultCode", "")).strip()
        if code in _KEY_ERR_CODES:
            return True
        if code in _OK_CODES or code in _NO_DATA_CODES:
            return False
        if code:
            # 08(필수누락)/10/11/12/22 등 다른 명시 코드는 키 형식 문제가 아니다.
            return False
        # resultCode 가 비어 있을 때만(헤더 미파싱/게이트웨이 차단) 본문 토큰 탐지
        return any(tok in (text or "") for tok in _KEY_ERR_TOKENS)

    # ------------------------------------------------------------------ #
    # 유틸
    # ------------------------------------------------------------------ #
    def _raise_for_status(self, header: Dict[str, str], operation: str, allow_no_data: bool = True) -> None:
        code = str(header.get("resultCode", "")).strip()
        msg = str(header.get("resultMsg", "")).strip()
        if code == "" or code in _OK_CODES:
            return
        if allow_no_data and code in _NO_DATA_CODES:
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
        return body.get(key) if isinstance(body, dict) else None

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
