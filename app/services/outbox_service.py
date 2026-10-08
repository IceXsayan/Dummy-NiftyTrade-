import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import event

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.outbox import OutboxEvent
from app.models.trading import Holding
from app.models.user import User
from app.shared_identity import normalize_email

logger = logging.getLogger(__name__)

def enqueue_outbox_event(
    db: Session,
    email: str,
    event_type: str = "HOLDINGS_CHANGED",
    dispatch_async: bool = True
) -> OutboxEvent:
    """
    Enqueue an outbox event for TradeOne.
    Send only: provider, email, event=HOLDINGS_CHANGED, occurredAt.
    Never send holdings quantities in the event.
    """
    norm_email = normalize_email(email)
    occurred_at = datetime.now(timezone.utc).isoformat()

    outbox_event = OutboxEvent(
        provider=getattr(settings, "PROVIDER_CODE", "a"),
        email=norm_email,
        event=event_type,
        occurred_at=occurred_at,
        status="PENDING",
        attempts=0,
        max_attempts=10
    )
    db.add(outbox_event)
    db.commit()
    db.refresh(outbox_event)

    if dispatch_async:
        # Asynchronous background thread to ensure trades/requests are NEVER blocked
        t = threading.Thread(
            target=post_event_with_retry,
            args=(outbox_event.id,),
            daemon=True
        )
        t.start()

    return outbox_event

def post_event_with_retry(
    event_id: int,
    max_attempts: int = 10,
    backoff_base: float = 0.5,
    http_client: Optional[httpx.Client] = None,
    db: Optional[Session] = None
) -> bool:
    """
    Deliver an outbox event with exponential backoff up to max_attempts (default 10).
    Never blocks trading threads.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        outbox_event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        if not outbox_event:
            return False


        tradeone_url = getattr(settings, "TRADEONE_URL", "http://localhost:8080").rstrip("/")
        endpoint = f"{tradeone_url}/internal/v1/events"
        api_key = getattr(settings, "INTERNAL_API_KEY", "")

        # Payload sends ONLY: provider, email, event, occurredAt
        payload = {
            "provider": outbox_event.provider,
            "email": outbox_event.email,
            "event": outbox_event.event,
            "occurredAt": outbox_event.occurred_at
        }

        headers = {
            "Content-Type": "application/json",
            "x-internal-key": api_key
        }

        created_client = False
        client = http_client
        if client is None:
            client = httpx.Client(timeout=5.0)
            created_client = True

        try:
            for attempt in range(1, max_attempts + 1):
                outbox_event.attempts = attempt
                try:
                    resp = client.post(endpoint, json=payload, headers=headers)
                    if 200 <= resp.status_code < 300:
                        outbox_event.status = "SENT"
                        outbox_event.last_error = None
                        db.commit()
                        return True
                    else:
                        err_msg = f"HTTP {resp.status_code}: {resp.text}"
                        outbox_event.last_error = err_msg
                except Exception as exc:
                    outbox_event.last_error = str(exc)

                if attempt >= max_attempts:
                    outbox_event.status = "FAILED"
                    db.commit()
                    return False

                db.commit()
                # Exponential backoff: backoff_base * (2 ** (attempt - 1))
                sleep_secs = backoff_base * (2 ** (attempt - 1))
                time.sleep(sleep_secs)

            return False
        finally:
            if created_client:
                client.close()

    except Exception as e:
        logger.error(f"Error processing outbox event {event_id}: {e}")
        return False
    finally:
        if close_db:
            db.close()


def dispatch_holdings_changed_for_user_ids(user_ids: List[int]):
    """Background helper to lookup user emails and enqueue outbox events."""
    def _run():
        db = SessionLocal()
        try:
            users = db.query(User).filter(User.id.in_(user_ids)).all()
            for u in users:
                if u and u.email:
                    enqueue_outbox_event(db, u.email, event_type="HOLDINGS_CHANGED", dispatch_async=True)
        except Exception as e:
            logger.error(f"Failed to dispatch holdings changed events: {e}")
        finally:
            db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

# --- SQLAlchemy Lifecycle Hooks for Committed Holdings Changes ---
@event.listens_for(Session, "after_flush")
def _track_holdings_after_flush(session, flush_context):
    """Detect if any Holding rows were added, modified, or deleted."""
    try:
        modified_users = session.info.setdefault("_modified_holding_user_ids", set())
        for obj in session.new | session.dirty | session.deleted:
            if isinstance(obj, Holding):
                if obj.user_id:
                    modified_users.add(obj.user_id)
    except Exception:
        pass

@event.listens_for(Session, "after_commit")
def _notify_holdings_after_commit(session):
    """Trigger outbox enqueueing only after the holdings change is committed."""
    try:
        user_ids = list(session.info.get("_modified_holding_user_ids", set()))
        if user_ids:
            session.info["_modified_holding_user_ids"].clear()
            dispatch_holdings_changed_for_user_ids(user_ids)
    except Exception:
        pass

@event.listens_for(Session, "after_rollback")
def _cleanup_holdings_after_rollback(session):
    """Clear pending tracked user IDs on rollback."""
    try:
        if "_modified_holding_user_ids" in session.info:
            session.info["_modified_holding_user_ids"].clear()
    except Exception:
        pass
