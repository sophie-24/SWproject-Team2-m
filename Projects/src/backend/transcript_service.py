# YouTube 자막 수집 — youtube-transcript-api 우선, yt-dlp fallback
import os
import json
import tempfile
import subprocess
from typing import Optional

COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")


def get_transcript(video_id: str) -> Optional[list]:
    """
    자막 수집. youtube-transcript-api 우선, 실패 시 yt-dlp fallback.
    우선순위: 한국어 → 영어 → 자동생성
    """
    result = _get_via_api(video_id)
    if result:
        return result
    return _get_via_ytdlp(video_id)


def _get_via_api(video_id: str) -> Optional[list]:
    """youtube-transcript-api로 자막 수집"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        for langs in [["ko"], ["en"], ["ko", "en"]]:
            try:
                transcript = api.fetch(video_id, languages=langs)
                return [
                    {"text": s.text, "start": s.start, "duration": s.duration}
                    for s in transcript
                    if s.text.strip()
                ]
            except Exception:
                continue
    except Exception:
        pass
    return None


def _get_via_ytdlp(video_id: str) -> Optional[list]:
    """yt-dlp fallback"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = ["yt-dlp"]
    if os.path.exists(COOKIES_PATH):
        cmd += ["--cookies", COOKIES_PATH]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "%(id)s")
        cmd += [
            "--write-sub", "--write-auto-sub",
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
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = []
        for event in data.get("events", []):
            segs = event.get("segs", [])
            text = "".join(s.get("utf8", "") for s in segs).strip().replace("\n", " ")
            if text and text != " ":
                result.append({
                    "text": text,
                    "start": round(event.get("tStartMs", 0) / 1000, 2),
                    "duration": round(event.get("dDurationMs", 0) / 1000, 2),
                })
        return result if result else None
    except Exception:
        return None


def list_available_transcripts(video_id: str) -> list:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        return [{"language_code": t.language_code, "language": t.language} for t in transcript_list]
    except Exception:
        return []


def format_transcript_with_timestamps(transcript: list) -> list:
    return [
        {
            "text": entry["text"],
            "start": entry["start"],
            "end": round(entry["start"] + entry.get("duration", 0), 2),
        }
        for entry in transcript
        if entry.get("text")
    ]
