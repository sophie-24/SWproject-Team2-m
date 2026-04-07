# backend/agents/cluster_ai.py
"""
[AI 1] cluster_ai.py — 주제 클러스터링

역할:
- 오늘 수집된 검색어/영상 제목을 의미적으로 그룹핑
- 2회 이상 트리거된 키워드들을 주제 단위로 묶음
- orchestrator.py의 Step 1에서 호출
"""

import os
import json
import re
from typing import List, Dict, Any

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_model = genai.GenerativeModel("gemini-2.5-flash-lite")


def _call_gemini(prompt: str) -> str:
    response = _model.generate_content(
        prompt,
        generation_config={"temperature": 0.2},
    )
    if response.text is None:
        finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        raise ValueError(f"Gemini 응답 없음 (finish_reason: {finish})")
    return response.text


def cluster_topics(raw_keywords: List[str]) -> List[Dict[str, Any]]:
    """
    오늘 수집된 검색어/영상 제목을 주제별로 클러스터링.

    INPUT:
      - raw_keywords: List[str] — 오늘 수집된 검색어/영상 제목 전체

    OUTPUT:
      - clusters: List[Dict]
        예: [
          {
            "topic": "토리든 저분자 세럼",
            "keywords": ["토리든", "저분자세럼", "히알루론산"]
          },
          {
            "topic": "아이폰 16",
            "keywords": ["아이폰16", "iPhone 16 리뷰"]
          }
        ]
    """
    if not raw_keywords:
        return []

    # 중복 제거
    unique_keywords = list(dict.fromkeys(raw_keywords))

    print(f"[cluster_ai] 클러스터링 시작 — {len(unique_keywords)}개 키워드")

    keywords_text = "\n".join(f"- {kw}" for kw in unique_keywords)

    prompt = f"""
다음은 사용자가 오늘 유튜브에서 검색하거나 시청한 키워드/영상 제목 목록입니다.

{keywords_text}

이 키워드들을 의미적으로 유사한 주제끼리 묶어 클러스터링하세요.

규칙:
1. 비슷한 주제끼리 하나의 클러스터로 묶으세요
2. 각 클러스터에 대표 주제명(topic)을 붙이세요
3. 주제명은 검색하기 좋은 간결한 한국어로 작성하세요
4. 반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이)

응답 형식:
[
  {{
    "topic": "대표 주제명",
    "keywords": ["관련 키워드1", "관련 키워드2"]
  }}
]
"""

    try:
        text = _call_gemini(prompt)
        clusters = _parse_clusters(text)
    except Exception as e:
        print(f"[cluster_ai] Gemini 오류 — 폴백 실행: {e}")
        clusters = _fallback_cluster(unique_keywords)

    print(f"[cluster_ai] 완료 — {len(clusters)}개 클러스터 생성")
    return clusters


def _parse_clusters(text: str) -> List[Dict[str, Any]]:
    """Gemini 응답에서 JSON 파싱"""
    # JSON 배열 추출
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("JSON 배열을 찾을 수 없음")

    clusters = json.loads(match.group())

    # 유효성 검사
    result = []
    for c in clusters:
        if "topic" in c and "keywords" in c:
            result.append({
                "topic":    str(c["topic"]).strip(),
                "keywords": [str(k).strip() for k in c["keywords"] if k],
            })

    if not result:
        raise ValueError("유효한 클러스터 없음")

    return result


def _fallback_cluster(keywords: List[str]) -> List[Dict[str, Any]]:
    """
    Gemini 호출 실패 시 폴백:
    키워드를 각각 독립 클러스터로 처리
    """
    return [
        {"topic": kw, "keywords": [kw]}
        for kw in keywords
    ]