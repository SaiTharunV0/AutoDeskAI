"""PostgreSQL-backed chatbot abuse counters; message content is never stored."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import ChatRateLimitBucket
import config


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _window_start(at, seconds):
    epoch = int(at.replace(tzinfo=timezone.utc).timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, timezone.utc).replace(tzinfo=None)


def _counter(db, user_id, name, seconds, *, reset=False):
    at = _utcnow()
    start = _window_start(at, seconds)
    db.execute(delete(ChatRateLimitBucket).where(
        ChatRateLimitBucket.user_id == user_id,
        ChatRateLimitBucket.window_start < at - timedelta(hours=2)))
    values = {"user_id": user_id, "bucket_type": name, "window_start": start,
              "count": 0 if reset else 1, "updated_at": at}
    dialect = db.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    statement = insert(ChatRateLimitBucket).values(**values)
    count_value = 0 if reset else ChatRateLimitBucket.count + 1
    statement = statement.on_conflict_do_update(
        index_elements=[ChatRateLimitBucket.user_id, ChatRateLimitBucket.bucket_type,
                        ChatRateLimitBucket.window_start],
        set_={"count": count_value, "updated_at": at})
    db.execute(statement)
    return db.scalar(select(ChatRateLimitBucket.count).where(
        ChatRateLimitBucket.user_id == user_id,
        ChatRateLimitBucket.bucket_type == name,
        ChatRateLimitBucket.window_start == start)), max(1, seconds - int((at - start).total_seconds()))


def _rate_error(wait_seconds):
    return HTTPException(429, "Too many chat messages. Please wait before trying again.",
                         headers={"Retry-After": str(wait_seconds)})


def check_chat_rate(db, user_id, message):
    if len(message) > min(2000, config.CHAT_MAX_MESSAGE_LENGTH):
        raise HTTPException(422, f"Messages must be {min(2000, config.CHAT_MAX_MESSAGE_LENGTH)} characters or fewer.")
    minute, minute_wait = _counter(db, user_id, "messages_minute", 60)
    hour, hour_wait = _counter(db, user_id, "messages_hour", 3600)
    db.commit()
    if minute > config.CHAT_RATE_LIMIT_PER_MINUTE or hour > config.CHAT_RATE_LIMIT_PER_HOUR:
        wait = max(minute_wait if minute > config.CHAT_RATE_LIMIT_PER_MINUTE else 0,
                   hour_wait if hour > config.CHAT_RATE_LIMIT_PER_HOUR else 0)
        raise _rate_error(wait)


def record_out_of_scope(db, user_id):
    count, wait = _counter(db, user_id, "out_of_scope_minute", 60)
    db.commit()
    if count > config.CHAT_OUT_OF_SCOPE_LIMIT_PER_MINUTE:
        raise _rate_error(wait)


def reset_out_of_scope(db, user_id):
    _counter(db, user_id, "out_of_scope_minute", 60, reset=True)
    db.commit()
