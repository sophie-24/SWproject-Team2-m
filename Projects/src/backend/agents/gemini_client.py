# backend/agents/gemini_client.py
"""
Gemini API 공통 클라이언트

- _call_gemini   : Gemini 호출 + 응답 검증
- _parse_section : [섹션명] 블록 텍스트 추출
- _parse_bullet_list : "- " 항목 리스트 추출

사용 규칙 (CLAUDE.md):
  - google.generativeai 패키지만 사용 (google.genai 금지)
  - model=, contents= 인자 사용 금지
  - 무료 티어 하루 20회 제한 → 호출 최소화
"""

import os
import re
from typing import List

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_model = genai.GenerativeModel("gemini-2.5-flash-lite")


def call_gemini(prompt: str, temperature: float = 0.3) -> str:
    """
    Gemini API 호출 후 응답 텍스트 반환.

    Args:
        prompt:      전송할 프롬프트 문자열
        temperature: 생성 다양성 (0.0 ~ 1.0, 기본 0.3)

    Returns:
        Gemini 응답 텍스트

    Raises:
        ValueError: 응답이 비어 있거나 안전 필터에 걸린 경우
    """
    response = _model.generate_content(
        prompt,
        generation_config={"temperature": temperature},
    )
    if response.text is None:
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
