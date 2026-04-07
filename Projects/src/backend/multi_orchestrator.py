import os
import json
from typing import List, Dict, Any
import google.generativeai as genai
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

# ✅ Gemini 설정
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_model = genai.GenerativeModel("gemini-1.5-flash") # 구조적 분석에 최적화된 모델 사용

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=60),
)
def _call_gemini(prompt: str) -> str:
    response = _model.generate_content(
        prompt,
        generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
    )
    if response.text is None:
        raise ValueError("Gemini 응답 없음")
    return response.text

# ✅ 다중 영상 분석 전용 프롬프트 (구조적 통찰 구현)
_MULTI_ANALYSIS_PROMPT = """
당신은 여러 정보 소스를 비교 분석하여 핵심 통찰을 도출하는 전문가입니다.
제공된 여러 영상의 자막 데이터를 바탕으로, 정보 간의 관계를 분석하여 아래 JSON 형식으로 응답하세요.

분석 원칙:
1. [common_facts]: 최소 2개 이상의 소스에서 공통적으로 언급되거나 일치하는 사실(교집합)만 추출하세요.
2. [controversies]: 소스마다 설명이 다르거나, 수치가 상충하거나, 의견이 대립하는 지점(차이점)을 명확히 대조하세요.
3. 객관적 근거가 없는 내용은 제외하고, 데이터에 기반한 구조적 분석만 수행하세요.

입력 데이터 (여러 영상의 자막):
{transcripts}

응답 형식 (반드시 이 구조를 지킬 것):
{{
  "summary": {{
    "common_facts": [
      "공통 사실 1",
      "공통 사실 2"
    ],
    "controversies": [
      {{
        "issue": "쟁점 주제",
        "opinions": {{
          "source_A": "입장/데이터 A",
          "source_B": "입장/데이터 B"
        }},
        "reason": "차이가 발생하는 이유 분석"
      }}
    ]
  }}
}}
"""

def analyze_multi_videos(video_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """✅ 여러 영상의 데이터를 통합하여 구조적 통찰 도출"""
    
    # 여러 영상의 자막 텍스트 결합
    combined_transcripts = ""
    for idx, data in enumerate(video_data):
        title = data.get("title", f"Video {idx+1}")
        text = data.get("transcript", "")[:4000] # 각 영상당 컨텍스트 제한
        combined_transcripts += f"--- Source: {title} ---\n{text}\n\n"

    try:
        # ✅ 구조적 통찰 루프 실행
        raw_response = _call_gemini(_MULTI_ANALYSIS_PROMPT.format(transcripts=combined_transcripts))
        result = json.loads(raw_response)
        
        # ✅ 비판적 검증 (데이터 무결성 체크)
        if not result.get("summary", {}).get("common_facts"):
            result["summary"]["common_facts"] = ["분석 결과 공통된 사실을 도출할 수 있는 충분한 데이터가 없습니다."]
            
        return result

    except Exception as e:
        return {
            "error": f"통합 분석 중 오류 발생: {str(e)}",
            "summary": {"common_facts": [], "controversies": []}
        }
