"""
[AI 3] category_ai.py — 카테고리 분석

역할:
- 검색어 + 영상 5개 제목으로 검색 의도 분류
  (정보탐색형 / 비교구매형 / 학습튜토리얼형)
- UI 구성 방향 결정 (레이아웃 힌트 반환)
"""

import os
import re
from typing import List, Dict, Any

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_model = genai.GenerativeModel("gemini-2.5-flash-lite")

CATEGORY_TYPES = ("정보탐색형", "비교구매형", "학습튜토리얼형")

# 카테고리별 UI 레이아웃 힌트
LAYOUT_HINTS: Dict[str, Dict[str, str]] = {
    "정보탐색형": {
        "layout": "summary_focus",
        "description": "핵심 요약과 공통 사실을 상단에 크게 배치. 쟁점은 접을 수 있는 섹션으로.",
        "primary_section": "summary",
        "secondary_section": "common_facts",
        "show_controversy": True,
    },
    "비교구매형": {
        "layout": "comparison_table",
        "description": "영상별 주요 주장을 비교 카드 형태로 나열. 추천 영상 순위를 강조.",
        "primary_section": "recommended_videos",
        "secondary_section": "controversies",
        "show_controversy": True,
    },
    "학습튜토리얼형": {
        "layout": "step_guide",
        "description": "공통 사실을 순서형 리스트로 표시. 신뢰도 높은 영상을 최상단에 배치.",
        "primary_section": "common_facts",
        "secondary_section": "recommended_videos",
        "show_controversy": False,
    },
}


def _call_gemini(prompt: str, temperature: float = 0.3) -> str:
    response = _model.generate_content(
        prompt,
        generation_config={"temperature": temperature},
    )
    if response.text is None:
        finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        raise ValueError(f"Gemini 응답 없음 (finish_reason: {finish})")
    return response.text


def classify_category(
    keyword: str,
    video_titles: List[str],
) -> Dict[str, Any]:
    """
    검색어와 영상 제목으로 검색 의도를 분류하고 UI 힌트를 반환.

    Args:
        keyword: 검색 키워드
        video_titles: 영상 제목 목록 (최대 5개)

    Returns:
        {
            "category": str,           # 정보탐색형 / 비교구매형 / 학습튜토리얼형
            "confidence": float,       # 0.0~1.0
            "reason": str,             # 분류 근거 한 문장
            "layout": Dict[str, Any],  # UI 구성 힌트
        }
    """
    titles_text = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(video_titles))

    prompt = f"""
사용자가 유튜브에서 "{keyword}" 를 검색했습니다.
검색 결과로 나온 영상 제목들입니다:

{titles_text}

이 검색의 의도를 아래 세 가지 중 하나로 분류하세요.

- 정보탐색형: 특정 사실이나 현황을 알고 싶어하는 검색 (예: "기후변화 원인", "코로나 증상")
- 비교구매형: 제품/서비스를 비교하거나 구매 결정을 돕는 검색 (예: "아이폰 vs 갤럭시", "최고의 노트북 추천")
- 학습튜토리얼형: 방법이나 기술을 배우려는 검색 (예: "파이썬 입문", "포토샵 사용법")

아래 형식으로만 답하세요.

[카테고리]
정보탐색형, 비교구매형, 학습튜토리얼형 중 하나만 작성.

[신뢰도]
0.0~1.0 사이 소수 하나만 작성.

[근거]
분류 근거를 한 문장으로 작성.
"""

    try:
        text = _call_gemini(prompt, temperature=0.2)
    except Exception as e:
        print(f"  [카테고리 분류 오류]: {e}")
        return _fallback_result(keyword)

    category = _parse_category(text)
    confidence = _parse_confidence(text)
    reason = _parse_section(text, "근거")

    layout = LAYOUT_HINTS.get(category, LAYOUT_HINTS["정보탐색형"])

    print(f"[category] '{keyword}' → {category} (신뢰도: {confidence})")

    return {
        "category": category,
        "confidence": confidence,
        "reason": reason,
        "layout": layout,
    }


def _parse_section(text: str, section_name: str) -> str:
    pattern = rf"\[{section_name}\]\s*(.*?)(?=\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_category(text: str) -> str:
    section = _parse_section(text, "카테고리")
    for cat in CATEGORY_TYPES:
        if cat in section:
            return cat
    # 섹션 파싱 실패 시 전체 텍스트에서 탐색
    for cat in CATEGORY_TYPES:
        if cat in text:
            return cat
    return "정보탐색형"


def _parse_confidence(text: str) -> float:
    section = _parse_section(text, "신뢰도")
    match = re.search(r"[01]\.\d+|[01]", section)
    if match:
        return round(max(0.0, min(1.0, float(match.group()))), 2)
    return 0.7


def _fallback_result(keyword: str) -> Dict[str, Any]:
    """Gemini 호출 실패 시 기본값 반환"""
    return {
        "category": "정보탐색형",
        "confidence": 0.5,
        "reason": "분류 실패로 기본값 사용",
        "layout": LAYOUT_HINTS["정보탐색형"],
    }
