# 검색 의도 분류 에이전트 — 유희형/지식형/구매형 판별 + 포맷 스타일(길이·톤·구조) 결정
from typing import List, Dict, Any

from gemini_client import call_gemini_async
# ── 포맷 맵 (구 format_ai.py 통합) ────────────────────────────────────────────
from typing import Dict as _Dict

FORMAT_MAP: _Dict[str, _Dict[str, str]] = {
    "유희형": {
        "tone": (
            "친근하고 가벼운 말투로 작성하세요. "
            "이모지를 적절히 활용하고, 딱딱한 표현은 피하세요. "
            "흥미를 유발하는 표현을 사용하세요."
        ),
        "structure": (
            "핵심 내용을 짧고 임팩트 있게 전달하세요. "
            "장단점보다는 '재밌는 포인트'와 '놓치면 아쉬운 것'으로 구성하세요."
        ),
        "length": "short",
    },
    "지식형": {
        "tone": (
            "정확하고 신뢰감 있는 문체로 작성하세요. "
            "전문 용어는 간단히 풀어서 설명하고, 근거를 중시하세요."
        ),
        "structure": (
            "배경 → 핵심 내용 → 시사점 순서로 구성하세요. "
            "공통 사실과 쟁점을 모두 포함하고, 출처를 강조하세요."
        ),
        "length": "long",
    },
    "구매형": {
        "tone": (
            "실용적이고 객관적인 말투로 작성하세요. "
            "수치와 비교 표현을 활용하고, 결론을 앞에 배치하세요."
        ),
        "structure": (
            "장점과 단점을 명확히 대비해서 작성하세요. "
            "'이런 사람에게 추천' 문구를 포함하고, 광고 영상은 반드시 명시하세요."
        ),
        "length": "long",
    },
}
DEFAULT_FORMAT = FORMAT_MAP["지식형"]


from logger import get_logger
logger = get_logger(__name__)


# 분류 불가 시 기본값
_DEFAULT_INTENT = "지식형"

# 유효한 의도 타입
_VALID_INTENTS = {"유희형", "지식형", "구매형"}


async def classify_intent(
    triggered_topics: List[str],
    clicked_video_titles: List[str] = None,
) -> Dict[str, str]:
    """
    검색 의도를 분류해 intent_type을 반환.

    Args:
        triggered_topics:      오늘 2회 이상 트리거된 주제 목록
        clicked_video_titles:  오늘 클릭/시청한 영상 제목 목록

    Returns:
        {"intent_type": "유희형" | "지식형" | "구매형"}
    """
    if clicked_video_titles is None:
        clicked_video_titles = []

    if not triggered_topics:
        return {"intent_type": _DEFAULT_INTENT}

    topics_text = "\n".join(f"- {t}" for t in triggered_topics)
    titles_text = (
        "\n".join(f"- {t}" for t in clicked_video_titles)
        if clicked_video_titles
        else "- (없음)"
    )

    prompt = f"""
사용자가 오늘 유튜브에서 관심을 보인 주제와 영상 제목입니다.

[검색/관심 주제]
{topics_text}

[시청한 영상 제목]
{titles_text}

이 사람의 오늘 검색 의도를 아래 세 가지 중 하나로 분류하세요.

- 유희형: 연예, 게임, 스포츠, 일상, 예능, 웃긴 영상 등 가볍고 재미 위주
- 지식형: 기술, 과학, 학습, 뉴스, 역사, 교육, 경제 등 정보 탐색 위주
- 구매형: 제품 리뷰, 가격 비교, 언박싱, 추천, 최저가 등 구매 결정 위주

규칙:
1. 반드시 "유희형", "지식형", "구매형" 중 하나만 답하세요.
2. 다른 텍스트 없이 해당 단어 하나만 출력하세요.
"""

    try:
        result = (await call_gemini_async(prompt, temperature=0.1)).strip()
        intent = _parse_intent(result)
        logger.info(f"[intent_ai] 의도 분류 완료: {intent}")
        return _build_result(intent)
    except Exception as e:
        logger.error(f"[intent_ai] 분류 오류 — 기본값 사용: {e}")
        return _build_result(_DEFAULT_INTENT)


def _build_result(intent_type: str) -> Dict[str, Any]:
    """intent_type으로 format_style을 조회해 통합 결과 딕셔너리를 반환."""
    fmt = dict(FORMAT_MAP.get(intent_type, DEFAULT_FORMAT))
    return {"intent_type": intent_type, "format_style": fmt}


def _parse_intent(text: str) -> str:
    """
    Gemini 응답에서 의도 타입 추출.
    유효하지 않은 응답이면 기본값 반환.
    """
    # 응답 첫 줄에서 유효한 타입 탐색
    for line in text.splitlines():
        candidate = line.strip()
        if candidate in _VALID_INTENTS:
            return candidate

    # 응답에 타입 키워드가 포함된 경우 탐색
    for intent in _VALID_INTENTS:
        if intent in text:
            return intent

    return _DEFAULT_INTENT
