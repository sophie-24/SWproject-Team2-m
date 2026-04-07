# backend/database.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid
import datetime
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# 엔진 생성
engine = create_async_engine(DATABASE_URL, echo=False)

# 세션 팩토리
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass

# ── 테이블 모델 ────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_id     = Column(String(255), unique=True, nullable=False)
    email         = Column(String(255), unique=True, nullable=False)
    kakao_uuid    = Column(String(255), nullable=True)
    delivery_type = Column(String(10), nullable=False, default="email")  # 'kakao' | 'email'
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)


class BehaviorLog(Base):
    __tablename__ = "behavior_logs"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(String(255), nullable=False)   # google_id 기준
    event_type = Column(String(10), nullable=False)    # 'search' | 'watch'
    keyword    = Column(String(500), nullable=False)
    video_id   = Column(String(50), nullable=True)
    logged_at  = Column(DateTime, default=datetime.datetime.utcnow)


class Newsletter(Base):
    __tablename__ = "newsletters"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(String(255), nullable=False)
    subject       = Column(String(500), nullable=True)
    content_json  = Column(Text, nullable=False)       # newsletter_ai 출력값 JSON 문자열
    delivered_at  = Column(DateTime, default=datetime.datetime.utcnow)
    delivery_type = Column(String(10), nullable=True)  # 'kakao' | 'email'


# ── DB 초기화 (테이블 생성) ────────────────────────────────────────────────────

async def init_db():
    """서버 시작 시 호출 — 테이블 없으면 자동 생성"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── 세션 의존성 (FastAPI Depends용) ───────────────────────────────────────────

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()