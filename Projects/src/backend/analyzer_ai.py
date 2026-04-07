"""
[AI 2] analyzer_ai.py — 5개 영상 동시 분석

역할:
- 자막 수집 및 전처리
- 광고/협찬 탐지
- 영상별 핵심 주장 추출
- 공통 사실 추출 (3개 이상 영상에서 언급)
- 쟁점 추출 (영상마다 다른 주장)
- 신뢰도 계산 (반복 등장 → 상승, 광고 포함 → 하락)
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

import google.generativeai as genai
from dotenv import load_dotenv

from transcript_service import get_transcript, format_transcript_with_timestamps
from preprocessing import clean_transcript

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_model = genai.GenerativeModel("gemini-2.5-flash-lite")

# 자막 최대 길이 (Gemini 1M 토큰 활용, 안전 마진 포함)
MAX_TRANSCRIPT_CHARS = 80_000


def _call_gemini(prompt: str, temperature: float = 0.3) -> str:
    response = _model.generate_content(
        prompt,
        generation_config={"temperature": temperature},
    )
    if response.text is None:
        finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        raise ValueError(f"Gemini 응답 없음 (finish_reason: {finish})")
    return response.text


def _collect_transcript(video_id: str) -> Optional[str]:
    """자막 수집 → 정제 → 단일 문자열 반환. 실패 시 None."""
    raw = get_transcript(video_id)
    if not raw:
        return None

    entries = format_transcript_with_timestamps(raw)
    if not entries:
        return None

    full_text = " ".join(e["text"] for e in entries)
    cleaned = clean_transcript(full_text)
    return cleaned[:MAX_TRANSCRIPT_CHARS] if cleaned else None


def _analyze_single_video(video: Dict[str, Any]) -> Dict[str, Any]:
    """
    영상 1개를 분석하여 아래 필드를 반환:
    - video_id, title, channel_id, channel_title
    - transcript_available (bool)
    - ad_score (0~100)
    - ad_detected (bool: ad_score >= 60)
    - summary (str)
    - key_claims (List[str])
    - credibility_score (float, 0~1) — 이후 cross_analyze에서 보정
    """
    video_id = video["video_id"]
    title = video.get("title", "")
    channel_title = video.get("channel_title", "")

    transcript = _collect_transcript(video_id)
    if not transcript:
        return {
            "video_id": video_id,
            "title": title,
            "channel_id": video.get("channel_id", ""),
            "channel_title": channel_title,
            "transcript_available": False,
            "ad_score": 0,
            "ad_detected": False,
            "summary": "자막 없음",
            "key_claims": [],
            "credibility_score": 0.3,
        }

    prompt = f"""
다음은 유튜브 영상의 자막입니다.
영상 제목: {title}
채널: {channel_title}

아래 형식에 맞게 분석하세요. 각 항목은 정확히 지정된 형식으로만 답변하세요.

[광고점수]
0~100 사이 정수 하나만. 기준:
- 명시적 협찬/유료광고 문구 → 80~100
- 구매 유도 링크/할인코드 → 60~80
- 제품 소개 중심 (광고 문구 없음) → 40~60
- 정보/리뷰 목적 제품 언급 → 20~40
- 광고 요소 없음 → 0~20

[요약]
영상 내용을 2~3문장으로 요약.

[핵심주장]
이 영상에서 제시하는 핵심 주장이나 정보를 최대 5개 항목으로 작성.
각 항목은 "- " 으로 시작.

자막:
{transcript}
"""

    try:
        text = _call_gemini(prompt, temperature=0.3)
    except Exception as e:
        print(f"  [분석 오류] {video_id}: {e}")
        return {
            "video_id": video_id,
            "title": title,
            "channel_id": video.get("channel_id", ""),
            "channel_title": channel_title,
            "transcript_available": True,
            "ad_score": 0,
            "ad_detected": False,
            "summary": "분석 실패",
            "key_claims": [],
            "credibility_score": 0.3,
        }

    # 파싱
    ad_score = _parse_ad_score(text)
    summary = _parse_section(text, "요약")
    key_claims = _parse_bullet_list(text, "핵심주장")

    return {
        "video_id": video_id,
        "title": title,
        "channel_id": video.get("channel_id", ""),
        "channel_title": channel_title,
        "transcript_available": True,
        "ad_score": ad_score,
        "ad_detected": ad_score >= 60,
        "summary": summary,
        "key_claims": key_claims,
        "credibility_score": 0.5,  # cross_analyze에서 최종 보정
    }


def _parse_ad_score(text: str) -> int:
    """[광고점수] 섹션에서 숫자 추출"""
    section = _parse_section(text, "광고점수")
    match = re.search(r"\d+", section)
    if match:
        return max(0, min(100, int(match.group())))
    # 섹션이 없으면 전체 텍스트에서 첫 숫자 탐색
    match = re.search(r"\d+", text[:50])
    return max(0, min(100, int(match.group()))) if match else 0


def _parse_section(text: str, section_name: str) -> str:
    """[섹션명] ~ 다음 [섹션] 사이 텍스트 추출"""
    pattern = rf"\[{section_name}\]\s*(.*?)(?=\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_bullet_list(text: str, section_name: str) -> List[str]:
    """[섹션명] 내부의 "- " 항목들 리스트로 반환"""
    section = _parse_section(text, section_name)
    items = re.findall(r"^-\s+(.+)", section, re.MULTILINE)
    return [item.strip() for item in items if item.strip()]


def _cross_analyze(
    keyword: str,
    video_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    5개 영상 분석 결과를 종합하여:
    - common_facts: 3개 이상 영상에서 언급된 공통 사실
    - controversies: 영상마다 다른 주장/쟁점
    반환. 또한 각 영상의 credibility_score를 최종 보정.
    """
    # 자막이 있는 영상만 대상
    valid = [v for v in video_results if v["transcript_available"] and v["key_claims"]]
    if not valid:
        return {"common_facts": [], "controversies": []}

    claims_block = "\n\n".join(
        f"영상{i+1} ({v['title']}):\n" + "\n".join(f"  - {c}" for c in v["key_claims"])
        for i, v in enumerate(valid)
    )

    prompt = f"""
검색어: {keyword}

아래는 {len(valid)}개 유튜브 영상에서 추출한 핵심 주장 목록입니다.

{claims_block}

다음 두 가지를 분석하세요.

[공통사실]
3개 이상의 영상에서 공통으로 언급되거나 동의하는 사실/정보를 최대 5개 작성.
각 항목은 "- " 으로 시작. 없으면 "- 없음" 으로 작성.

[쟁점]
영상마다 서로 다른 주장을 하거나 의견이 나뉘는 내용을 최대 5개 작성.
각 항목은 "- " 으로 시작. 없으면 "- 없음" 으로 작성.
"""

    try:
        text = _call_gemini(prompt, temperature=0.3)
    except Exception as e:
        print(f"  [교차분석 오류]: {e}")
        return {"common_facts": [], "controversies": []}

    common_facts = _parse_bullet_list(text, "공통사실")
    controversies = _parse_bullet_list(text, "쟁점")

    # "없음" 제거
    common_facts = [f for f in common_facts if f != "없음"]
    controversies = [c for c in controversies if c != "없음"]

    return {"common_facts": common_facts, "controversies": controversies}


def _calc_credibility(video: Dict[str, Any], common_facts: List[str]) -> float:
    """
    신뢰도 계산:
    - 기본 0.5
    - 광고 포함 → -0.2
    - 공통 사실과 일치하는 주장 수에 비례 → 최대 +0.3
    """
    score = 0.5

    if video["ad_detected"]:
        score -= 0.2

    if common_facts and video["key_claims"]:
        # 핵심 주장 중 공통 사실 키워드와 겹치는 비율
        claim_text = " ".join(video["key_claims"]).lower()
        matched = sum(
            1 for fact in common_facts
            if any(word in claim_text for word in fact.lower().split() if len(word) > 2)
        )
        overlap_ratio = matched / max(len(common_facts), 1)
        score += 0.3 * overlap_ratio

    return round(max(0.0, min(1.0, score)), 3)


def analyze_videos(
    keyword: str,
    videos: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    5개 영상을 병렬 분석 후 교차 분석 결과를 반환.

    Args:
        keyword: 검색 키워드
        videos: selector_ai.select_top_videos() 반환값 (최대 5개)

    Returns:
        {
            "keyword": str,
            "videos": [...],          # 영상별 분석 결과 + credibility_score
            "common_facts": [...],    # 공통 사실
            "controversies": [...],   # 쟁점
        }
    """
    print(f"[analyzer] '{keyword}' 영상 {len(videos)}개 분석 시작")

    # 1. 영상별 병렬 분석 (자막 수집 + Gemini 호출)
    video_results: List[Dict[str, Any]] = [None] * len(videos)
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {
            executor.submit(_analyze_single_video, v): i
            for i, v in enumerate(videos)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                video_results[idx] = future.result()
            except Exception as e:
                print(f"  [영상 분석 실패] index={idx}: {e}")
                v = videos[idx]
                video_results[idx] = {
                    "video_id": v["video_id"],
                    "title": v.get("title", ""),
                    "channel_id": v.get("channel_id", ""),
                    "channel_title": v.get("channel_title", ""),
                    "transcript_available": False,
                    "ad_score": 0,
                    "ad_detected": False,
                    "summary": "분석 실패",
                    "key_claims": [],
                    "credibility_score": 0.3,
                }

    # 2. 교차 분석 (공통 사실, 쟁점)
    cross = _cross_analyze(keyword, video_results)
    common_facts = cross["common_facts"]
    controversies = cross["controversies"]

    # 3. 신뢰도 최종 보정
    for vr in video_results:
        vr["credibility_score"] = _calc_credibility(vr, common_facts)

    print(f"[analyzer] 완료 — 공통사실 {len(common_facts)}개 / 쟁점 {len(controversies)}개")

    return {
        "keyword": keyword,
        "videos": video_results,
        "common_facts": common_facts,
        "controversies": controversies,
    }
