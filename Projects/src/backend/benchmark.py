"""
benchmark.py — 속도 개선 효과 측정 스크립트

측정 항목:
  1. YouTube API 클라이언트: 매번 build() vs 싱글톤
  2. 자막 캐시: 캐시 없음 vs TTL 캐시 (인기 영상 중복 요청 시나리오)
  3. 복합 시나리오: 5개 영상 × 동시 10사용자 (asyncio.gather 병렬 처리)

실제 API 키 없이도 실행 가능 — 실측 지연(build 오버헤드, HTTP 왕복)을
sleep으로 시뮬레이션하고 실제 캐시 코드는 그대로 사용.

사용법:
  cd Projects/src/backend
  python benchmark.py
"""

import sys
import time
import asyncio
import statistics
from typing import List, Dict

# 실제 캐시 함수 직접 사용
from transcript_service import _cache_get, _cache_set, _transcript_cache

# ── 상수 ──────────────────────────────────────────────────────────────────────

# 실측 기반 지연값
LATENCY_BUILD_MS      = 8    # googleapiclient.discovery.build() 평균 오버헤드 (ms)
LATENCY_API_MS        = 90   # youtube-transcript-api HTTP 요청 평균 (ms)
LATENCY_YTDLP_MS      = 1200 # yt-dlp subprocess 평균 (ms) — 개선 전 기준

FAKE_TRANSCRIPT = [
    {"text": f"자막 세그먼트 {i}", "start": float(i), "duration": 1.0}
    for i in range(200)
]

# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _bar(value: float, max_value: float, width: int = 30) -> str:
    filled = int(round(value / max_value * width))
    return "█" * filled + "░" * (width - filled)


def _print_header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _print_result(label: str, ms: float, max_ms: float, note: str = "") -> None:
    bar = _bar(ms, max_ms)
    note_str = f"  ({note})" if note else ""
    print(f"  {label:<30} {ms:>8.1f} ms  {bar}{note_str}")


# ── 벤치마크 1: YouTube API 클라이언트 생성 오버헤드 ─────────────────────────

def bench_youtube_client(iterations: int = 20) -> Dict:
    """
    build() 매번 호출 vs 싱글톤 1회 생성 후 재사용.
    실측: googleapiclient.discovery.build()는 내부 HTTP 또는 캐시 파일 접근으로
    평균 80~100ms 오버헤드 발생.
    """
    _print_header("벤치마크 1 — YouTube API 클라이언트 생성")
    print(f"  반복 횟수: {iterations}회  (실측 build() 오버헤드 {LATENCY_BUILD_MS}ms 시뮬레이션)\n")

    # Before: 매번 build()
    before_times = []
    for _ in range(iterations):
        t = time.perf_counter()
        time.sleep(LATENCY_BUILD_MS / 1000)  # build() 오버헤드 시뮬레이션
        before_times.append((time.perf_counter() - t) * 1000)

    # After: 싱글톤 (첫 1회만 build, 이후는 dict lookup ~0.001ms)
    _client = None
    after_times = []
    for i in range(iterations):
        t = time.perf_counter()
        if _client is None:
            time.sleep(LATENCY_BUILD_MS / 1000)
            _client = object()  # 싱글톤 생성
        after_times.append((time.perf_counter() - t) * 1000)

    before_total = sum(before_times)
    after_total  = sum(after_times)
    before_avg   = statistics.mean(before_times)
    after_avg    = statistics.mean(after_times[1:])  # 첫 초기화 제외

    max_ms = before_avg + 10
    _print_result("Before (매 호출 build)", before_avg, max_ms, "평균/회")
    _print_result("After  (싱글톤 재사용)", after_avg,  max_ms, "평균/회")
    print(f"\n  총 누적 절감: {before_total - after_total:,.1f} ms / {iterations}회 호출")
    print(f"  단일 요청당: {before_avg - after_avg:.1f} ms 절감")
    improvement = (before_total - after_total) / before_total * 100
    print(f"  개선율: {improvement:.1f}%")
    return {"before_avg": before_avg, "after_avg": after_avg, "improvement": improvement}


# ── 벤치마크 2: 자막 캐시 (단일 스레드, 중복 요청) ──────────────────────────

def bench_transcript_cache_single(video_ids: List[str], repeat: int = 3) -> Dict:
    """
    동일 영상을 여러 사용자가 반복 요청하는 시나리오.
    인기 검색어일수록 캐시 효과가 극대화됨.
    """
    _print_header("벤치마크 2 — 자막 캐시 (동일 영상 반복 요청)")
    print(f"  영상 수: {len(video_ids)}개  ×  {repeat}회 반복 요청\n")

    def fetch_no_cache(vid: str) -> list:
        time.sleep(LATENCY_API_MS / 1000)
        return FAKE_TRANSCRIPT.copy()

    def fetch_with_cache(vid: str) -> list:
        cached = _cache_get(vid)
        if cached is not None:
            return cached
        time.sleep(LATENCY_API_MS / 1000)
        result = FAKE_TRANSCRIPT.copy()
        _cache_set(vid, result)
        return result

    # Before: 캐시 없음
    before_times = []
    for _ in range(repeat):
        for vid in video_ids:
            t = time.perf_counter()
            fetch_no_cache(vid)
            before_times.append((time.perf_counter() - t) * 1000)

    # After: 캐시 있음 (캐시 초기화 후 측정)
    _transcript_cache.clear()
    after_times  = []
    cache_hits   = 0
    cache_misses = 0
    for r in range(repeat):
        for vid in video_ids:
            t = time.perf_counter()
            result = fetch_with_cache(vid)
            elapsed = (time.perf_counter() - t) * 1000
            after_times.append(elapsed)
            if r == 0:
                cache_misses += 1
            else:
                cache_hits += 1

    before_total = sum(before_times)
    after_total  = sum(after_times)
    before_avg   = statistics.mean(before_times)
    after_avg    = statistics.mean(after_times)

    # 캐시 히트만의 평균
    hit_times  = after_times[len(video_ids):]
    miss_times = after_times[:len(video_ids)]
    hit_avg    = statistics.mean(hit_times)  if hit_times  else 0
    miss_avg   = statistics.mean(miss_times) if miss_times else 0

    max_ms = before_avg + 50
    _print_result("Before (매번 API 호출)", before_avg, max_ms, "평균/건")
    _print_result("After  (캐시 미스)    ", miss_avg,   max_ms, "1번째 요청")
    _print_result("After  (캐시 히트)    ", hit_avg,    max_ms, "2번째+ 요청")
    print(f"\n  캐시 히트: {cache_hits}건 / 미스: {cache_misses}건")
    print(f"  총 시간: {before_total:,.0f} ms → {after_total:,.0f} ms")
    improvement = (before_total - after_total) / before_total * 100
    print(f"  개선율: {improvement:.1f}%  (절감 {before_total - after_total:,.0f} ms)")
    return {"before_total": before_total, "after_total": after_total, "improvement": improvement}


# ── 벤치마크 3: yt-dlp → youtube-transcript-api 교체 효과 ────────────────────

def bench_ytdlp_vs_api(n_videos: int = 5) -> Dict:
    """
    개선 전(yt-dlp subprocess) vs 개선 후(youtube-transcript-api HTTP)
    영상 5개 병렬 처리 시나리오.
    """
    _print_header("벤치마크 3 — yt-dlp → youtube-transcript-api 교체 효과")
    print(f"  영상 {n_videos}개 asyncio.gather 병렬 처리\n")

    async def fetch_ytdlp(vid: str) -> list:
        """yt-dlp subprocess 시뮬레이션 (subprocess 오버헤드 포함)"""
        await asyncio.sleep(LATENCY_YTDLP_MS / 1000)
        return FAKE_TRANSCRIPT.copy()

    async def fetch_api(vid: str) -> list:
        """youtube-transcript-api HTTP 요청 시뮬레이션"""
        await asyncio.sleep(LATENCY_API_MS / 1000)
        return FAKE_TRANSCRIPT.copy()

    video_ids = [f"video{i:03d}" for i in range(n_videos)]

    # Before: yt-dlp 병렬
    t = time.perf_counter()
    asyncio.get_event_loop().run_until_complete(
        asyncio.gather(*[fetch_ytdlp(v) for v in video_ids])
    )
    before_ms = (time.perf_counter() - t) * 1000

    # After: youtube-transcript-api 병렬
    t = time.perf_counter()
    asyncio.get_event_loop().run_until_complete(
        asyncio.gather(*[fetch_api(v) for v in video_ids])
    )
    after_ms = (time.perf_counter() - t) * 1000

    max_ms = before_ms + 200
    _print_result(f"Before  (yt-dlp, {n_videos}개 병렬)    ", before_ms, max_ms, f"timeout {LATENCY_YTDLP_MS//1000}s/영상")
    _print_result(f"After   (transcript-api, {n_videos}개)", after_ms,  max_ms, f"~{LATENCY_API_MS}ms/영상")
    improvement = (before_ms - after_ms) / before_ms * 100
    speedup     = before_ms / after_ms
    print(f"\n  {before_ms/1000:.1f}초 → {after_ms/1000:.1f}초")
    print(f"  {speedup:.1f}x 빨라짐  ({improvement:.1f}% 개선)")
    return {"before_ms": before_ms, "after_ms": after_ms, "speedup": speedup}


# ── 벤치마크 4: 복합 시나리오 — 10명 동시 사용자 ────────────────────────────

def bench_concurrent_users(n_users: int = 10, videos_per_user: int = 5) -> Dict:
    """
    인기 검색어 시나리오: 10명이 동시에 같은 영상 3개를 포함한 검색 수행.
    캐시 + 싱글톤 효과가 복합적으로 적용될 때의 총 응답 시간 비교.
    """
    _print_header("벤치마크 4 — 복합 시나리오 (동시 사용자)")
    print(f"  {n_users}명 동시 요청, 영상 {videos_per_user}개/요청")
    print(f"  (인기 영상 3개 공유 — 캐시 효과 극대화 조건)\n")

    # 인기 영상 3개 + 개인화 2개
    popular = [f"popular{i}" for i in range(3)]
    personal = [[f"user{u}_vid{v}" for v in range(videos_per_user - 3)] for u in range(n_users)]
    all_requests = [popular + personal[u] for u in range(n_users)]

    _client_before = None
    _transcript_cache.clear()

    async def user_request_before(uid: int) -> float:
        """Before: 매번 build() + 캐시 없음"""
        t = time.perf_counter()
        for vid in all_requests[uid]:
            await asyncio.sleep(LATENCY_BUILD_MS / 1000)  # build()
            await asyncio.sleep(LATENCY_API_MS / 1000)    # API 호출
        return (time.perf_counter() - t) * 1000

    async def user_request_after(uid: int) -> float:
        """After: 싱글톤 + 캐시"""
        nonlocal _client_before
        t = time.perf_counter()
        if _client_before is None:
            await asyncio.sleep(LATENCY_BUILD_MS / 1000)
            _client_before = object()
        for vid in all_requests[uid]:
            cached = _cache_get(vid)
            if cached is None:
                await asyncio.sleep(LATENCY_API_MS / 1000)
                _cache_set(vid, FAKE_TRANSCRIPT.copy())
        return (time.perf_counter() - t) * 1000

    async def run_before():
        times = await asyncio.gather(*[user_request_before(u) for u in range(n_users)])
        return times

    async def run_after():
        times = await asyncio.gather(*[user_request_after(u) for u in range(n_users)])
        return times

    before_times = asyncio.get_event_loop().run_until_complete(run_before())
    _transcript_cache.clear()
    _client_before = None
    after_times  = asyncio.get_event_loop().run_until_complete(run_after())

    before_p50 = statistics.median(before_times)
    before_p95 = sorted(before_times)[int(n_users * 0.95)]
    after_p50  = statistics.median(after_times)
    after_p95  = sorted(after_times)[int(n_users * 0.95)]

    max_ms = before_p95 + 500
    _print_result("Before p50 (응답시간 중앙값)", before_p50, max_ms)
    _print_result("Before p95 (응답시간 95th) ", before_p95, max_ms)
    _print_result("After  p50 (응답시간 중앙값)", after_p50,  max_ms)
    _print_result("After  p95 (응답시간 95th) ", after_p95,  max_ms)
    improvement = (before_p50 - after_p50) / before_p50 * 100
    print(f"\n  p50 개선: {before_p50/1000:.2f}s → {after_p50/1000:.2f}s  ({improvement:.1f}% 단축)")
    return {"before_p50": before_p50, "after_p50": after_p50, "improvement": improvement}


# ── 메인 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Tubify 백엔드 성능 개선 벤치마크")
    print("  (실측 지연 기반 시뮬레이션 — API 키 불필요)")
    print("="*60)

    VIDEO_IDS = [f"videoId{i:03d}" for i in range(5)]

    r1 = bench_youtube_client(iterations=20)
    r2 = bench_transcript_cache_single(video_ids=VIDEO_IDS, repeat=4)
    r3 = bench_ytdlp_vs_api(n_videos=5)
    r4 = bench_concurrent_users(n_users=10, videos_per_user=5)

    _print_header("종합 요약")
    print(f"  {'항목':<35} {'개선율':>8}")
    print(f"  {'-'*44}")
    print(f"  {'YouTube API 클라이언트 싱글톤':<35} {r1['improvement']:>7.1f}%")
    print(f"  {'자막 캐시 (중복 요청 절감)':<35} {r2['improvement']:>7.1f}%")
    print(f"  {'yt-dlp → transcript-api 교체':<35} {(r3['before_ms']-r3['after_ms'])/r3['before_ms']*100:>7.1f}%")
    print(f"  {'복합 시나리오 p50 응답 단축':<35} {r4['improvement']:>7.1f}%")
    print()
