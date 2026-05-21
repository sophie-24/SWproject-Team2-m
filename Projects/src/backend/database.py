# SQLAlchemy ORM 모델 정의 및 비동기 DB 연결
# refactor/db-interest-schema: user_interests를 하트 토픽 저장 중심으로 단순화
import os
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, String, DateTime, Text, Boolean, Integer, UniqueConstraint, Index, Enum as SAEnum
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
    # 발송 시간 — JSON 배열 문자열 (Issue 7에서 단일 시간으로 정리 예정)
    send_time            = Column(Text, nullable=False, default='["21:00"]', server_default='["21:00"]')
    # 수신 동의 여부 — False이면 배치에서 완전히 제외
    is_subscribed        = Column(Boolean, nullable=False, default=True)
    unsubscribed_at      = Column(DateTime, nullable=True)
    # DEPRECATED: scheduler selector_ai 가산점용 구독 채널 캐시 — 행동기록 기반 파이프라인 제거로 불필요
    subscribed_channels  = Column(Text, nullable=True)
    # selector_ai ω₄ click_score용 — /analyze_video 호출 시 시청 채널 ID 누적 저장 (최대 50개)
    watched_channels     = Column(Text, nullable=True)
    # Google OAuth credentials JSON — 서버 재시작 후에도 /subscriptions 호출 가능하도록 DB에 저장
    oauth_credentials    = Column(Text, nullable=True)
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


# DEPRECATED: 행동기록 기반 파이프라인 제거(Issue 8)로 더 이상 사용하지 않음
# /collect, /collect/today API도 deprecated 처리됨
class BehaviorLog(Base):
    __tablename__ = "behavior_logs"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(String(255), nullable=False)   # google_id 기준
    event_type   = Column(SAEnum('search', 'watch', name='event_type', create_type=False), nullable=False)
    keyword      = Column(String(500), nullable=False)
    video_id     = Column(String(50), nullable=True)
    logged_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    status       = Column(SAEnum('pending', 'processed', 'archived', name='log_status', create_type=False), nullable=False, default="pending")
    processed_at = Column(DateTime, nullable=True)
    batch_id     = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("idx_behavior_logs_status",   "user_id", "status", "logged_at"),
        Index("idx_behavior_logs_batch_id", "batch_id"),
    )


class Newsletter(Base):
    __tablename__ = "newsletters"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id          = Column(String(255), nullable=False)
    subject          = Column(String(500), nullable=True)
    content_json     = Column(Text, nullable=False)
    delivered_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    delivery_status  = Column(SAEnum('generated', 'sent', 'failed', name='delivery_status', create_type=False), nullable=False, default="generated")
    error_message    = Column(Text, nullable=True)
    batch_id         = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("idx_newsletters_history",  "user_id", "delivered_at"),
        Index("idx_newsletters_delivery", "user_id", "delivery_status"),
    )


# DEPRECATED: 행동기록 기반 파이프라인 제거(Issue 8)로 더 이상 사용하지 않음
class ReportBatch(Base):
    __tablename__ = "report_batches"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(String(255), nullable=False)
    started_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    finished_at  = Column(DateTime, nullable=True)
    status       = Column(SAEnum('created', 'processing', 'completed', 'failed', name='batch_status', create_type=False), nullable=False, default="created")
    topic_count  = Column(Integer, nullable=True)
    window_type  = Column(SAEnum('before_cutoff', 'after_cutoff', name='window_type', create_type=False), nullable=True)
    period_start = Column(DateTime, nullable=True)
    period_end   = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_report_batches_user", "user_id", "started_at"),
    )


class UserInterest(Base):
    """사용자가 하트한 관심 토픽 저장 테이블.
    - 하트 1회 = 1개 토픽 (normalized_topic 기준 중복 제거)
    - 최대 5개 제한은 API 레이어(Issue 3)에서 처리
    - user_interest_videos 테이블과 1:N 관계 (Issue 4)
    """
    __tablename__ = "user_interests"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id           = Column(String(255), nullable=False)   # google_id 기준
    # 사용자에게 보여줄 대표 토픽명 (title_topic_ai 출력)
    category          = Column(String(100), nullable=False)
    # 중복 판단 및 5개 제한 카운트 기준 (소문자·공백 정규화)
    normalized_topic  = Column(String(100), nullable=True)
    # source: 하트 기반 관심사는 'manual', 온보딩 초기화는 'onboarding'
    source            = Column(SAEnum('behavior', 'onboarding', 'manual', name='interest_source', create_type=False), nullable=False, default="manual")
    # weight: 하위 호환 유지 (행동기록 기반 누적 로직은 Issue 8에서 제거)
    weight            = Column(Integer, nullable=False, default=1)
    # soft delete — False이면 관심사 취소 상태 (DELETE /interests/{topic} 시 활용)
    is_active         = Column(Boolean, nullable=False, default=True)
    last_seen_at      = Column(DateTime, nullable=True)
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                               onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        # 신규 기준: (user_id, normalized_topic) — 같은 토픽 중복 저장 방지
        UniqueConstraint("user_id", "normalized_topic", name="uq_user_interest_normalized"),
        # 하위 호환: 기존 온보딩/profile_init 코드에서 category 기준 삽입 시 사용
        UniqueConstraint("user_id", "category", name="uq_user_interest_category"),
        Index("idx_user_interests_user", "user_id", "weight"),
        Index("idx_user_interests_active", "user_id", "is_active"),
    )


class UserInterestVideo(Base):
    """관심 토픽에 연결된 하트 영상 테이블.
    - 하나의 관심 토픽(UserInterest)에 여러 영상 연결 가능 (1:N)
    - 동일 관심 토픽 안에서 같은 video_id 중복 저장 방지
    - 관심 토픽 삭제(UserInterest 삭제) 시 연결 영상도 CASCADE 삭제
    """
    __tablename__ = "user_interest_videos"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # user_interests.id 참조 — ON DELETE CASCADE
    user_interest_id = Column(UUID(as_uuid=True), nullable=False)
    video_id         = Column(String(50), nullable=False)   # YouTube video_id
    title            = Column(Text, nullable=True)           # 영상 제목 (참고용)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        # 동일 관심 토픽 안에서 같은 video_id 중복 저장 방지
        UniqueConstraint("user_interest_id", "video_id", name="uq_interest_video"),
        Index("idx_interest_videos_interest", "user_interest_id"),
    )


# ── DB 초기화 (테이블 생성) ────────────────────────────────────────────────────

async def init_db():
    """서버 시작 시 호출 — 테이블 없으면 자동 생성"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── 세션 의존성 (FastAPI Depends용) ───────────────────────────────────────────

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
