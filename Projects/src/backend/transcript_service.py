# yt-dlp로 YouTube 자막 수집, 타임스탬프 포맷 변환, 언어별 자막 목록 조회
import os
import json
import tempfile
import subprocess
from typing import Optional

COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")


def _base_cmd() -> list:
    cmd = ["yt-dlp"]
    if os.path.exists(COOKIES_PATH):
        cmd += ["--cookies", COOKIES_PATH]
    return cmd


def list_available_transcripts(video_id: str) -> list:
    """영상에서 사용 가능한 자막 언어 목록 반환"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = _base_cmd() + ["--list-subs", "--skip-download", url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = result.stdout.splitlines()
        subs = []
        for line in lines:
            if line.strip() and not line.startswith("[") and "Language" not in line:
                parts = line.split()
                if parts:
                    subs.append({"language_code": parts[0], "raw": line.strip()})
        return subs
    except Exception:
        return []


def get_transcript(video_id: str) -> Optional[list]:
    """
    yt-dlp로 자막 수집.
    우선순위: 한국어 → 영어 → 자동생성 자막 → 기타
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "%(id)s")

        cmd = _base_cmd() + [
            "--write-sub",
            "--write-auto-sub",
            "--sub-lang", "ko,en",
            "--sub-format", "json3",
            "--skip-download",
            "--output", output_path,
            url,
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return None

        all_json3 = [
            os.path.join(tmpdir, f)
            for f in os.listdir(tmpdir)
            if f.endswith(".json3")
        ]

        sub_file = None
        for lang in ["ko-orig", "ko", "en"]:
            for f in all_json3:
                if f".{lang}." in f:
                    sub_file = f
                    break
            if sub_file:
                break

        if not sub_file and all_json3:
            sub_file = all_json3[0]

        if not sub_file:
            return None

        return _parse_json3(sub_file)


def _parse_json3(filepath: str) -> Optional[list]:
    """yt-dlp json3 자막 파일 파싱"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        result = []
        for event in data.get("events", []):
            start_ms = event.get("tStartMs", 0)
            duration_ms = event.get("dDurationMs", 0)
            segs = event.get("segs", [])

            text = "".join(s.get("utf8", "") for s in segs).strip()
            text = text.replace("\n", " ").strip()

            if text and text != " ":
                result.append({
                    "text": text,
                    "start": round(start_ms / 1000, 2),
                    "duration": round(duration_ms / 1000, 2),
                })

        return result if result else None
    except Exception:
        return None


def format_transcript_with_timestamps(transcript: list) -> list:
    """자막 리스트를 {text, start, end} 형식으로 정리"""
    return [
        {
            "text": entry["text"],
            "start": entry["start"],
            "end": round(entry["start"] + entry.get("duration", 0), 2),
        }
        for entry in transcript
        if entry.get("text")
    ]
