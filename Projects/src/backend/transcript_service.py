# youtube-transcript-api(1순위) + yt-dlp(fallback) 자막 수집 모듈
# 외부 공개 함수: get_transcript / format_transcript_with_timestamps / list_available_transcripts

import os
import json
import time
import tempfile
import subprocess
from typing import Optional

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from logger import get_logger
logger = get_logger(__name__)

COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

# YOUTUBE_COOKIES_B64 환경변수에 cookies.txt를 base64 인코딩한 값을 넣으면
# 서버 시작 시 자동으로 cookies.txt로 복원 — Cloudtype 배포 환경에서 YouTube 429 우회용
_cookies_b64 = os.getenv("YOUTUBE_COOKIES_B64", "")
if _cookies_b64 and not os.path.exists(COOKIES_PATH):
    try:
        import base64
        with open(COOKIES_PATH, "wb") as _f:
            _f.write(base64.b64decode(_cookies_b64))
        logger.info("[transcript] cookies.txt 복원 완료 (YOUTUBE_COOKIES_B64)")
    except Exception as _e:
        logger.warning("[transcript] cookies.txt 복원 실패: %s", _e)

_LANG_PRIORITY = ["ko", "en"]
# 쿠키 파일이 있으면 인증된 요청으로 YouTube 429 우회 (v1.2.4: http_client로 전달)
if os.path.exists(COOKIES_PATH):
    try:
        import requests
        from http.cookiejar import MozillaCookieJar
        _session = requests.Session()
        _jar = MozillaCookieJar(COOKIES_PATH)
        _jar.load(ignore_discard=True, ignore_expires=True)
        _session.cookies = _jar
        _api = YouTubeTranscriptApi(http_client=_session)
        logger.info("[transcript] YouTubeTranscriptApi 쿠키 세션 적용 완료")
    except Exception as _e:
        logger.warning("[transcript] 쿠키 세션 적용 실패, 기본 모드 사용: %s", _e)
        _api = YouTubeTranscriptApi()
else:
    _api = YouTubeTranscriptApi()

# ── 자막 캐시 ─────────────────────────────────────────────────────────────────
# 인기 영상은 여러 사용자가 동일 video_id를 요청하므로 인메모리 캐시로 중복 수집 방지.
# Redis 도입 전 임시 구현 — 단일 워커 환경에서만 안전.
_TRANSCRIPT_CACHE_TTL = 86400  # 24시간 (초)
_transcript_cache: dict = {}   # { video_id: {"data": list, "ts": float} }


def _cache_get(video_id: str) -> Optional[list]:
    """캐시에서 자막 반환. 만료됐거나 없으면 None."""
    entry = _transcript_cache.get(video_id)
    if entry and (time.time() - entry["ts"]) < _TRANSCRIPT_CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(video_id: str, data: list) -> None:
    """자막을 캐시에 저장."""
    _transcript_cache[video_id] = {"data": data, "ts": time.time()}


# ── 공개 API ──────────────────────────────────────────────────────────────────

def get_transcript(video_id: str) -> Optional[list]:
    """
    자막 수집. 캐시 확인 -> youtube-transcript-api -> yt-dlp fallback 순.
    반환: [{"text": str, "start": float, "duration": float}, ...] or None
    """
    cached = _cache_get(video_id)
    if cached is not None:
        logger.info("[transcript] %s: 캐시 히트 (%d개)", video_id, len(cached))
        return cached

    result = _fetch_via_api(video_id)
    if result is not None:
        _cache_set(video_id, result)
        return result

    logger.info("[transcript] %s: API 실패 -> yt-dlp fallback", video_id)
    result = _fetch_via_ytdlp(video_id)
    if result is not None:
        _cache_set(video_id, result)
    return result


def format_transcript_with_timestamps(transcript: list) -> list:
    """자막 리스트를 {text, start, end} 형식으로 정리"""
    return [
        {
            "text":  entry["text"],
            "start": entry["start"],
            "end":   round(entry["start"] + entry.get("duration", 0), 2),
        }
        for entry in transcript
        if entry.get("text")
    ]


def list_available_transcripts(video_id: str) -> list:
    """영상에서 사용 가능한 자막 언어 목록 반환"""
    try:
        transcript_list = _api.list(video_id)
        result = []
        for t in transcript_list:
            result.append({
                "language_code": t.language_code,
                "language":      t.language,
                "is_generated":  t.is_generated,
                "raw":           t.language_code + " (" + t.language + ")"
                                 + (" [auto]" if t.is_generated else ""),
            })
        return result
    except Exception as e:
        logger.warning("[transcript] %s: list_transcripts 실패 - %s", video_id, e)
        return _list_via_ytdlp(video_id)


# ── Strategy A: youtube-transcript-api ───────────────────────────────────────

_RETRY_DELAYS = [3, 8, 20]  # 429 시 재시도 대기 시간 (초) — 3회 retry


def _fetch_via_api(video_id: str) -> Optional[list]:
    """
    youtube-transcript-api 로 자막 수집.
    수동 자막(ko->en) 우선, 없으면 자동생성(ko->en) 시도.
    429 발생 시 최대 3회 retry (3s → 8s → 20s backoff).
    """
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            logger.info("[transcript] %s: 429 재시도 %d회차 (%ds 대기)", video_id, attempt, delay)
            time.sleep(delay)
        try:
            transcript_list = _api.list(video_id)

            # 수동 자막 우선
            for lang in _LANG_PRIORITY:
                try:
                    t = transcript_list.find_manually_created_transcript([lang])
                    entries = t.fetch()
                    logger.info("[transcript] %s: 수동자막(%s) %d개", video_id, lang, len(entries))
                    return _normalize_entries(entries)
                except NoTranscriptFound:
                    continue

            # 자동생성 자막
            for lang in _LANG_PRIORITY:
                try:
                    t = transcript_list.find_generated_transcript([lang])
                    entries = t.fetch()
                    logger.info("[transcript] %s: 자동자막(%s) %d개", video_id, lang, len(entries))
                    return _normalize_entries(entries)
                except NoTranscriptFound:
                    continue

            logger.info("[transcript] %s: 지원 언어 없음", video_id)
            return None

        except (TranscriptsDisabled, VideoUnavailable) as e:
            logger.info("[transcript] %s: 자막 비활성화 - %s", video_id, e)
            return None
        except Exception as e:
            err_str = str(e)
            if "429" in err_str and attempt < len(_RETRY_DELAYS):
                logger.warning("[transcript] %s: API 예외 - %s", video_id, e)
                continue  # retry
            logger.warning("[transcript] %s: API 예외 - %s", video_id, e)
            return None

    return None


def _normalize_entries(entries) -> Optional[list]:
    """youtube-transcript-api 응답 -> 내부 표준 형식 변환"""
    result = []
    for entry in entries:
        # SDK v1.x: 속성 접근 / v0.x: dict 접근 모두 지원
        try:
            text     = entry.text     if hasattr(entry, "text")     else entry["text"]
            start    = entry.start    if hasattr(entry, "start")    else entry["start"]
            duration = entry.duration if hasattr(entry, "duration") else entry.get("duration", 0)
        except Exception:
            continue

        text = str(text).replace("\n", " ").strip()
        if text:
            result.append({
                "text":     text,
                "start":    round(float(start), 2),
                "duration": round(float(duration), 2),
            })
    return result if result else None


# ── Strategy B: yt-dlp (fallback) ────────────────────────────────────────────

def _base_cmd() -> list:
    """yt-dlp 기본 커맨드 (쿠키 있으면 포함)"""
    cmd = ["yt-dlp"]
    if os.path.exists(COOKIES_PATH):
        cmd += ["--cookies", COOKIES_PATH]
    return cmd


def _fetch_via_ytdlp(video_id: str) -> Optional[list]:
    """yt-dlp fallback. 한국어 -> 영어 -> 자동생성 순."""
    url = "https://www.youtube.com/watch?v=" + video_id

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
            logger.warning("[transcript] %s: yt-dlp timeout", video_id)
            return None

        all_json3 = [
            os.path.join(tmpdir, f)
            for f in os.listdir(tmpdir)
            if f.endswith(".json3")
        ]

        sub_file = None
        for lang in ["ko-orig", "ko", "en"]:
            for f in all_json3:
                if ("." + lang + ".") in f:
                    sub_file = f
                    break
            if sub_file:
                break

        if not sub_file and all_json3:
            sub_file = all_json3[0]

        if not sub_file:
            return None

        result = _parse_json3(sub_file)
        if result:
            logger.info("[transcript] %s: yt-dlp fallback %d개", video_id, len(result))
        return result


def _parse_json3(filepath: str) -> Optional[list]:
    """yt-dlp json3 자막 파일 파싱"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        result = []
        for event in data.get("events", []):
            start_ms    = event.get("tStartMs", 0)
            duration_ms = event.get("dDurationMs", 0)
            segs        = event.get("segs", [])

            text = "".join(s.get("utf8", "") for s in segs).strip()
            text = text.replace("\n", " ").strip()

            if text and text != " ":
                result.append({
                    "text":     text,
                    "start":    round(start_ms / 1000, 2),
                    "duration": round(duration_ms / 1000, 2),
                })

        return result if result else None
    except Exception:
        return None


def _list_via_ytdlp(video_id: str) -> list:
    """list_available_transcripts yt-dlp fallback"""
    url = "https://www.youtube.com/watch?v=" + video_id
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
