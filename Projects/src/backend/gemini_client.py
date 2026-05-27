# Gemini API 비동기 래퍼 — call_gemini_async, JSON 파싱 유틸(parse_section, parse_bullet_list)
import asyncio
import logging
import os
import re
from typing import List

from google import genai
from google.genai import types
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
    after_log,
)

load_dotenv()

_logger = logging.getLogger(__name__)

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
_MODEL  = "gemini-3.1-flash-lite"

# 재시도 대상 HTTP 상태코드 — Rate Limit(429), Server Error(500/503)
_RETRYABLE_STATUS = {429, 500, 503}


def _is_retryable(exc: BaseException) -> bool:
    """429 / 5xx 계열 오류만 재시도. ValueError(빈 응답)는 재시도하지 않는다."""
    msg = str(exc).lower()
    # google-genai SDK는 상태코드를 메시지에 포함하거나 속성으로 노출
    if hasattr(exc, "status_code") and exc.status_code in _RETRYABLE_STATUS:
        return True
    if hasattr(exc, "code") and exc.code in _RETRYABLE_STATUS:
        return True
    # 메시지 기반 폴백 — "429", "quota", "rate limit", "503", "unavailable"
    retryable_keywords = ("429", "quota", "rate limit", "rate_limit", "503", "unavailable", "500", "internal")
    return any(kw in msg for kw in retryable_keywords)


@retry(
    wait=wait_exponential_jitter(initial=2, max=60, jitter=2),  # 2s → 4s → 8s … ±2s jitter, 최대 60s
    stop=stop_after_attempt(5),
    retry=retry_if_exception(_is_retryable),
    before_sleep=before_sleep_log(_logger, logging.WARNING),
    after=after_log(_logger, logging.INFO),
    reraise=True,
)
def call_gemini(
    prompt: str,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    """
    Gemini API 호출 후 응답 텍스트 반환.

    429 (Rate Limit) / 500 / 503 (Server Error) 발생 시 tenacity가 자동으로
    exponential backoff + jitter 재시도 (2s → 4s → 8s … 최대 60s, 최대 5회).
    ValueError (빈 응답 / 안전 필터) 는 재시도하지 않고 즉시 raise.

    Args:
        prompt:      전송할 프롬프트 문자열
        temperature: 생성 다양성 (0.0 ~ 1.0, 기본 0.3)
        json_mode:   True이면 response_mime_type="application/json" 적용.
                     Gemini가 마크다운 코드블록 없이 순수 JSON만 반환하도록 강제한다.
                     JSON 구조화 응답이 필요한 에이전트(title_topic_ai 등)에서만 사용.

    Returns:
        Gemini 응답 텍스트

    Raises:
        ValueError:          응답이 비어 있거나 안전 필터에 걸린 경우 (재시도 없음)
        tenacity.RetryError: 5회 재시도 후에도 실패한 경우
    """
    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )
    response = _client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=config,
    )
    if not response.text:
        finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        raise ValueError(f"Gemini 응답 없음 (finish_reason: {finish})")
    return response.text


async def call_gemini_async(
    prompt: str,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    """
    call_gemini의 async 래퍼.

    asyncio.to_thread로 실행하므로 이벤트 루프를 블로킹하지 않는다.
    여러 사용자가 동시에 파이프라인을 실행해도 각 Gemini 호출이
    await 시점에 다른 코루틴에 양보하여 동시 처리가 가능하다.
    """
    return await asyncio.to_thread(call_gemini, prompt, temperature, json_mode)


def _strip_markdown(text: str) -> str:
    """Gemini가 출력한 마크다운 기호 제거 — 프론트에서 plain text로 렌더링하므로 필요."""
    # **bold** / *italic* → 텍스트만
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    # __bold__ / _italic_
    text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
    return text


def parse_section(text: str, section_name: str) -> str:
    """
    '[섹션명] ... [다음섹션]' 패턴에서 섹션 내용 추출.

    Args:
        text:         Gemini 응답 전체 텍스트
        section_name: 추출할 섹션 이름 (예: '요약', '광고점수')

    Returns:
        섹션 내용 문자열 (마크다운 기호 제거). 섹션이 없으면 빈 문자열.
    """
    pattern = rf"\[{section_name}\]\s*(.*?)(?=\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return _strip_markdown(match.group(1).strip()) if match else ""


def parse_bullet_list(text: str, section_name: str) -> List[str]:
    """
    섹션 내부의 '- ' 항목들을 리스트로 반환.

    Args:
        text:         Gemini 응답 전체 텍스트
        section_name: 추출할 섹션 이름

    Returns:
        항목 문자열 리스트 (마크다운 기호 제거). 없으면 빈 리스트.
    """
    section = parse_section(text, section_name)
    items = re.findall(r"^-\s+(.+)", section, re.MULTILINE)
    return [_strip_markdown(item.strip()) for item in items if item.strip()]
