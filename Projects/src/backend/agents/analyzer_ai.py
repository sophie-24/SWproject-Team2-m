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

_ANALYZE_SEMAPHORE_SIZE    = 5  # 토픽당 최대 동시 Gemini 호출 수
_MAX_CLAIMS_PER_VIDEO      = 3  # 교차분석 프롬프트에 넘길 영상당 최대 핵심주장 수 (토큰 절감)
_TRANSCRIPT_SEMAPHORE_SIZE = 1  # YouTube 429 방지: 자막 요청 순차화 (동시 1개)
_TRANSCRIPT_FAIL_DELAY     = 5.0  # 자막 수집 실패 시 다음 요청 전 대기 시간 (초)
_TRANSCRIPT_SUCCESS_DELAY  = 2.0  # 자막 수집 성공 시에도 다음 요청 전 대기 (429 예방)


async def _analyze_single_video(
    keyword: str,
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
            "selection_tags":      video.get("selection_tags", []),
        }

    # 자막 있음 — Semaphore 획득 후 Gemini 호출
    lang = _detect_language(transcript)
    lang_inst = _build_lang_instruction(lang)
    if lang == "en":
        logger.info(f"  [언어감지] {video['video_id']}: 영어 자막")

    prompt = (
        f"검색 주제: {keyword}\n"
        f"제목: {video.get('title', '')} / 채널: {video.get('channel_title', '')}\n"
        f"{lang_inst}"
        f"자막:\n{transcript}\n"
        f"\n"
        f"위 유튜브 영상을 분석하세요. 반드시 아래 형식으로 답변하세요.\n"
        f"모든 답변은 한국어로 작성하세요.\n"
        f"\n"
        f"[분석 규칙]\n"
        f"- 먼저 이 영상이 검색 주제와 실제로 관련 있는지 판단하세요.\n"
        f"- 제목, 채널명, 자막 내용이 검색 주제와 직접 연결되지 않으면 억지로 연결하지 마세요.\n"
        f"- 단순히 같은 단어가 일부 등장한다는 이유만으로 관련성이 높다고 판단하지 마세요.\n"
        f"- 관련도가 낮은 영상이라도 자막에 등장하는 내용 중 검색 주제와 조금이라도 연관된 주장은 핵심주장에 포함하세요.\n"
        f"- 뮤직비디오, 음원, 라이브 무대, 직캠, 플레이리스트, lyrics, 가사 영상, cover 영상은 일반 정보성 영상으로 단정하지 마세요.\n"
        f"- 자막이 노래 가사, 반복 구절, 후렴, 감탄사 중심이면 이를 일반 정보성 발화로 해석하지 마세요.\n"
        f"- 가사 내용을 바탕으로 제품 추천, 지식 설명, 사회적 쟁점, 실천 조언을 추측하지 마세요.\n"
        f"- 검색 주제가 음악/아티스트/곡명/공연 자체라면 음악 영상은 분위기, 장르, 아티스트, 팬 반응, 화제성 등 실제 영상 맥락에 근거해 짧게 요약하세요.\n"
        f"- 자막이나 제목에 근거가 없는 내용은 작성하지 마세요.\n"
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
        "selection_tags":      video.get("selection_tags", []),
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
    # Step 1: 자막 수집 — 세마포어로 동시 요청 수 제한 (YouTube 429 방지)
    # 병렬 5개 동시 요청 → YouTube가 429로 차단하는 문제 완화
    _transcript_sem = asyncio.Semaphore(_TRANSCRIPT_SEMAPHORE_SIZE)

    async def _collect_with_throttle(video_id: str) -> Optional[str]:
        async with _transcript_sem:
            result = await asyncio.to_thread(_collect_transcript, video_id)
            # 성공/실패 모두 딜레이 — YouTube가 연속 요청을 감지하지 못하게
            delay = _TRANSCRIPT_FAIL_DELAY if result is None else _TRANSCRIPT_SUCCESS_DELAY
            await asyncio.sleep(delay)
            return result

    transcripts: List[Optional[str]] = list(await asyncio.gather(
        *[_collect_with_throttle(v["video_id"]) for v in videos]
    ))

    # Step 2: 영상별 개별 분석 — 병렬 (Semaphore로 동시 Gemini 호출 수 제한)
    semaphore = asyncio.Semaphore(_ANALYZE_SEMAPHORE_SIZE)
    results: List[Dict[str, Any]] = list(await asyncio.gather(
        *[
            _analyze_single_video(keyword, v, t, semaphore)
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
    "유희형":  ["요약", "쟁점"],                              # 흥미·화제성 위주
    "지식형":  ["공통사실", "쟁점", "요약", "장점", "단점"],  # 모든 섹션 포함
    "구매형":  ["공통사실", "쟁점", "요약", "장점", "단점"],          # 실용 비교 위주
}

_SECTION_GUIDE: Dict[str, str] = {
    "공통사실": (
        "2개 이상 영상에서 반복 확인되는 사실·정보·비교 기준만 최대 5개 작성.\n"
        "단일 영상의 주장, 광고성 주장, 추측은 제외.\n"
        "서로 같은 의미의 항목은 하나로 합치고, 각 항목은 \"- \"으로 시작.\n"
        "2개 이상 영상에서 공통으로 확인된 내용이 없으면 \"- 없음\"."
    ),
    "쟁점": (
        "영상들 사이에 실제로 다른 주장, 관점, 기준, 추천 방식이 있을 때만 최대 5개 작성.\n"
        "단순 표현 차이, 사소한 차이, 근거 없는 추측은 쟁점으로 만들지 말 것.\n"
        "각 항목은 무엇이 어떻게 다른지 분명히 쓰고, 차이가 없거나 근거가 약하면 \"- 없음\".\n"
        "각 항목은 \"- \"으로 시작. 없으면 \"- 없음\"."
    ),
    "요약": (
        "이 주제의 핵심을 정확히 3줄로 요약.\n"
        "1줄째: 사용자가 먼저 알아야 할 핵심 결론 또는 화제 포인트.\n"
        "2줄째: 여러 영상에서 반복 확인된 내용, 주요 반응, 또는 판단 근거.\n"
        "3줄째: 사용자가 주의해서 볼 점, 다음 판단 기준, 또는 볼 만한 포인트.\n"
        "공통사실·쟁점·장단점 항목을 그대로 반복하지 말고 종합해서 작성.\n"
        "각 줄은 \"- \"으로 시작."
    ),
    "장점": (
        "긍정적인 점, 유용한 점, 추천할 만한 이유를 최대 3개 작성.\n"
        "구매형은 성능·가격·사용성·가성비 중심, 지식형은 실천 효과·이해에 도움 되는 점 중심으로 작성.\n"
        "각 항목은 \"- \"로 시작."
    ),
    "단점": (
        "한계, 주의점, 반론, 확인해야 할 점을 최대 3개 작성.\n"
        "근거 없는 위험을 과장하지 말 것.\n"
        "구매형은 가격·성능 한계·사용 조건·광고/협찬 가능성 중심, 지식형은 오해 가능성·적용 한계 중심.\n"
        "각 항목은 \"- \"로 시작."
    ),
}

_INTENT_TONE: Dict[str, str] = {
    "유희형": (
        "가볍고 읽기 쉬운 말투. 과장된 감탄사, 억지 밈, 과도한 이모지는 피함. "
        "사용자가 빠르게 분위기와 화제 포인트를 파악할 수 있도록 짧고 선명하게 작성."
    ),
    "지식형": (
        "명확하고 신뢰감 있는 문체. 전문 용어는 쉽게 풀어서 설명. "
        "확인된 사실과 해석을 구분하고, 근거가 부족한 내용은 단정하지 않음."
    ),
    "구매형": (
        "실용적이고 객관적인 말투. 광고성 표현은 피하고, 선택 판단에 필요한 기준을 먼저 제시. "
        "장점과 단점을 균형 있게 비교하고, 결론은 사용자가 바로 판단할 수 있게 작성."
    ),
}

_INTENT_FOCUS: Dict[str, str] = {
    "유희형": (
        "인물, 콘텐츠, 팬 반응, 화제성, 재미 포인트 중심으로 정리. "
        "정보성 분석보다 '왜 화제가 되는지', '어떤 반응이 갈리는지', '볼 만한 포인트가 무엇인지'에 집중. "
        "실제 의견 차이가 있을 때만 쟁점으로 다루고, 논란을 억지로 만들지 않음."
    ),
    "지식형": (
        "배경, 핵심 개념, 원인, 관점 차이, 실천 팁, 주의점을 중심으로 정리. "
        "여러 영상에서 반복 확인되는 내용과 서로 다른 해석을 구분. "
        "사용자가 주제를 이해하고 실제로 적용할 수 있도록 결론보다 근거와 맥락을 함께 제공."
    ),
    "구매형": (
        "구매 또는 선택 판단에 필요한 비교 기준, 장점, 단점, 적합한 사용자, 구매 전 확인점을 중심으로 정리. "
        "가격, 성능, 사용성, 가성비, 후기, 광고/협찬 가능성을 구분. "
        "광고/협찬 가능성이 있는 주장은 보조 정보로만 활용하고, 구매를 유도하는 표현은 피함."
    ),
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
    # transcript_available + key_claims 가 있는 영상 우선
    valid = [v for v in video_results if v.get("transcript_available") and v.get("key_claims")]

    # key_claims가 없지만 요약이 있는 영상 → summary를 단일 claim으로 보완 (YouTube 429 등 자막 실패 시 복구)
    if not valid:
        for v in video_results:
            if v.get("transcript_available") and not v.get("key_claims"):
                summary_text = v.get("summary", "")
                if summary_text and summary_text not in ("분석 실패", "자막 없음", ""):
                    v["key_claims"] = [summary_text]
        valid = [v for v in video_results if v.get("key_claims")]

    if not valid:
        return {
            "common_facts": [],
            "controversies": [],
            "summary": ["자막을 가져오지 못했습니다. 잠시 후 다시 시도해주세요.", "", ""],
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
        for c in v["key_claims"][:_MAX_CLAIMS_PER_VIDEO]:
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


def _calc_credibility(video: Dict[str, Any], common_facts: List[str]) -> Dict[str, Any]:
    """
    신뢰도 = ω₁·자막품질 + ω₂·(1-광고확률) + ω₃·채널신뢰도 + ω₄·정보일관성

    Returns:
        {
            "score":      float,   # 최종 가중합 (0~1)
            "components": {        # 프론트 더보기 토글용 컴포넌트별 점수
                "transcript_quality": float,
                "ad_free":            float,
                "channel_credibility": float,
                "consistency":        float,
            }
        }
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
    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "components": {
            "transcript_quality":  round(transcript_q, 4),
            "ad_free":             round(ad_free, 4),
            "channel_credibility": round(channel_cred, 4),
            "consistency":         round(consistency, 4),
        },
    }


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
        cred = _calc_credibility(vr, common_facts)
        vr["credibility_score"]      = cred["score"]
        vr["credibility_components"] = cred["components"]  # 프론트 더보기 토글용

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
