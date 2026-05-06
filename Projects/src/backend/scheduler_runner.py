# Pipeline B 배치 워커 독립 실행 진입점 — Railway batch-worker 서비스용
# 사용법: python scheduler_runner.py
# api-server(uvicorn main:app)와 분리해 배포할 때 이 파일로 배치 워커를 실행합니다.
import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ── 필수 환경변수 Fail-fast ────────────────────────────────────────────────────
_REQUIRED_ENV = [
    "DATABASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "JWT_SECRET",
    "RESEND_API_KEY",
    "YOUTUBE_API_KEY",
]

missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
if missing:
    print(f"[scheduler_runner] 필수 환경변수 누락: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)

# ── DB 초기화 + 스케줄러 실행 ─────────────────────────────────────────────────
from database import init_db
from scheduler import scheduler, start_scheduler
from logger import get_logger

logger = get_logger(__name__)


async def main():
    logger.info("[scheduler_runner] DB 초기화 중...")
    await init_db()

    logger.info("[scheduler_runner] 배치 워커 시작")
    start_scheduler()

    # 스케줄러가 실행 중인 동안 프로세스 유지
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("[scheduler_runner] 종료 신호 수신 — 스케줄러 종료 중...")
        scheduler.shutdown(wait=True)
        logger.info("[scheduler_runner] 종료 완료")


if __name__ == "__main__":
    asyncio.run(main())
