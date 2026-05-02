# SQLAlchemy ORM 모델 정의 및 비동기 DB 연결 (User, BehaviorLog, Newsletter, ReportBatch, UserInterest, UserSubscription)
import os
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, String, DateTime, Text, Boolean, Integer, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
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

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_id            = Column(String(255), unique=True, nullable=False)
    email                = Column(String(255), unique=True, nullable=False)
    delivery_type        = Column(String(10), nullable=False, default="email")
    # 온보딩 프로파일링
    initial_intent       = Column(String(20), nullable=True)   # '유희형'|'지식형'|'구매형'
    interest_categories  = Column(Text, nullable=True)         # JSON 문자열 — 관심사 카테고리 목록
    # 사용자 설정 발송 시간
    morning_send_time    = Column(String(5), nullable=False, default="08:00", server_default="08:00")  # "HH:MM" KST 오전 발송
    send_time            = Column(String(5), nullable=False, default="21:00", server_default="21:00")  # "HH:MM" KST 오후 발송
    # 수신 동의 여부 — False이면 배치에서 완전히 제외
    is_subscribed        = Column(Boolean, nullable=False, default=True)
    unsubscribed_at      = Column(DateTime, nullable=True)
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BehaviorLog(Base):
    __tablename__ = "behavior_logs"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(String(255), nullable=False)   # google_id 기준
    event_type = Column(String(10), nullable=False)    # 'search' | 'watch'
    keyword    = Column(String(500), nullable=False)
    video_id   = Column(String(50), nullable=True)
    logged_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # 배치 처리 상태 추적
    status     = Column(String(20), nullable=False, default="pending")  # 'pending'|'processed'|'archived'
    batch_id   = Column(UUID(as_uuid=True), nullable=True)              # 처리한 ReportBatch.id

    __table_args__ = (
        # 스케줄러: user_id + status='pending' 필터링 → logged_at 정렬
        Index("idx_behavior_logs_status",   "user_id", "status", "logged_at"),
        # batch_id 역추적 (ReportBatch 단위 로그 조회)
        Index("idx_behavior_logs_batch_id", "batch_id"),
    )


class Newsletter(Base):
    __tablename__ = "newsletters"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id          = Column(String(255), nullable=False)
    subject          = Column(String(500), nullable=True)
    content_json     = Column(Text, nullable=False)       # newsletter_ai 출력값 JSON 문자열
    delivered_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    delivery_type    = Column(String(10), nullable=True)  # 'email'
    # 발송 결과 추적
    delivery_status  = Column(String(20), nullable=False, default="pending")  # 'pending'|'sent'|'failed'
    error_message    = Column(Text, nullable=True)        # 실패 시 오류 메시지
    batch_id         = Column(UUID(as_uuid=True), nullable=True)  # 생성한 ReportBatch.id

    __table_args__ = (
        # 대시보드 히스토리 목록: user_id 필터 + delivered_at 정렬
        Index("idx_newsletters_history",  "user_id", "delivered_at"),
        # 발송 실패 추적: delivery_status='failed' 필터링
        Index("idx_newsletters_delivery", "user_id", "delivery_status"),
    )


class ReportBatch(Base):
    """Pipeline B 1회 실행 단위. behavior_logs.batch_id → report_batches.id 로 역추적 가능."""
    __tablename__ = "report_batches"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(String(255), nullable=False)   # google_id 기준
    started_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)
    status      = Column(String(20), nullable=False, default="running")  # 'running'|'done'|'failed'
    log_count   = Column(Integer, nullable=True)    # 처리에 사용된 behavior_logs 수
    topic_count = Column(Integer, nullable=True)    # cluster_ai가 뽑은 토픽 수

    __table_args__ = (
        # 유저별 배치 실행 이력 조회: user_id 필터 + started_at 정렬
        Index("idx_report_batches_user", "user_id", "started_at"),
    )


class UserInterest(Base):
    """유저 카테고리별 관심도 누적 테이블.
    온보딩 시 weight=1 초기화, Pipeline B 실행마다 해당 토픽 weight++.
    Gemini 추가 호출 없이 cluster_ai 결과(merged_topics)를 그대로 재활용.
    """
    __tablename__ = "user_interests"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(String(255), nullable=False)   # google_id 기준
    category   = Column(String(100), nullable=False)   # cluster_ai 토픽명 (ex: "아이폰 16")
    weight     = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_user_interest_category"),
        # 관심도 상위 카테고리 조회: user_id 필터 + weight 정렬
        Index("idx_user_interests_user", "user_id", "weight"),
    )


class UserSubscription(Base):
    """유저 YouTube 구독 채널 테이블.
    로그인 시 자동 동기화 + /subscriptions/sync로 수동 갱신.
    scheduler가 selector_ai에 subscribed_channel_ids 전달 시 여기서 조회.
    """
    __tablename__ = "user_subscriptions"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(String(255), nullable=False)    # google_id 기준
    channel_id    = Column(String(100), nullable=False)    # YouTube channel ID
    channel_title = Column(String(255), nullable=True)     # 채널명 (표시용)
    synced_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uq_user_subscription"),
        Index("idx_user_subscriptions_user", "user_id"),
    )


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
