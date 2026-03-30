import re
from langchain_text_splitters import RecursiveCharacterTextSplitter


def clean_transcript(text: str) -> str:
    """
    자막 노이즈 제거:
    - 특수문자/이모지 제거
    - 반복어 제거 (ㅋㅋㅋ, ㅎㅎㅎ 등)
    - 과도한 공백 정리
    - 의미없는 짧은 토큰 제거
    """
    # 대괄호 안 내용 제거 ([박수], [음악] 등 자막 메타)
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\(.*?\)", "", text)

    # 이모지 제거
    text = re.sub(
        r"[\U00010000-\U0010FFFF\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]",
        "",
        text,
        flags=re.UNICODE,
    )

    # ㅋ, ㅎ, ㅠ 반복 제거
    text = re.sub(r"[ㅋㅎㅠㅜㅡ]{2,}", "", text)

    # 특수문자 제거 (한글, 영문, 숫자, 기본 문장부호만 남김)
    text = re.sub(r"[^\w\s가-힣a-zA-Z0-9.,!?]", " ", text)

    # 과도한 공백 정리
    text = re.sub(r"\s+", " ", text).strip()

    return text


def chunk_transcript(
    transcript_entries: list[dict],
    video_id: str,
    channel_id: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[dict]:
    """
    자막 엔트리를 전처리 후 청크로 분할.
    각 청크에 메타데이터(video_id, timestamp, channel_id, quality_score) 태깅.

    반환: [{"text": str, "metadata": {...}}, ...]
    """
    if not transcript_entries:
        return []

    # 텍스트 정제 및 timestamp 매핑 구성
    cleaned_entries = []
    for entry in transcript_entries:
        cleaned = clean_transcript(entry["text"])
        if len(cleaned) > 5:  # 너무 짧은 건 스킵
            cleaned_entries.append(
                {"text": cleaned, "start": entry["start"], "end": entry["end"]}
            )

    if not cleaned_entries:
        return []

    # 전체 텍스트 합치기 (위치 추적을 위해 구분자 포함)
    full_text = " ".join(e["text"] for e in cleaned_entries)

    # LangChain TextSplitter로 청크 분할
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[". ", "? ", "! ", "\n", " "],
    )
    chunks = splitter.split_text(full_text)

    # 각 청크에 메타데이터 태깅
    result = []
    cursor = 0  # 청크가 전체 텍스트에서 어느 위치인지 추적

    for chunk in chunks:
        # 청크 시작 위치에 해당하는 timestamp 추정
        char_pos = full_text.find(chunk, cursor)
        if char_pos == -1:
            char_pos = cursor
        cursor = char_pos + len(chunk)

        # 전체 텍스트 대비 비율로 timestamp 추정
        ratio = char_pos / max(len(full_text), 1)
        idx = min(int(ratio * len(cleaned_entries)), len(cleaned_entries) - 1)
        estimated_start = cleaned_entries[idx]["start"] if cleaned_entries else 0.0

        quality_score = _calc_quality_score(chunk)

        result.append(
            {
                "text": chunk,
                "metadata": {
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "timestamp": estimated_start,
                    "quality_score": quality_score,
                },
            }
        )

    return result


def _calc_quality_score(text: str) -> float:
    """
    청크 품질 점수 산출 (0.0 ~ 1.0).
    - 길이, 한글 비율, 문장 완성도 기반 단순 휴리스틱
    """
    if not text:
        return 0.0

    length_score = min(len(text) / 500, 1.0)

    korean_chars = len(re.findall(r"[가-힣]", text))
    korean_ratio = korean_chars / max(len(text), 1)
    korean_score = min(korean_ratio * 2, 1.0)

    sentence_endings = len(re.findall(r"[.!?]", text))
    sentence_score = min(sentence_endings / 5, 1.0)

    return round((length_score + korean_score + sentence_score) / 3, 2)
