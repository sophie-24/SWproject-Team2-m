"""
[AI 4] dashboard_ai.py — 대시보드 생성

역할:
- 모든 AI 분석 결과를 종합하여 최종 대시보드 데이터 생성
- 핵심 요약 3줄
- 공통 결론
- 쟁점
- 추천 영상 순위 (final_score 기반)

final_score = +구독채널여부 + 조회수기반영향력 + 최신성 - 광고포함여부
"""

import os
import re
from typing import List, Dict, Any

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_model = genai.GenerativeModel("gemini-2.5-flash-lite")

# final_score 가중치
FS_SUBSCRIBED     = 0.3   # 구독 채널 여부
FS_VIEW_INFLUENCE = 0.4   # 조회수 기반 영향력 (정규화된 view_count)
FS_RECENCY        = 0.2   # 최신성
FS_AD_PENALTY     = 0.3   # 광고 포함 시 감점


def _call_gemini(prompt: str, temperature: float = 0.3) -> str:
    response = _model.generate_content(
        prompt,
        generation_config={"temperature": temperature},
    )
    if response.text is None:
        finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        raise ValueError(f"Gemini 응답 없음 (finish_reason: {finish})")
    return response.text


def _parse_section(text: str, section_name: str) -> str:
    pattern = rf"\[{section_name}\]\s*(.*?)(?=\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_bullet_list(text: str, section_name: str) -> List[str]:
    section = _parse_section(text, section_name)
    items = re.findall(r"^-\s+(.+)", section, re.MULTILINE)
    return [item.strip() for item in items if item.strip()]


def _calc_final_score(video: Dict[str, Any], max_view_count: int) -> float:
    """
    final_score = +구독채널여부 + 조회수기반영향력 + 최신성 - 광고포함여부

    각 항목은 0~1 스케일로 정규화 후 가중치 적용.
    """
    is_subscribed   = 1.0 if video.get("is_subscribed", False) else 0.0
    view_influence  = video.get("view_count", 0) / max(max_view_count, 1)
    recency         = video.get("recency_score", 0.0)
    ad_penalty      = FS_AD_PENALTY if video.get("ad_detected", False) else 0.0

    score = (
        FS_SUBSCRIBED     * is_subscribed
        + FS_VIEW_INFLUENCE * view_influence
        + FS_RECENCY        * recency
        - ad_penalty
    )
    return round(max(0.0, min(1.0, score)), 4)


def _rank_videos(
    selector_videos: List[Dict[str, Any]],
    analyzer_videos: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    selector_ai 메타데이터 + analyzer_ai 분석 결과를 합쳐
    final_score 기준으로 정렬된 추천 목록 반환.
    """
    # analyzer 결과를 video_id로 인덱싱
    analyzer_map = {v["video_id"]: v for v in analyzer_videos}

    max_view_count = max((v.get("view_count", 0) for v in selector_videos), default=1)

    ranked = []
    for sv in selector_videos:
        vid = sv["video_id"]
        av = analyzer_map.get(vid, {})

        merged = {
            **sv,
            "summary": av.get("summary", ""),
            "key_claims": av.get("key_claims", []),
            "ad_detected": av.get("ad_detected", False),
            "ad_score": av.get("ad_score", 0),
            "credibility_score": av.get("credibility_score", 0.5),
            "transcript_available": av.get("transcript_available", False),
        }
        merged["final_score"] = _calc_final_score(merged, max_view_count)
        ranked.append(merged)

    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    return ranked


def generate_dashboard(
    keyword: str,
    selector_result: List[Dict[str, Any]],
    analyzer_result: Dict[str, Any],
    category_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    모든 AI 분석 결과를 종합하여 최종 대시보드 데이터를 생성.

    Args:
        keyword: 검색 키워드
        selector_result: selector_ai.select_top_videos() 반환값
        analyzer_result: analyzer_ai.analyze_videos() 반환값
        category_result: category_ai.classify_category() 반환값

    Returns:
        {
            "keyword": str,
            "category": str,
            "layout": dict,
            "summary_lines": List[str],   # 핵심 요약 3줄
            "common_conclusion": str,     # 공통 결론
            "controversies": List[str],   # 쟁점
            "recommended_videos": List[dict],  # final_score 순 정렬
            "common_facts": List[str],
        }
    """
    print(f"[dashboard] '{keyword}' 대시보드 생성 시작")

    analyzer_videos = analyzer_result.get("videos", [])
    common_facts    = analyzer_result.get("common_facts", [])
    controversies   = analyzer_result.get("controversies", [])

    # 1. 추천 영상 순위 산출
    recommended_videos = _rank_videos(selector_result, analyzer_videos)

    # 2. Gemini로 핵심 요약 3줄 + 공통 결론 생성
    summary_lines, common_conclusion = _generate_summary(
        keyword, common_facts, controversies, recommended_videos, category_result
    )

    print(f"[dashboard] 완료 — 추천 영상 {len(recommended_videos)}개")

    return {
        "keyword": keyword,
        "category": category_result.get("category", "정보탐색형"),
        "layout": category_result.get("layout", {}),
        "summary_lines": summary_lines,
        "common_conclusion": common_conclusion,
        "controversies": controversies,
        "recommended_videos": recommended_videos,
        "common_facts": common_facts,
    }


def _generate_summary(
    keyword: str,
    common_facts: List[str],
    controversies: List[str],
    ranked_videos: List[Dict[str, Any]],
    category_result: Dict[str, Any],
) -> tuple[List[str], str]:
    """Gemini 호출로 핵심 요약 3줄 + 공통 결론 생성"""

    facts_text = "\n".join(f"- {f}" for f in common_facts) if common_facts else "- 없음"
    controversy_text = "\n".join(f"- {c}" for c in controversies) if controversies else "- 없음"
    top_titles = "\n".join(
        f"  {i+1}. {v['title']} (최종점수: {v['final_score']})"
        for i, v in enumerate(ranked_videos[:5])
    )
    category = category_result.get("category", "정보탐색형")

    prompt = f"""
검색어: {keyword}
검색 의도: {category}

[공통 사실]
{facts_text}

[쟁점]
{controversy_text}

[추천 영상 순위]
{top_titles}

위 정보를 바탕으로 아래 형식에 맞게 작성하세요.

[핵심요약]
이 검색 결과를 처음 보는 사람이 바로 이해할 수 있도록 3줄로 요약.
각 줄은 "- " 으로 시작. 정확히 3개 항목.

[공통결론]
여러 영상에서 공통으로 도달한 결론을 1~2문장으로 작성.
"""

    try:
        text = _call_gemini(prompt, temperature=0.3)
    except Exception as e:
        print(f"  [요약 생성 오류]: {e}")
        return (
            ["요약 생성 실패", "잠시 후 다시 시도해주세요", ""],
            "공통 결론을 생성할 수 없습니다.",
        )

    summary_lines = _parse_bullet_list(text, "핵심요약")
    # 정확히 3줄 보장
    while len(summary_lines) < 3:
        summary_lines.append("")
    summary_lines = summary_lines[:3]

    common_conclusion = _parse_section(text, "공통결론")
    if not common_conclusion:
        common_conclusion = common_facts[0] if common_facts else "공통 결론 없음"

    return summary_lines, common_conclusion
