# 자막 분석 에이전트 — 배치 광고 탐지, 교차분석(공통사실·쟁점), 신뢰도 점수, 영어 자막 한국어 처리
import asyncio
import re
from typing import List, Dict, Any, Optional

from transcript_service import get_transcript, format_transcript_with_timestamps
from preprocessing import clean_transcript
from gemini_client import call_gemini_async, parse_section, parse_bullet_list
from ad_detector import detect_ad_signals, blend_scores

from logger import get_logger
logger = get_logger(__name__)


# ── 상수 ──────────────────────────────────────────────────────────────────────

MAX_TRANSCRIPT_CHARS = 30_000

_KO_CHAR_RATIO_THRESHOLD = 0.15


# ── 언어 감지 ─────────────────────────────────────────────────────────────────

def _detect_language(text: str) -> str:
    if not text:
        return "en"
    ko_chars = sum(1 for c in text if "\uAC00" <= c <= "\uD7A3")
    return "ko" if (ko_chars / len(text)) >= _KO_CHAR_RATIO_THRESHOLD else "en"


def _build_lang_instruction(lang: str) -> str:
    if lang == "en":
        return (
            "[주의] 아래 자막은 영어입니다. 영어 자막을 분석하되 "
            "반드시 한국어 섹션 형식으로 답변하세요.\n"
        )
    return ""


# ── 자막 수집 (동기, asyncio.to_thread로 호출) ───────────────────────────────

def _collect_transcript(video_id: str) -> Optional[str]:
    raw = get_transcript(video_id)
    if not raw:
        return None
    entries = format_transcript_with_timestamps(raw)
    if not entries:
        return None
    full_text = " ".join(e["text"] for e in entries)
    cleaned = clean_transcript(full_text)
    return cleaned[:MAX_TRANSCRIPT_CHARS] if cleaned else None


# ── Strategy B: 배치 분석 (영상 N개 → Gemini 1회) ────────────────────────────

async def _analyze_videos_batch(
    keyword: str,
    videos: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    영상 N개를 하나의 Gemini 호출로 일괄 분석.

    이전: _analyze_single_video() x N = N회 호출
    이후: 1회 호출 (자막 수집은 asyncio.gather로 병렬 처리)
    """
    # 1. 자막 수집 — 병렬
    transcripts: List[Optional[str]] = list(await asyncio.gather(
        *[asyncio.to_thread(_collect_transcript, v["video_id"]) for v in videos]
    ))

    # 2. 자막 없는 영상만 있으면 Gemini 호출 생략
    if not any(transcripts):
        return [
            {
                "video_id": v["video_id"],
                "title": v.get("title", ""),
                "channel_id": v.get("channel_id", ""),
                "channel_title": v.get("channel_title", ""),
                "transcript_available": False,
                "ad_score": 0,
                "ad_detected": False,
                "summary": "자막 없음",
                "key_claims": [],
                "credibility_score": 0.3,
            }
            for v in videos
        ]

    # 3. 배치 프롬프트 구성
    video_blocks = []
    for i, (v, t) in enumerate(zip(videos, transcripts)):
        title = v.get("title", "")
        channel = v.get("channel_title", "")
        if t:
            lang = _detect_language(t)
            lang_inst = _build_lang_instruction(lang)
            if lang == "en":
                logger.info(f"  [언어감지] {v['video_id']}: 영어 자막")
            block = (
                f"[영상 {i + 1}] 제목: {title} / 채널: {channel}\n"
                f"{lang_inst}"
                f"자막:\n{t}"
            )
        else:
            block = f"[영상 {i + 1}] 제목: {title} / 채널: {channel}\n자막: 없음"
        video_blocks.append(block)

    video_data = "\n\n" + ("-" * 40 + "\n").join(video_blocks)

    prompt = (
        f"검색 주제: {keyword}\n"
        f"아래 {len(videos)}개 유튜브 영상을 각각 분석하세요.\n"
        f"반드시 각 영상 분석을 ===VIDEO_N=== 구분자로 시작하고, 아래 형식을 정확히 따르세요.\n"
        f"모든 답변은 한국어로 작성하세요.\n"
        f"\n"
        f"[응답 형식]\n"
        f"===VIDEO_1===\n"
        f"[광고점수]\n"
        f"0~100 정수 하나만 (협찬/광고 문구 -> 80~100, 구매 유도 -> 60~80, 정보/리뷰 -> 0~40)\n"
        f"[요약]\n"
        f"영상 내용 2~3문장 요약\n"
        f"[핵심주장]\n"
        f"- 핵심 주장 1\n"
        f"- 핵심 주장 2 (최대 5개)\n"
        f"\n"
        f"===VIDEO_2===\n"
        f"... (동일 형식 반복)\n"
        f"\n"
        f"[영상 데이터]"
        f"{video_data}\n"
        f"\n"
        f"위 {len(videos)}개 영상을 각각 분석하세요. "
        f"===VIDEO_1=== 부터 ===VIDEO_{len(videos)}=== 까지 모든 영상을 빠짐없이 분석하세요."
    )

    try:
        text = await call_gemini_async(prompt, temperature=0.3)
        return _parse_batch_response(text, videos, transcripts)
    except Exception as e:
        logger.error(f"  [배치분석 오류] {keyword}: {e}")
        # 폴백: 모든 영상 분석 실패 처리
        return [
            {
                "video_id": v["video_id"],
                "title": v.get("title", ""),
                "channel_id": v.get("channel_id", ""),
                "channel_title": v.get("channel_title", ""),
                "transcript_available": transcripts[i] is not None,
                "ad_score": 0,
                "ad_detected": False,
                "summary": "분석 실패",
                "key_claims": [],
                "credibility_score": 0.3,
            }
            for i, v in enumerate(videos)
        ]


def _parse_batch_response(
    text: str,
    videos: List[Dict[str, Any]],
    transcripts: List[Optional[str]],
) -> List[Dict[str, Any]]:
    """
    ===VIDEO_N=== 구분자로 Gemini 배치 응답을 파싱.
    구분자가 없는 영상은 기본값으로 처리.
    """
    parts = re.split(r"===VIDEO_(\d+)===", text)
    section_map: Dict[int, str] = {}
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            section_map[int(parts[i])] = parts[i + 1]

    results = []
    for i, v in enumerate(videos):
        content = section_map.get(i + 1, "")
        transcript = transcripts[i]

        gemini_ad_score = _parse_ad_score(content) if content else 0
        summary = parse_section(content, "요약") if content else ""
        key_claims = parse_bullet_list(content, "핵심주장") if content else []

        # Layer 1~3 규칙 기반 탐지 (description + 자막 패턴 + API 플래그)
        rule_result = detect_ad_signals(
            description=v.get("description", ""),
            transcript=transcript or "",
            paid_flag=v.get("has_paid_placement"),  # YouTube Studio 체크박스 값
        )
        # Layer 4 Gemini 점수와 블렌딩
        ad_score = blend_scores(rule_result.rule_score, gemini_ad_score)

        results.append({
            "video_id": v["video_id"],
            "title": v.get("title", ""),
            "channel_id": v.get("channel_id", ""),
            "channel_title": v.get("channel_title", ""),
            "transcript_available": transcript is not None,
            "ad_score": ad_score,
            "ad_detected": ad_score >= 60,
            "ad_signals": [
                {"rule": s.rule, "evidence": s.evidence, "score": s.score}
                for s in rule_result.signals
            ],
            "summary": summary or ("자막 없음" if not transcript else "분석 실패"),
            "key_claims": key_claims,
            "credibility_score": 0.3 if ad_score >= 60 else 0.5,
        })

    return results


def _parse_ad_score(text: str) -> int:
    section = parse_section(text, "광고점수")
    match = re.search(r"\d+", section)
    if match:
        return max(0, min(100, int(match.group())))
    match = re.search(r"\d+", text[:50])
    return max(0, min(100, int(match.group()))) if match else 0


# ── Strategy C: 교차분석 + 뉴스레터 통합 (2회 → 1회) ────────────────────────

async def _cross_and_generate(
    keyword: str,
    video_results: List[Dict[str, Any]],
    format_style: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    교차분석(공통사실/쟁점)과 뉴스레터 콘텐츠(요약/장점/단점)를
    하나의 Gemini 호출로 통합 생성.

    이전: _cross_analyze() 1회 + _generate_topic_content() 1회 = 2회
    이후: 1회
    """
    valid = [v for v in video_results if v["transcript_available"] and v["key_claims"]]
    if not valid:
        return {
            "common_facts": [],
            "controversies": [],
            "summary": ["분석 가능한 영상이 없습니다", "", ""],
            "pros": [],
            "cons": [],
        }

    # 영상별 주장 블록 (신뢰도 + 광고 여부 포함)
    claims_lines = []
    for i, v in enumerate(valid):
        ad_tag = " [광고포함]" if v["ad_detected"] else ""
        cred = v.get("credibility_score", 0.5)
        claims_lines.append(
            f"영상{i + 1} [{v['channel_title']} / 신뢰도:{cred:.1f}{ad_tag}]:"
        )
        for c in v["key_claims"]:
            claims_lines.append(f"  - {c}")
    claims_block = "\n".join(claims_lines)

    length_guide = (
        "각 항목은 1줄로 간결하게"
        if format_style and format_style.get("length") == "short"
        else "각 항목은 2줄 이내로"
    )
    tone_note = f"작성 스타일: {format_style['tone']}\n" if format_style and format_style.get("tone") else ""

    prompt = (
        f"검색 주제: {keyword}\n"
        f"\n"
        f"아래는 {len(valid)}개 유튜브 영상에서 추출한 핵심 주장입니다.\n"
        f"[광고포함] 영상의 주장은 신뢰도가 낮으므로 보조 정보로만 활용하세요.\n"
        f"\n"
        f"{claims_block}\n"
        f"\n"
        f"위 영상 분석을 바탕으로 아래 항목들을 한국어로 작성하세요.\n"
        f"{tone_note}"
        f"{length_guide} 작성하세요.\n"
        f"\n"
        f"[공통사실]\n"
        f"3개 이상 영상에서 공통으로 언급된 사실/정보를 최대 5개.\n"
        f"각 항목은 \"- \"으로 시작. 없으면 \"- 없음\".\n"
        f"\n"
        f"[쟁점]\n"
        f"영상마다 서로 다른 주장이나 의견이 갈리는 내용을 최대 5개.\n"
        f"각 항목은 \"- \"으로 시작. 없으면 \"- 없음\".\n"
        f"\n"
        f"[요약]\n"
        f"이 주제의 핵심을 정확히 3줄로 요약. 각 줄은 \"- \"으로 시작.\n"
        f"\n"
        f"[장점]\n"
        f"긍정적인 점을 최대 3개. 각 항목은 \"- \"으로 시작.\n"
        f"\n"
        f"[단점]\n"
        f"부정적이거나 주의할 점을 최대 3개. 각 항목은 \"- \"으로 시작.\n"
    )

    try:
        text = await call_gemini_async(prompt, temperature=0.3)
    except Exception as e:
        logger.error(f"  [교차+생성 오류] {keyword}: {e}")
        return {
            "common_facts": [],
            "controversies": [],
            "summary": ["콘텐츠 생성 실패", "", ""],
            "pros": [],
            "cons": [],
        }

    common_facts  = [f for f in parse_bullet_list(text, "공통사실") if f != "없음"]
    controversies = [c for c in parse_bullet_list(text, "쟁점")    if c != "없음"]
    summary       = parse_bullet_list(text, "요약")
    pros          = parse_bullet_list(text, "장점")
    cons          = parse_bullet_list(text, "단점")

    while len(summary) < 3:
        summary.append("")
    summary = summary[:3]

    return {
        "common_facts":  common_facts,
        "controversies": controversies,
        "summary":       summary,
        "pros":          pros,
        "cons":          cons,
    }


# ── 신뢰도 보정 ───────────────────────────────────────────────────────────────

def _calc_credibility(video: Dict[str, Any], common_facts: List[str]) -> float:
    score = 0.5
    if video["ad_detected"]:
        score -= 0.2
    if common_facts and video["key_claims"]:
        claim_text = " ".join(video["key_claims"]).lower()
        matched = sum(
            1 for fact in common_facts
            if any(word in claim_text for word in fact.lower().split() if len(word) > 2)
        )
        score += 0.3 * (matched / max(len(common_facts), 1))
    return round(max(0.0, min(1.0, score)), 3)


# ── 메인 진입점 ───────────────────────────────────────────────────────────────

async def analyze_videos(
    keyword: str,
    videos: List[Dict[str, Any]],
    format_style: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    영상 배치 분석 + 교차분석 + 뉴스레터 콘텐츠를 2회 Gemini 호출로 완성.

    Gemini 호출 횟수 변화 (영상 5개 기준):
      이전: 5 (개별분석) + 1 (교차분석) + 1 (뉴스레터) = 7회
      이후: 1 (배치분석) + 1 (교차+뉴스레터 통합) = 2회

    Args:
        keyword:      검색 키워드
        videos:       selector_ai 반환 영상 목록 (최대 5개)
        format_style: intent_ai가 반환한 format_style (뉴스레터 스타일 제어)
    """
    logger.info(f"[analyzer] '{keyword}' 영상 {len(videos)}개 — 배치 분석 시작")

    # Step 1: 배치 분석 [1회 호출]
    video_results = await _analyze_videos_batch(keyword, videos)

    # Step 2: 교차분석 + 뉴스레터 통합 [1회 호출]
    content = await _cross_and_generate(keyword, video_results, format_style)

    # Step 3: 최종 신뢰도 보정 (공통사실 기반, 호출 없음)
    common_facts = content["common_facts"]
    for vr in video_results:
        vr["credibility_score"] = _calc_credibility(vr, common_facts)

    # 출처 구성 (광고 제외, 없으면 전체)
    sources = [
        {
            "title":         v["title"],
            "url":           f"https://youtube.com/watch?v={v['video_id']}",
            "channel_title": v.get("channel_title", ""),
            "thumbnail_url": f"https://img.youtube.com/vi/{v['video_id']}/mqdefault.jpg",
        }
        for v in video_results
        if not v.get("ad_detected") and v.get("transcript_available")
    ]
    if not sources:
        sources = [
            {
                "title":         v["title"],
                "url":           f"https://youtube.com/watch?v={v['video_id']}",
                "channel_title": v.get("channel_title", ""),
                "thumbnail_url": f"https://img.youtube.com/vi/{v['video_id']}/mqdefault.jpg",
            }
            for v in video_results
        ]

    logger.info(f"[analyzer] 완료 — 공통사실 {len(common_facts)}개 / "
        f"쟁점 {len(content['controversies'])}개"
    )

    return {
        "keyword":       keyword,
        "videos":        video_results,
        "common_facts":  common_facts,
        "controversies": content["controversies"],
        "summary":       content["summary"],
        "pros":          content["pros"],
        "cons":          content["cons"],
        "sources":       sources,
    }
