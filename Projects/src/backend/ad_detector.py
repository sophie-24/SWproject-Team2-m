# 유튜브 광고/협찬 탐지 모듈 — description·자막 규칙(Layer 1-2) + API 플래그(Layer 3) + Gemini 블렌딩
"""
ad_detector.py — 유튜브 영상 광고 탐지 모듈

탐지 레이어:
  Layer 1. Description 규칙 기반 (무료, 즉시)
  Layer 2. 자막(Transcript) 규칙 기반 (무료, 즉시)
  Layer 3. YouTube Data API paidProductPlacementDetails (API 호출)
  Layer 4. Gemini 의미론적 분석 (유료, 느림 — analyzer_ai에서 수행)

이 모듈은 Layer 1~3만 담당.
Layer 4(Gemini) 점수는 analyzer_ai.py에서 계산 후 blend_scores()로 합산.

최종 점수 기준:
  0~30   광고 없음 (녹색)
  31~60  광고 의심 (주황)
  61~100 광고 확실 (빨강)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from logger import get_logger

logger = get_logger(__name__)


# ── 탐지 신호 데이터클래스 ────────────────────────────────────────────────────

@dataclass
class AdSignal:
    layer: str          # "description" | "transcript" | "api"
    rule: str           # 탐지 규칙 이름
    evidence: str       # 발견된 원문 (최대 80자)
    score: int          # 이 신호의 기여 점수 (0~35)


@dataclass
class AdDetectionResult:
    rule_score: int                       # Layer 1~3 합산 점수 (0~100)
    grade: str                            # "광고 없음" | "광고 의심" | "광고 확실"
    signals: list[AdSignal] = field(default_factory=list)

    @property
    def ad_detected(self) -> bool:
        return self.rule_score >= 61


# ── Layer 1: Description 규칙 패턴 ───────────────────────────────────────────

# (패턴, 점수, 규칙명)
_DESC_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    # ① 명시적 유료광고 고지 — 최고 신뢰도
    (re.compile(r"유료\s*(?:광고|프로모션|홍보)", re.I), 35, "유료광고_명시"),
    (re.compile(r"협찬\s*(?:영상|제품|콘텐츠)?|제품\s*협찬|브랜드\s*협찬", re.I), 35, "협찬_명시"),
    (re.compile(r"#\s*(?:ad|sponsored|advertisement|협찬|광고)\b", re.I), 35, "해시태그_광고"),
    (re.compile(r"paid\s*(?:promotion|partnership|sponsorship)", re.I), 35, "paid_promotion_EN"),
    (re.compile(r"이\s*영상은\s*광고(?:를\s*포함)?합니다", re.I), 35, "광고포함_고지"),

    # ② 제휴 링크 / 수익화 링크
    (re.compile(r"쿠팡파트너스|coupang\.com.*(?:rfl|aff)", re.I), 25, "쿠팡파트너스"),
    (re.compile(r"affiliate|어필리에이트|제휴\s*링크", re.I), 25, "제휴링크"),
    (re.compile(r"amzn\.to|amazon\.com.*tag=", re.I), 25, "아마존_제휴"),
    (re.compile(r"bit\.ly|tinyurl|ow\.ly", re.I), 10, "단축URL"),  # 약한 신호

    # ③ 할인 코드
    (re.compile(r"할인\s*코드|discount\s*code|coupon\s*code|use\s*code\s*[A-Z0-9]+", re.I), 20, "할인코드"),
    (re.compile(r"코드[:\s]+[A-Z0-9]{3,12}|code[:\s]+[A-Z0-9]{3,12}", re.I), 20, "코드명시"),
    (re.compile(r"\d+%\s*할인|할인\s*링크|special\s*offer", re.I), 15, "할인오퍼"),

    # ④ 구매 유도 / CTA
    (re.compile(r"지금\s*구매|구매\s*(?:링크|하기|하세요)|buy\s*now|shop\s*now", re.I), 15, "구매CTA"),
    (re.compile(r"설명\s*란\s*링크|아래\s*링크|링크는\s*(?:아래|설명)", re.I), 10, "설명란링크"),
    (re.compile(r"무료\s*체험|free\s*trial|구독\s*하면\s*할인", re.I), 10, "무료체험"),
]

# Description 첫 125자(YouTube 공시 의무 구간) 가중치
_FIRST_125_BOOST = 1.5


def _score_description(description: str) -> tuple[int, list[AdSignal]]:
    """Description에서 광고 신호 탐지 → 최대 40점"""
    if not description:
        return 0, []

    desc_lower = description
    first_125  = description[:125]
    signals: list[AdSignal] = []
    total = 0

    for pattern, base_score, rule in _DESC_PATTERNS:
        # 첫 125자 매칭이면 가중치 적용
        m_first = pattern.search(first_125)
        m_full  = pattern.search(desc_lower)
        match   = m_first or m_full

        if match:
            boost = _FIRST_125_BOOST if m_first else 1.0
            contrib = min(35, int(base_score * boost))
            total += contrib
            evidence = match.group(0)[:80]
            signals.append(AdSignal(
                layer="description", rule=rule,
                evidence=evidence, score=contrib,
            ))

    return min(75, total), signals


# ── Layer 2: 자막(Transcript) 규칙 패턴 ──────────────────────────────────────

_TRANS_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    # 명시적 광고 고지 발화
    (re.compile(r"이\s*영상은?\s*(?:.*?)\s*(?:협찬|후원|제공)(?:을\s*받았|해주셨|으로\s*제작)", re.I), 30, "협찬발화"),
    (re.compile(r"오늘\s*영상은?\s*광고|광고\s*영상입니다|광고임을\s*밝힙니다", re.I), 30, "광고발화"),
    (re.compile(r"sponsored\s*by|this\s*video\s*is\s*(?:sponsored|brought\s*to\s*you)", re.I), 30, "sponsored_발화"),
    (re.compile(r"유료\s*광고|paid\s*promotion\s*(?:포함|included)", re.I), 30, "유료광고_발화"),

    # 제품 제공/협찬 표현
    (re.compile(r"제품(?:을|을)?\s*(?:제공|협찬|보내)(?:받았|주셨|해주)", re.I), 25, "제품제공"),
    (re.compile(r"(?:브랜드|업체|회사)(?:에서|로부터)\s*(?:지원|제공|협찬)", re.I), 25, "업체지원"),
    (re.compile(r"gifted|c/o\s+\w+|sent\s+by\s+\w+", re.I), 20, "gifted_EN"),

    # 할인코드/구매유도 발화
    (re.compile(r"할인\s*코드|쿠폰\s*코드|discount\s*code", re.I), 15, "할인코드_발화"),
    (re.compile(r"링크\s*걸어\s*드릴게|링크\s*눌러서|설명란\s*참고", re.I), 10, "링크유도"),
    (re.compile(r"(?:지금|바로)\s*구매|구매하시면|주문하시면", re.I), 10, "구매유도_발화"),

    # 고빈도 브랜드/제품명 패턴 (약한 신호)
    (re.compile(r"\b(?:체험단|서포터즈|ambassador|홍보대사)\b", re.I), 20, "체험단"),
]

# 자막 내 광고성 문구 밀도 보정 (전체 자막 대비 매칭 비율)
_DENSITY_BONUS_THRESHOLD = 3  # 3개 이상 신호 → 보너스


def _score_transcript(transcript: str) -> tuple[int, list[AdSignal]]:
    """자막에서 광고 신호 탐지 → 최대 35점"""
    if not transcript:
        return 0, []

    signals: list[AdSignal] = []
    total = 0

    for pattern, base_score, rule in _TRANS_PATTERNS:
        matches = pattern.findall(transcript)
        if matches:
            evidence = (matches[0] if isinstance(matches[0], str) else matches[0][0])[:80]
            signals.append(AdSignal(
                layer="transcript", rule=rule,
                evidence=evidence, score=base_score,
            ))
            total += base_score

    # 고밀도 신호 보너스
    if len(signals) >= _DENSITY_BONUS_THRESHOLD:
        total += 10

    return min(35, total), signals


# ── Layer 3: YouTube Data API paidProductPlacementDetails ────────────────────

def _score_api_flag(paid_flag: Optional[bool]) -> tuple[int, list[AdSignal]]:
    """
    YouTube Data API videos.list(part=paidProductPlacementDetails) 응답 처리.

    참고: 이 필드는 크리에이터 본인 OAuth 없이는 공개 API로 접근 불가.
    youtube_search.py에서 status 파트를 함께 요청해 hasPaidProductPlacement를
    읽어올 수 있지만, 본인 채널이 아니면 null 반환이 대부분.
    읽혀올 경우 최고 신뢰도 신호(+40)로 처리.
    """
    if paid_flag is True:
        return 40, [AdSignal(
            layer="api",
            rule="YouTube_공식_유료광고_플래그",
            evidence="hasPaidProductPlacement = true",
            score=40,
        )]
    return 0, []


# ── 점수 블렌딩 (Layer 1~3 룰 + Layer 4 Gemini) ───────────────────────────────

def blend_scores(rule_score: int, gemini_score: int) -> int:
    """
    룰 기반 점수와 Gemini 점수를 합산해 최종 ad_score 반환.

    전략:
    - rule ≥ 70: 명시적 신호 확정 → rule 결과 그대로 사용
    - rule ≥ 35: description 명시 고지 있음 → rule 우선 (max 적용)
    - 그 외:    가중 평균 rule 40% + gemini 60%
    - 어느 쪽이든 ≥ 80이면 max 적용 (광고 놓치지 않도록 보수적 판단)
    """
    if rule_score >= 70:
        return min(100, rule_score)
    if rule_score >= 35:
        # 명시적 description 고지 — Gemini보다 신뢰
        return min(100, max(rule_score, gemini_score))
    if max(rule_score, gemini_score) >= 80:
        return min(100, max(rule_score, gemini_score))
    blended = int(0.4 * rule_score + 0.6 * gemini_score)
    return min(100, blended)


def grade(score: int) -> str:
    if score <= 30:
        return "광고 없음"
    if score <= 60:
        return "광고 의심"
    return "광고 확실"


# ── 공개 인터페이스 ───────────────────────────────────────────────────────────

def detect_ad_signals(
    description: str = "",
    transcript: str = "",
    paid_flag: Optional[bool] = None,
) -> AdDetectionResult:
    """
    Layer 1~3 규칙 기반 광고 탐지 실행.
    Gemini(Layer 4) 점수는 별도로 받아 blend_scores()로 합산.

    Args:
        description:  영상 설명란 전체 텍스트
        transcript:   정제된 자막 텍스트
        paid_flag:    YouTube API hasPaidProductPlacement 값 (없으면 None)

    Returns:
        AdDetectionResult (rule_score, grade, signals)
    """
    desc_score,  desc_sigs  = _score_description(description)
    trans_score, trans_sigs = _score_transcript(transcript)
    api_score,   api_sigs   = _score_api_flag(paid_flag)

    # API 플래그가 있으면 최고 우선순위
    if api_score >= 40:
        total = 100
    else:
        total = min(100, desc_score + trans_score)

    all_signals = desc_sigs + trans_sigs + api_sigs

    logger.debug(
        f"[ad_detector] desc={desc_score} trans={trans_score} "
        f"api={api_score} → rule_total={total}"
    )

    return AdDetectionResult(
        rule_score=total,
        grade=grade(total),
        signals=all_signals,
    )
