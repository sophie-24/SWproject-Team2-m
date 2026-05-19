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

분류의 목표는 단순히 주제를 나누는 것이 아니라,
사용자가 최종 뉴스레터에서 어떤 방식의 정보를 기대하는지 판단하는 것입니다.

[분류 기준]

1. 유희형
- 사용자가 콘텐츠를 가볍게 소비하거나, 화제성/반응/재미 포인트를 알고 싶어 하는 경우
- 연예인, 아이돌, 유튜버, 방송, 예능, 드라마, 영화, 게임, 스포츠, 밈, 챌린지, 브이로그, 일상, 팬 반응, 근황, 하이라이트 등이 중심인 경우
- 결과물은 화제성, 재미 포인트, 인물/콘텐츠 중심 정보, 팬 반응, 트렌드 맥락 중심으로 구성되는 것이 적절함
- 예시: "Lisa Lifestyle", "뉴진스 직캠 반응", "침착맨 레전드", "환승연애 명장면", "아이돌 공항패션", "롤드컵 하이라이트"

2. 지식형
- 사용자가 어떤 주제를 이해하거나 배우거나 실천 방법을 알고 싶어 하는 경우
- 기술, 과학, 학습, 뉴스, 역사, 교육, 경제, 사회, 건강, 운동법, 자기관리, 공부법, 커리어, 문제 해결, 개념 설명, 원리, 이유, 방법, 차이 등이 중심인 경우
- 결과물은 배경, 핵심 개념, 원인, 관점 차이, 실천 팁, 주의점 중심으로 구성되는 것이 적절함
- 예시: "20대 자기관리", "생성형 AI 원리", "러닝 무릎 통증 이유", "대학생 시간관리 방법", "MoE 오케스트레이션 차이", "금리 인하 영향"

3. 구매형
- 사용자가 제품, 서비스, 장소, 앱, 브랜드, 기기 등을 비교하거나 선택하려는 경우
- 제품 리뷰, 가격 비교, 언박싱, 추천, 최저가, 가성비, 후기, 장단점, 성능, 사용성, 할인, 살까 말까, vs, TOP, 입문용 등이 중심인 경우
- 결과물은 비교 기준, 장점, 단점, 가격, 성능, 사용성, 적합한 사용자, 구매 전 확인점 중심으로 구성되는 것이 적절함
- 예시: "아이폰 16 리뷰", "맥북 에어 vs 그램", "대학생 노트북 추천", "올리브영 세일 기초템 추천", "나이키 러닝화 후기", "유튜브 프리미엄 싸게 쓰는 법"

[애매한 경우 판단 규칙]

1. 제품명, 서비스명, 브랜드명, 가격, 리뷰, 후기, 비교, 가성비, 추천, 구매 판단이 강하면 구매형으로 분류하세요.
2. 인물, 연예인, 아이돌, 유튜버, 방송, 영화, 드라마, 게임, 스포츠, 밈, 팬 반응, 근황, 하이라이트가 중심이면 유희형으로 분류하세요.
3. 개념, 방법, 이유, 원리, 문제 해결, 학습, 자기관리, 생활 습관, 실천 팁이 중심이면 지식형으로 분류하세요.
4. "추천"이 포함되어도 추천 대상이 제품/서비스/장소/앱이면 구매형, 방법/습관/공부법/루틴이면 지식형, 영화/드라마/예능/유튜브 콘텐츠/음악이면 유희형으로 분류하세요.
5. "리뷰"가 포함되어도 리뷰 대상이 제품/서비스/장소이면 구매형, 영화/드라마/예능/유튜브 콘텐츠이면 유희형으로 분류하세요.
6. 검색어가 짧고 모호한 경우, 제품명은 구매형, 인물/콘텐츠명은 유희형, 일반 주제어는 지식형으로 분류하세요.
7. 여러 의도가 섞여 있으면 오늘의 검색/시청 기록에서 가장 많이 반복되거나 가장 강하게 드러나는 의도를 선택하세요.

[출력 규칙]

1. 반드시 "유희형", "지식형", "구매형" 중 하나만 답하세요.
2. 다른 텍스트, 설명, 이유, JSON, 마크다운 없이 해당 단어 하나만 출력하세요.
3. 확신이 낮더라도 세 가지 중 가장 가까운 하나를 반드시 선택하세요.
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
