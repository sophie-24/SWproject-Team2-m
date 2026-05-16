# 영상 제목 기반 관심 토픽 추출 에이전트
# 입력: 영상 제목(title)만 사용
# 출력: topic, normalized_topic, related_keywords
# 재사용: /analyze_video, /interests 에서 호출
import json
import re
from typing import Optional

from gemini_client import call_gemini_async
from logger import get_logger

logger = get_logger(__name__)


# ── 상수 ──────────────────────────────────────────────────────────────────────

# fallback 시 제목에서 제거할 노이즈 패턴
_NOISE_PATTERNS = [
    r"\[.*?\]",           # [브이로그], [ENG SUB] 등 대괄호
    r"\(.*?\)",           # (feat. ...) 등 소괄호
    r"【.*?】",            # 일본식 괄호
    r"\|\s*[^|]+$",       # | 이후 채널명
    r"#\S+",              # 해시태그
    r"EP\.?\s*\d+",       # EP.1, EP1
    r"\d+화",             # 1화
    r"ft\..+",            # ft. 아무개
    r"(?i)shorts?",       # Shorts
    r"\d{4}\.\d{2}\.\d{2}",  # 날짜
]

# 낚시성/과장형 표현 — 제거 후 핵심 명사구만 남김
_CLICKBAIT_PATTERNS = [
    r"(?i)(충격|경악|대박|놀라운|믿을 수 없는|역대급|레전드|초대박|핵폭탄|미쳤다|난리났다|떴다|터졌다)",
    r"(?i)(드디어|마침내|결국|갑자기|갑작스럽게)",
    r"(?i)(꼭 봐야 할|당장 봐야 할|지금 바로)",
    r"(?i)(논란|사건|사고|폭로|고백|실화|실제상황)",
]


# ── 메인 함수 ─────────────────────────────────────────────────────────────────

async def extract_topic_from_title(title: str) -> dict:
    """
    영상 제목에서 관심 토픽을 추출한다.

    Args:
        title: YouTube 영상 제목 (채널명·자막·검색어 등 추가 정보 없이 제목만)

    Returns:
        {
            "topic":             str,       # 사용자에게 보여줄 대표 관심 토픽 (한국어 명사구)
            "normalized_topic":  str,       # 중복 판단 및 5개 제한 카운트 기준 (소문자·공백 정규화)
            "related_keywords":  list[str], # 연관 키워드 (2~4개)
        }
    """
    if not title or not title.strip():
        return _fallback_result("알 수 없음")

    try:
        result = await _call_gemini(title.strip())
        logger.info(f"[title_topic_ai] 토픽 추출 완료: '{title[:30]}' → {result['topic']}")
        return result
    except Exception as e:
        logger.warning(f"[title_topic_ai] Gemini 실패, fallback 적용: {e}")
        return _fallback_from_title(title)


# ── Gemini 호출 ───────────────────────────────────────────────────────────────

async def _call_gemini(title: str) -> dict:
    prompt = f"""당신은 유튜브 영상 제목을 보고 사용자의 관심 토픽을 추출하는 AI입니다.

[영상 제목]
{title}

[규칙]
1. 제목만 보고 핵심 관심 토픽을 한국어 명사구(2~5글자 권장)로 추출하세요.
2. 낚시성·과장형 표현("충격", "대박", "레전드" 등)은 무시하고 실제 주제를 파악하세요.
3. 너무 구체적인 고유명사(사람 이름, 특정 상품명)보다 상위 카테고리 토픽을 선택하세요.
   예) "갤럭시 S25 언박싱" → "스마트폰 리뷰" / "손흥민 골 모음" → "축구"
4. topic은 뉴스레터 메일 주제로 쓰기 좋은 간결한 명사구여야 합니다.
5. normalized_topic은 topic을 소문자·영문·숫자·공백만 남긴 형태 또는 한글 그대로 사용하되
   조사·어미를 제거한 최소 형태로 작성하세요 (중복 판단용).
6. related_keywords는 이 토픽과 연관된 검색 키워드 2~4개를 작성하세요.

[출력 형식 - 반드시 JSON만 출력]
{{
  "topic": "토픽명",
  "normalized_topic": "정규화된토픽",
  "related_keywords": ["키워드1", "키워드2", "키워드3"]
}}"""

    raw = await call_gemini_async(prompt, temperature=0.1, json_mode=True)
    data = json.loads(raw)
    return _validate_and_normalize(data)


# ── 결과 검증 및 정규화 ────────────────────────────────────────────────────────

def _validate_and_normalize(data: dict) -> dict:
    topic = str(data.get("topic", "")).strip()
    normalized = str(data.get("normalized_topic", "")).strip()
    keywords = data.get("related_keywords", [])

    if not topic:
        raise ValueError("topic이 비어 있습니다")

    if not normalized:
        normalized = _normalize(topic)

    if not isinstance(keywords, list):
        keywords = []

    keywords = [str(k).strip() for k in keywords if str(k).strip()][:4]

    return {
        "topic": topic,
        "normalized_topic": normalized,
        "related_keywords": keywords,
    }


# ── Fallback (Gemini 실패 시) ─────────────────────────────────────────────────

def _fallback_from_title(title: str) -> dict:
    """
    Gemini 호출 실패 시 제목 문자열 기반으로 토픽을 추출한다.
    노이즈 패턴·낚시성 표현 제거 후 앞 명사구를 topic으로 사용.
    """
    cleaned = title

    # 노이즈 제거
    for pattern in _NOISE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)

    # 낚시성 표현 제거
    for pattern in _CLICKBAIT_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)

    # 구분자(|, /, ·) 기준 앞부분만 사용
    for sep in ["|", "/", "·", "ㅣ"]:
        if sep in cleaned:
            cleaned = cleaned.split(sep)[0]

    # 공백 정리 후 앞 20자 이내 명사구 추출
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    topic = cleaned[:20].strip() if cleaned else title[:15].strip()

    logger.info(f"[title_topic_ai] fallback 결과: '{title[:30]}' → '{topic}'")
    return _fallback_result(topic)


def _fallback_result(topic: str) -> dict:
    return {
        "topic": topic,
        "normalized_topic": _normalize(topic),
        "related_keywords": [],
    }


def _normalize(text: str) -> str:
    """중복 판단용 정규화: 소문자 변환 + 앞뒤 공백 제거 + 연속 공백 단일화."""
    return re.sub(r"\s+", " ", text.lower()).strip()
