from typing import List, Dict, Any

from agents.gemini_client import call_gemini
from agents.format_ai import FORMAT_MAP, DEFAULT_FORMAT

# 분류 불가 시 기본값
_DEFAULT_INTENT = "지식형"

# 유효한 의도 타입
_VALID_INTENTS = {"유희형", "지식형", "구매형"}


def classify_intent(
    triggered_topics: List[str],
    clicked_video_titles: List[str] = None,
) -> Dict[str, Any]:
    """
    검색 의도를 분류해 intent_type과 format_style을 함께 반환.

    format_ai는 Gemini를 호출하지 않는 단순 딕셔너리 조회이므로
    별도 호출 없이 여기서 직접 처리합니다.

    Args:
        triggered_topics:      오늘 2회 이상 트리거된 주제 목록
        clicked_video_titles:  오늘 클릭/시청한 영상 제목 목록

    Returns:
        {
            "intent_type":  "유희형" | "지식형" | "구매형",
            "format_style": {"tone": str, "structure": str, "length": str},
        }
    """
    if clicked_video_titles is None:
        clicked_video_titles = []

    if not triggered_topics:
        return _build_result(_DEFAULT_INTENT)

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
        result = call_gemini(prompt, temperature=0.1).strip()
        intent = _parse_intent(result)
        print(f"[intent_ai] 의도 분류 완료: {intent}")
        return _build_result(intent)
    except Exception as e:
        print(f"[intent_ai] 분류 오류 — 기본값 사용: {e}")
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
    for line in text.splitlines():
        candidate = line.strip()
        if candidate in _VALID_INTENTS:
            return candidate

    for intent in _VALID_INTENTS:
        if intent in text:
            return intent

    return _DEFAULT_INTENT
