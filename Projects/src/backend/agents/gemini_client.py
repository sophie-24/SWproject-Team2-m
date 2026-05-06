import os
import re
from typing import List

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
_MODEL  = "gemini-2.5-flash-lite"


def call_gemini(
    prompt: str,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    """
    Gemini API 호출 후 응답 텍스트 반환.

    Args:
        prompt:      전송할 프롬프트 문자열
        temperature: 생성 다양성 (0.0 ~ 1.0, 기본 0.3)
        json_mode:   True이면 response_mime_type="application/json" 적용.
                     Gemini가 마크다운 코드블록 없이 순수 JSON만 반환하도록 강제한다.
                     JSON 구조화 응답이 필요한 에이전트(cluster_ai 등)에서만 사용.

    Returns:
        Gemini 응답 텍스트

    Raises:
        ValueError: 응답이 비어 있거나 안전 필터에 걸린 경우
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


def parse_section(text: str, section_name: str) -> str:
    """
    '[섹션명] ... [다음섹션]' 패턴에서 섹션 내용 추출.

    Args:
        text:         Gemini 응답 전체 텍스트
        section_name: 추출할 섹션 이름 (예: '요약', '광고점수')

    Returns:
        섹션 내용 문자열. 섹션이 없으면 빈 문자열.
    """
    pattern = rf"\[{section_name}\]\s*(.*?)(?=\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_bullet_list(text: str, section_name: str) -> List[str]:
    """
    섹션 내부의 '- ' 항목들을 리스트로 반환.

    Args:
        text:         Gemini 응답 전체 텍스트
        section_name: 추출할 섹션 이름

    Returns:
        항목 문자열 리스트. 없으면 빈 리스트.
    """
    section = parse_section(text, section_name)
    items = re.findall(r"^-\s+(.+)", section, re.MULTILINE)
    return [item.strip() for item in items if item.strip()]
