"""
Tubify 공통 로거 설정

사용법:
    from logger import get_logger
    logger = get_logger(__name__)

    logger.debug("개발용 상세 정보")
    logger.info("정상 흐름 기록")
    logger.warning("주의 필요하지만 치명적이진 않음")
    logger.error("실제 오류 발생")
"""

import logging
import sys
import os
from logging.handlers import RotatingFileHandler

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "false").lower() == "true"
LOG_FILE = os.getenv("LOG_FILE", "tubify.log")


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _configure_root() -> None:
    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    fmt = _build_formatter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    if LOG_TO_FILE:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # 외부 라이브러리 노이즈 억제
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


_configure_root()


def get_logger(name: str) -> logging.Logger:
    """모듈별 logger 반환. 각 파일 상단에서 호출."""
    return logging.getLogger(name)
