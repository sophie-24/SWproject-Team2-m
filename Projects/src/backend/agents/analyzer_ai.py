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


# ── 영상 1개 분석 (Gemini 1회 호출) ──────────────────────────────────────────

_ANALYZE_SEMAPHORE_SIZE = 5  # 토픽당 최대 동시 Gemini 호출 수


async def _analyze_single_video(
    video: Dict[str, Any],
    transcript: Optional[str],
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    """
    영상 1개를 Gemini 1회 호출로 분석 (광고점수 + 요약 + 핵심주장).

    자막 없는 영상은 Gemini 호출 없이 rule 기반 광고 탐지만 수행.
    Lost in the Middle 방지: 영상 N개를 1개 프롬프트에 묶지 않고 개별 호출.
    """
    # Layer 1~3 규칙 기반 탐지 — 자막 유무와 무관하게 항상 수행
    rule_result = detect_ad_signals(
        description=video.get("description", ""),
        transcript=transcript or "",
        paid_flag=video.get("has_paid_placement"),
    )

    if not transcript:
        # 자막 없음 — Gemini 호출 생략, rule 점수만 반영
        ad_score = blend_scores(rule_result.rule_score, 0)
        return {
            "video_id":            video["video_id"],
            "title":               video.get("title", ""),
            "channel_id":          video.get("channel_id", ""),
            "channel_title":       video.get("channel_title", ""),
            "subscriber_count":    video.get("subscriber_count", 0),
            "transcript_available": False,
            "transcript_len":      0,
            "ad_score":            ad_score,
            "ad_detected":         ad_score >= 60,
            "ad_signals":          [
                {"rule": s.rule, "evidence": s.evidence, "score": s.score}
                for s in rule_result.signals
            ],
            "summary":             "자막 없음",
            "key_claims":          [],
            "credibility_score":   0.3,
        }

    # 자막 있음 — Semaphore 획득 후 Gemini 호출
    lang = _detect_language(transcript)
    lang_inst = _build_lang_instruction(lang)
    if lang == "en":
        logger.info(f"  [언어감지] {video['video_id']}: 영어 자막")

    prompt = (
        f"제목: {video.get('title', '')} / 채널: {video.get('channel_title', '')}\n"
        f"{lang_inst}"
        f"자막:\n{transcript}\n"
        f"\n"
        f"위 유튜브 영상을 분석하세요. 반드시 아래 형식으로 답변하세요.\n"
        f"모든 답변은 한국어로 작성하세요.\n"
        f"\n"
        f"[광고점수]\n"
        f"0~100 정수 하나만 (협찬/광고 문구 → 80~100, 구매 유도 → 60~80, 정보/리뷰 → 0~40)\n"
        f"[요약]\n"
        f"영상 내용 2~3문장 요약\n"
        f"[핵심주장]\n"
        f"- 핵심 주장 1\n"
        f"- 핵심 주장 2 (최대 5개)\n"
    )

    try:
        async with semaphore:
            text = await call_gemini_async(prompt, temperature=0.3)
    except Exception as e:
        logger.warning(f"  [단일분석 오류] {video['video_id']}: {e}")
        text = ""

    gemini_ad_score = _parse_ad_score(text) if text else 0
    summary     = parse_section(text, "요약") if text else ""
    key_claims  = parse_bullet_list(text, "핵심주장") if text else []

    # Layer 4 Gemini 점수와 rule 점수 블렌딩
    ad_score = blend_scores(rule_result.rule_score, gemini_ad_score)

    return {
        "video_id":            video["video_id"],
        "title":               video.get("title", ""),
        "channel_id":          video.get("channel_id", ""),
        "channel_title":       video.get("channel_title", ""),
        "subscriber_count":    video.get("subscriber_count", 0),
        "transcript_available": True,
        "transcript_len":      len(transcript),
        "ad_score":            ad_score,
        "ad_detected":         ad_score >= 60,
        "ad_signals":          [
            {"rule": s.rule, "evidence": s.evidence, "score": s.score}
            for s in rule_result.signals
        ],
        "summary":             summary or "분석 실패",
        "key_claims":          key_claims,
        "credibility_score":   0.3 if ad_score >= 60 else 0.5,
    }


# ── 영상 N개 병렬 분석 (영상당 Gemini 1회) ───────────────────────────────────

async def _analyze_videos_parallel(
    keyword: str,
    videos: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    영상 N개를 개별 Gemini 호출로 병렬 분석.

    이전(_analyze_videos_batch): N개 → Gemini 1회 (배치 프롬프트)
      → Lost in the Middle: 후반부 영상 요약 품질 저하
    현재(_analyze_videos_parallel): N개 → Gemini N회 병렬
      → 각 영상이 독립적인 짧은 프롬프트를 받아 균일한 품질 보장

    Gemini 호출 수: 영상 5개 기준 1회 → 5회 (+ 교차분석 1회로 총 6회)
    """
    # Step 1: 자막 수집 — 병렬
    transcripts: List[Optional[str]] = list(await asyncio.gather(
        *[asyncio.to_thread(_collect_transcript, v["video_id"]) for v in videos]
    ))

    # Step 2: 영상별 개별 분석 — 병렬 (Semaphore로 동시 Gemini 호출 수 제한)
    semaphore = asyncio.Semaphore(_ANALYZE_SEMAPHORE_SIZE)
    results: List[Dict[str, Any]] = list(await asyncio.gather(
        *[
            _analyze_single_video(v, t, semaphore)
            for v, t in zip(videos, transcripts)
        ]
    ))

    logger.info(
        f"  [병렬분석] '{keyword}' — {len(videos)}개 영상 / "
        f"자막 있음 {sum(1 for t in transcripts if t)}개"
    )
    return results


def _parse_ad_score(text: str) -> int:
    section = parse_section(text, "광고점수")
    match = re.search(r"\d+", section)
    if match:
        return max(0, min(100, int(match.group())))
    match = re.search(r"\d+", text[:50])
    return max(0, min(100, int(match.group()))) if match else 0


# ── 의도별 교차분석 프롬프트 전략 ───────────────────────────────────────────────

# intent_type → 포함할 섹션 목록
_INTENT_SECTIONS: Dict[str, List[str]] = {
    "유희형":  ["쟁점", "요약"],                              # 흥미·화제성 위주
    "지식형":  ["공통사실", "쟁점", "요약", "장점", "단점"],  # 모든 섹션 포함
    "구매형":  ["공통사실", "요약", "장점", "단점"],          # 실용 비교 위주
}

_SECTION_GUIDE: Dict[str, str] = {
    "공통사실": (
        "3개 이상 영상에서 공통으로 언급된 사실·정보를 최대 5개.\n"
        "각 항목은 \"- \"으로 시작. 없으면 \"- 없음\"."
    ),
    "쟁점": (
        "영상마다 서로 다른 주장이나 의견 차이를 최대 5개.\n"
        "각 항목은 \"- \"으로 시작. 없으면 \"- 없음\"."
    ),
    "요약": "이 주제의 핵심을 정확히 3줄로 요약. 각 줄은 \"- \"으로 시작.",
    "장점": "긍정적인 점을 최대 3개. 각 항목은 \"- \"으로 시작.",
    "단점": "부정적이거나 주의할 점을 최대 3개. 각 항목은 \"- \"으로 시작.",
}

_INTENT_TONE: Dict[str, str] = {
    "유희형": "친근하고 가벼운 말투. 이모지 1~2개 포함. 흥미를 유발하는 표현 사용.",
    "지식형": "정확하고 신뢰감 있는 문체. 전문 용어는 간단히 풀어 설명. 근거 중심.",
    "구매형": "실용적·객관적 말투. 수치와 비교 표현 활용. 결론을 앞에 배치.",
}

_INTENT_FOCUS: Dict[str, str] = {
    "유희형": "화제성·논란·재미 포인트에 집중. 장단점 대신 '주목할 관점'을 작성.",
    "지식형": "사실 정확성과 출처 신뢰도 우선. 배경→핵심→시사점 순으로 요약.",
    "구매형": "구매 결정에 도움이 되는 장단점을 명확히 대비. 가격·스펙·사용성 위주 서술.",
}


# ── Strategy C: 교차분석 + 콘텐츠 통합 (1회 호출) ────────────────────────────

async def _cross_and_generate(
    keyword: str,
    video_results: List[Dict[str, Any]],
    format_style: Optional[Dict[str, str]] = None,
    intent_type: str = "지식형",
) -> Dict[str, Any]:
    """
    교차분석(공통사실/쟁점)과 콘텐츠(요약/장점/단점)를 1회 Gemini 호출로 통합 생성.

    intent_type에 따라 포함 섹션과 작성 톤이 달라진다:
      유희형 - 쟁점·요약만, 친근·가벼운 말투
      지식형 - 모든 섹션, 신뢰감 있는 문체
      구매형 - 공통사실·요약·장단점, 실용적 비교 언어
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

    # 의도별 설정
    sections     = _INTENT_SECTIONS.get(intent_type, _INTENT_SECTIONS["지식형"])
    tone         = _INTENT_TONE.get(intent_type, _INTENT_TONE["지식형"])
    focus        = _INTENT_FOCUS.get(intent_type, _INTENT_FOCUS["지식형"])
    length       = (format_style or {}).get("length", "medium")
    length_guide = "각 항목은 1줄로 간결하게" if length == "short" else "각 항목은 2줄 이내로"

    section_prompts = "\n\n".join(
        f"[{sec}]\n{_SECTION_GUIDE[sec]}" for sec in sections
    )

    prompt = (
        f"검색 주제: {keyword}\n"
        f"사용자 검색 의도: {intent_type}\n"
        f"\n"
        f"아래는 {len(valid)}개 유튜브 영상에서 추출한 핵심 주장입니다.\n"
        f"[광고포함] 영상의 주장은 신뢰도가 낮으므로 보조 정보로만 활용하세요.\n"
        f"\n"
        f"{claims_block}\n"
        f"\n"
        f"위 영상 분석을 바탕으로 아래 항목들을 한국어로 작성하세요.\n"
        f"작성 스타일: {tone}\n"
        f"분석 방향: {focus}\n"
        f"{length_guide} 작성하세요.\n"
        f"\n"
        f"{section_prompts}\n"
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

    # 요청한 섹션만 파싱 (요청 안 한 섹션은 빈 리스트)
    common_facts  = (
        [f for f in parse_bullet_list(text, "공통사실") if f != "없음"]
        if "공통사실" in sections else []
    )
    controversies = (
        [c for c in parse_bullet_list(text, "쟁점") if c != "없음"]
        if "쟁점" in sections else []
    )
    summary = parse_bullet_list(text, "요약") if "요약" in sections else []
    pros    = parse_bullet_list(text, "장점") if "장점" in sections else []
    cons    = parse_bullet_list(text, "단점") if "단점" in sections else []

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
#
# PPT 공식: 신뢰도 = ω₁·자막품질 + ω₂·(1-광고확률) + ω₃·채널신뢰도 + ω₄·정보일관성
#   ω₁=0.20, ω₂=0.35, ω₃=0.25, ω₄=0.20

W_TRANSCRIPT  = 0.20  # ω₁ 자막품질
W_AD_FREE     = 0.35  # ω₂ (1 - 광고확률)
W_CHANNEL     = 0.25  # ω₃ 채널신뢰도 (구독자 수 기반)
W_CONSISTENCY = 0.20  # ω₄ 정보일관성 (공통사실 매칭률)


def _transcript_quality_score(transcript_len: int, transcript_available: bool) -> float:
    """
    자막품질 점수 (0.0 ~ 1.0).
    자막 없으면 0.0, 있으면 길이 기준 선형 증가 (5000자 이상 = 1.0).
    """
    if not transcript_available or transcript_len == 0:
        return 0.0
    return min(1.0, transcript_len / 5000)


def _channel_credibility_score(subscriber_count: int) -> float:
    """
    채널신뢰도 점수 (0.0 ~ 1.0) — 구독자 수 기반 로그 스케일.
    - 100만+ : 1.0
    - 10만  : 0.8
    - 1만   : 0.6
    - 1000  : 0.4
    - 100   : 0.2
    - 0     : 0.0
    """
    if subscriber_count <= 0:
        return 0.0
    import math
    # log10(1_000_000) = 6  → 1.0
    # log10(100)       = 2  → 0.2
    score = math.log10(subscriber_count) / 6.0
    return round(min(1.0, max(0.0, score)), 4)


def _calc_credibility(video: Dict[str, Any], common_facts: List[str]) -> float:
    """
    신뢰도 = ω₁·자막품질 + ω₂·(1-광고확률) + ω₃·채널신뢰도 + ω₄·정보일관성
    """
    # ω₁ 자막품질
    transcript_q = _transcript_quality_score(
        video.get("transcript_len", 0),
        video.get("transcript_available", False),
    )

    # ω₂ (1 - 광고확률) — ad_score 는 0~100
    ad_free = 1.0 - (video.get("ad_score", 0) / 100.0)

    # ω₃ 채널신뢰도
    channel_cred = _channel_credibility_score(video.get("subscriber_count", 0))

    # ω₄ 정보일관성 — key_claims 와 공통사실 토큰 겹침 비율
    consistency = 0.0
    if common_facts and video.get("key_claims"):
        claim_text = " ".join(video["key_claims"]).lower()
        matched = sum(
            1 for fact in common_facts
            if any(word in claim_text for word in fact.lower().split() if len(word) > 2)
        )
        consistency = matched / max(len(common_facts), 1)

    score = (
        W_TRANSCRIPT  * transcript_q
        + W_AD_FREE     * ad_free
        + W_CHANNEL     * channel_cred
        + W_CONSISTENCY * consistency
    )
    return round(max(0.0, min(1.0, score)), 4)


# ── 메인 진입점 ───────────────────────────────────────────────────────────────

async def analyze_videos(
    keyword: str,
    videos: List[Dict[str, Any]],
    format_style: Optional[Dict[str, str]] = None,
    intent_type: str = "지식형",
) -> Dict[str, Any]:
    """
    영상 개별 병렬 분석 + 교차분석 + 콘텐츠 생성.

    Gemini 호출 횟수 (영상 5개 기준):
      이전: 1 (배치분석) + 1 (교차+콘텐츠 통합) = 2회
      현재: 5 (개별병렬) + 1 (교차+콘텐츠 통합) = 6회
      개선: Lost in the Middle 제거 → 모든 영상 균일한 품질

    Args:
        keyword:      검색 키워드
        videos:       selector_ai 반환 영상 목록 (최대 5개)
        format_style: intent_ai가 반환한 format_style (길이·톤 제어)
        intent_type:  사용자 검색 의도 (유희형/지식형/구매형) — 교차분석 프롬프트 분기
    """
    logger.info(f"[analyzer] '{keyword}' 영상 {len(videos)}개 — 의도={intent_type}, 개별 병렬 분석 시작")

    # Step 1: 영상별 개별 병렬 분석 [영상당 1회 호출]
    video_results = await _analyze_videos_parallel(keyword, videos)

    # Step 2: 의도 반영 교차분석 + 콘텐츠 통합 [1회 호출]
    content = await _cross_and_generate(keyword, video_results, format_style, intent_type)

    # Step 3: 최종 신뢰도 보정 (공통사실 기반, 호출 없음)
    common_facts = content["common_facts"]
    for vr in video_results:
        vr["credibility_score"] = _calc_credibility(vr, common_facts)

    # 출처 구성 — 분석에 사용된 영상 전체 포함 (필터 없음)
    # 광고 여부는 ad_detected 필드로 전달, 프론트에서 뱃지로 표시
    sources = [
        {
            "title":         v["title"],
            "url":           f"https://youtube.com/watch?v={v['video_id']}",
            "channel_title": v.get("channel_title", ""),
            "thumbnail_url": f"https://img.youtube.com/vi/{v['video_id']}/mqdefault.jpg",
            "ad_detected":   v.get("ad_detected", False),
        }
        for v in video_results
    ]

    logger.info(
        f"[analyzer] 완료 — 공통사실 {len(common_facts)}개 / "
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
