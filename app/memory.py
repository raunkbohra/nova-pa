"""
PostgreSQL database models and CRUD operations.
Uses SQLAlchemy 2.0 async with asyncpg driver.
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Index,
    create_engine, event, text, func
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.sql import select
from datetime import datetime, timezone
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()


# ============================================================================
# SQLAlchemy Models
# ============================================================================

class Message(Base):
    """Raunak's conversation history (rolling 50 messages)"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExternalThread(Base):
    """Isolated conversation thread per external contact"""
    __tablename__ = "external_threads"

    id = Column(Integer, primary_key=True)
    phone = Column(String(20), nullable=False, index=True)  # E.164 format
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Contact(Base):
    """External contact profiles"""
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255))
    company = Column(String(255))
    purpose = Column(String(255))
    is_vip = Column(Boolean, default=False, index=True)
    is_blocked = Column(Boolean, default=False, index=True)
    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))


class Note(Base):
    """Raunak's second brain with full-text search"""
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(String(500))  # comma-separated
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class NovaContext(Base):
    """NOVA's knowledge about Raunak (editable via chat)"""
    __tablename__ = "nova_context"

    id = Column(Integer, primary_key=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class Usage(Base):
    """Claude API token usage per request"""
    __tablename__ = "usage"

    id = Column(Integer, primary_key=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RateLimit(Base):
    """Rate limiting for external contacts"""
    __tablename__ = "rate_limits"

    id = Column(Integer, primary_key=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    message_count = Column(Integer, default=0)
    window_start = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    blocked_until = Column(DateTime(timezone=True), nullable=True)


# ============================================================================
# Database Engine & Session Management
# ============================================================================

async_engine = None
AsyncSessionLocal = None


async def init_db(database_url: str):
    """Initialize async database engine and session factory"""
    global async_engine, AsyncSessionLocal

    async_engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )

    AsyncSessionLocal = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create all tables
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialized successfully")


async def get_session() -> AsyncSession:
    """Get async database session for dependency injection"""
    async with AsyncSessionLocal() as session:
        yield session


async def close_db():
    """Close database engine"""
    global async_engine
    if async_engine:
        await async_engine.dispose()


# ============================================================================
# CRUD Helpers
# ============================================================================

async def save_message(session: AsyncSession, role: str, content: str):
    """Save message to Raunak's conversation"""
    msg = Message(role=role, content=content)
    session.add(msg)
    await session.commit()


async def get_messages(session: AsyncSession, limit: int = 50) -> List[Message]:
    """Get recent messages (rolling history)"""
    stmt = select(Message).order_by(Message.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(reversed(result.scalars().all()))


async def save_external_message(session: AsyncSession, phone: str, role: str, content: str):
    """Save message to external contact's thread"""
    msg = ExternalThread(phone=phone, role=role, content=content)
    session.add(msg)
    await session.commit()


async def get_external_thread(session: AsyncSession, phone: str) -> List[ExternalThread]:
    """Get conversation history for external contact"""
    stmt = select(ExternalThread).where(ExternalThread.phone == phone).order_by(ExternalThread.created_at)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_or_create_contact(session: AsyncSession, phone: str, name: Optional[str] = None,
                               company: Optional[str] = None) -> Contact:
    """Get existing contact or create new one"""
    stmt = select(Contact).where(Contact.phone == phone)
    result = await session.execute(stmt)
    contact = result.scalar_one_or_none()

    if contact:
        contact.last_seen = datetime.now(timezone.utc)
    else:
        contact = Contact(phone=phone, name=name, company=company)
        session.add(contact)

    await session.commit()
    return contact


async def add_vip(session: AsyncSession, phone: str):
    """Mark contact as VIP"""
    contact = await get_or_create_contact(session, phone)
    contact.is_vip = True
    await session.commit()


async def block_contact(session: AsyncSession, phone: str):
    """Block contact"""
    contact = await get_or_create_contact(session, phone)
    contact.is_blocked = True
    await session.commit()


async def save_note(session: AsyncSession, title: str, content: str, tags: Optional[str] = None):
    """Save note to second brain"""
    note = Note(title=title, content=content, tags=tags)
    session.add(note)
    await session.commit()
    return note


async def search_notes(session: AsyncSession, query: str) -> List[Note]:
    """Full-text search on notes (PostgreSQL tsvector)"""
    # For now, use simple LIKE search. PostgreSQL FTS requires separate setup.
    stmt = select(Note).where(
        (Note.title.ilike(f"%{query}%")) | (Note.content.ilike(f"%{query}%"))
    ).order_by(Note.updated_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_context(session: AsyncSession, key: str) -> Optional[str]:
    """Get NOVA context value (Raunak's info)"""
    stmt = select(NovaContext).where(NovaContext.key == key)
    result = await session.execute(stmt)
    ctx = result.scalar_one_or_none()
    return ctx.value if ctx else None


async def set_context(session: AsyncSession, key: str, value: str):
    """Set NOVA context value"""
    stmt = select(NovaContext).where(NovaContext.key == key)
    result = await session.execute(stmt)
    ctx = result.scalar_one_or_none()

    if ctx:
        ctx.value = value
    else:
        ctx = NovaContext(key=key, value=value)
        session.add(ctx)

    await session.commit()


async def save_usage(session: AsyncSession, input_tokens: int, output_tokens: int):
    """Save Claude API token usage for a request"""
    session.add(Usage(input_tokens=input_tokens, output_tokens=output_tokens))
    await session.commit()


async def get_usage_stats(session: AsyncSession, days: int = 30):
    """Get aggregated token usage for the last N days"""
    from sqlalchemy import func
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    since = since.replace(day=since.day - days + 1) if days > 1 else since

    stmt = select(
        func.sum(Usage.input_tokens).label("total_input"),
        func.sum(Usage.output_tokens).label("total_output"),
        func.count(Usage.id).label("total_requests"),
    ).where(Usage.created_at >= since)

    result = await session.execute(stmt)
    row = result.one()
    return {
        "total_input": row.total_input or 0,
        "total_output": row.total_output or 0,
        "total_requests": row.total_requests or 0,
        "days": days,
    }


async def get_recent_contacts(session: AsyncSession, limit: int = 10) -> List[Contact]:
    """Get recent contacts ordered by last activity (last_seen or first_seen)"""
    from sqlalchemy import func, case
    stmt = (
        select(Contact)
        .order_by(
            func.coalesce(Contact.last_seen, Contact.first_seen).desc()
        )
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def search_contact_by_name(session: AsyncSession, name: str) -> Optional[Contact]:
    """Find contact by partial name match (case-insensitive)"""
    stmt = select(Contact).where(Contact.name.ilike(f"%{name}%")).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def check_rate_limit(session: AsyncSession, phone: str, max_messages: int = 10,
                          window_seconds: int = 3600) -> bool:
    """Check if contact exceeded rate limit"""
    stmt = select(RateLimit).where(RateLimit.phone == phone)
    result = await session.execute(stmt)
    rate_limit = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if not rate_limit:
        rate_limit = RateLimit(phone=phone, message_count=1, window_start=now)
        session.add(rate_limit)
    else:
        # Check if window expired
        elapsed = (now - rate_limit.window_start).total_seconds()
        if elapsed > window_seconds:
            # Reset window
            rate_limit.message_count = 1
            rate_limit.window_start = now
        else:
            rate_limit.message_count += 1

    await session.commit()

    # Return True if over limit
    return rate_limit.message_count > max_messages
