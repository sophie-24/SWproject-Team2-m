# SQLAlchemy ORM 모델 정의 및 비동기 DB 연결 (User, BehaviorLog, Newsletter, ReportBatch, UserInterest, UserSubscription)
# 2차 DB 설계 반영: behavior_logs.processed_at / user_interests.(source,last_seen_at,created_at) / report_batches.(window_type,period_start,period_end)
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
    # 사용자 설정 발송 시간 — JSON 배열 문자열로 1개 이상 저장 (예: '["08:00","21:00"]')
    send_time            = Column(Text, nullable=False, default='["21:00"]', server_default='["21:00"]')
    # 수신 동의 여부 — False이면 배치에서 완전히 제외
    is_subscribed        = Column(Boolean, nullable=False, default=True)
    unsubscribed_at      = Column(DateTime, nullable=True)
    # 유튜브 구독 채널 ID 캐시 — JSON 배열 문자열 (예: '["UCxxx","UCyyy"]')
    # GET /subscriptions 호출 시 갱신, scheduler에서 selector_ai 가산점에 사용
    subscribed_channels  = Column(Text, nullable=True)
    # Google OAuth credentials JSON — 서버 재시작 후에도 /subscriptions 호출 가능하도록 DB에 저장
    oauth_credentials    = Column(Text, nullable=True)
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class BehaviorLog(Base):
    __tablename__ = "behavior_logs"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(String(255), nullable=False)   # google_id 기준
    event_type   = Column(SAEnum('search', 'watch', name='event_type', create_type=False), nullable=False)
    keyword      = Column(String(500), nullable=False)
    video_id     = Column(String(50), nullable=True)
    logged_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    # 배치 처리 상태 추적
    status       = Column(SAEnum('pending', 'processed', 'archived', name='log_status', create_type=False), nullable=False, default="pending")
    processed_at = Column(DateTime, nullable=True)                         # processed 상태로 바뀐 시점
    batch_id     = Column(UUID(as_uuid=True), nullable=True)              # 처리한 ReportBatch.id

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
    delivered_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    # 발송 결과 추적
    delivery_status  = Column(SAEnum('generated', 'sent', 'failed', name='delivery_status', create_type=False), nullable=False, default="generated")
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

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(String(255), nullable=False)   # google_id 기준
    started_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    finished_at  = Column(DateTime, nullable=True)
    status       = Column(SAEnum('created', 'processing', 'completed', 'failed', name='batch_status', create_type=False), nullable=False, default="created")
    topic_count  = Column(Integer, nullable=True)    # Pipeline B가 추출한 최종 토픽 수
    # 2차 설계: 배치가 커버한 기간 및 발송 시점 구분
    window_type  = Column(SAEnum('before_cutoff', 'after_cutoff', name='window_type', create_type=False), nullable=True)
    period_start = Column(DateTime, nullable=True)       # 이번 배치가 커버한 로그 시작 시점
    period_end   = Column(DateTime, nullable=True)       # 이번 배치가 커버한 로그 종료 시점 (= 배치 실행 시각)

    __table_args__ = (
        # 유저별 배치 실행 이력 조회: user_id 필터 + started_at 정렬
        Index("idx_report_batches_user", "user_id", "started_at"),
    )


class UserInterest(Base):
    """유저 카테고리별 관심도 누적 테이블.
    온보딩 시 weight=1 초기화, Pipeline B 실행마다 해당 토픽 weight++.
    Gemini 추가 호출 없이 cluster_ai 결과(merged_topics)를 그대로 재활용.
    2차 설계: source(출처 구분) / last_seen_at(최근성 판단) / created_at(최초 등장) 추가.
    """
    __tablename__ = "user_interests"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(String(255), nullable=False)   # google_id 기준
    category     = Column(String(100), nullable=False)   # cluster_ai 토픽명 (ex: "아이폰 16")
    weight       = Column(Integer, nullable=False, default=1)
    source       = Column(SAEnum('behavior', 'onboarding', 'manual', name='interest_source', create_type=False), nullable=False, default="behavior")
    last_seen_at = Column(DateTime, nullable=True)        # 해당 토픽이 마지막으로 관찰된 시점
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                          onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_user_interest_category"),
        # 관심도 상위 카테고리 조회: user_id 필터 + weight 정렬
        Index("idx_user_interests_user", "user_id", "weight"),
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
