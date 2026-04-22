from typing import List, Dict

from agents.gemini_client import call_gemini

# 분류 불가 시 기본값
_DEFAULT_INTENT = "지식형"

# 유효한 의도 타입
_VALID_INTENTS = {"유희형", "지식형", "구매형"}


def classify_intent(
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
        result = call_gemini(prompt, temperature=0.1).strip()
        intent = _parse_intent(result)
        print(f"[intent_ai] 의도 분류 완료: {intent}")
        return {"intent_type": intent}
    except Exception as e:
        print(f"[intent_ai] 분류 오류 — 기본값 사용: {e}")
        return {"intent_type": _DEFAULT_INTENT}


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
