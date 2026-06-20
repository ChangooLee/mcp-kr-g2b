"""
선택적 의미 기반 리랭커 (opt-in)

substring 매칭(예: '재활'이 '재활용'을 포함)으로 끌려온 대량 후보를, 회사/사업 설명
질의문과의 의미 유사도로 재정렬하여 노이즈를 줄인다.

- 기본 설치에는 포함되지 않는다(`pip install "mcp-kr-g2b[ml]"`).
- sentence-transformers 는 함수 내부에서 지연 임포트하므로, 미설치 시에도
  서버 import 및 나머지 도구는 정상 동작한다.
- 모델: 기본 한국어 문장 임베딩(jhgan/ko-sroberta-multitask). G2B_RERANK_MODEL 로 변경.
"""

import os
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("mcp-kr-g2b")

_model = None


def is_available() -> bool:
    """sentence-transformers 설치 여부."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def model_name() -> str:
    return os.getenv("G2B_RERANK_MODEL", "jhgan/ko-sroberta-multitask")


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # 지연 임포트

        name = model_name()
        logger.info(f"🔎 리랭커 모델 로드: {name} (최초 1회 다운로드 발생 가능)")
        _model = SentenceTransformer(name)
    return _model


def rerank(
    query: str,
    items: List[Dict[str, Any]],
    text_field: str = "bidNtceNm",
    top_k: int = 20,
) -> List[Tuple[Dict[str, Any], float]]:
    """query 와 각 item[text_field] 의 코사인 유사도로 내림차순 정렬하여 상위 top_k 반환."""
    if not items:
        return []
    from sentence_transformers import util

    model = _get_model()
    texts = [str(it.get(text_field, "") or "") for it in items]
    emb = model.encode(texts, convert_to_tensor=True, normalize_embeddings=True, batch_size=64)
    qemb = model.encode([query], convert_to_tensor=True, normalize_embeddings=True)
    sims = util.cos_sim(qemb, emb)[0].tolist()
    scored = sorted(zip(items, sims), key=lambda x: x[1], reverse=True)
    return scored[:top_k]
