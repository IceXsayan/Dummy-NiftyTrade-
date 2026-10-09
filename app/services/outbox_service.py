import time
import asyncio
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

def enqueue_outbox_event_in_tx(
    db: Session,
    email: str,
    event_type: str = "HOLDINGS_CHANGED"
) -> OutboxEvent:
    """
    Inserts an outbox event into the given session/transaction WITHOUT committing.
    The caller's transaction commit will commit the outbox event and the trade together.
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

    # Track in session info so after_commit hook knows which events were created
    pending_events = db.info.setdefault("_pending_outbox_objs", [])
    pending_events.append(outbox_event)
    db.info.setdefault("_outbox_emails_pending", set()).add(norm_email)

    return outbox_event

def enqueue_outbox_event(
    db: Session,
    email: str,
    event_type: str = "HOLDINGS_CHANGED",
    dispatch_async: bool = True
) -> OutboxEvent:
    """
    Enqueue an outbox event and commit immediately.
    """
    outbox_event = enqueue_outbox_event_in_tx(db, email, event_type=event_type)
    db.commit()
    db.refresh(outbox_event)

    if dispatch_async:
        trigger_single_event_delivery(outbox_event.id)

    return outbox_event

def trigger_single_event_delivery(event_id: int):
    """Deliver an event in a background daemon thread."""
    t = threading.Thread(
        target=post_event_with_retry,
        args=(event_id,),
        daemon=True
    )
    t.start()

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
    Logs each delivery result.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        outbox_event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        if not outbox_event or outbox_event.status == "SENT":
            return True

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
            current_attempts = outbox_event.attempts
            for attempt in range(current_attempts + 1, max_attempts + 1):
                outbox_event.attempts = attempt
                try:
                    resp = client.post(endpoint, json=payload, headers=headers)
                    if 200 <= resp.status_code < 300:
                        outbox_event.status = "SENT"
                        outbox_event.last_error = None
                        db.commit()
                        logger.info(f"Outbox event {event_id} ({outbox_event.email}) delivered successfully to {endpoint} on attempt {attempt}")
                        return True
                    else:
                        err_msg = f"HTTP {resp.status_code}: {resp.text}"
                        outbox_event.last_error = err_msg
                        logger.warning(f"Outbox event {event_id} attempt {attempt} failed: {err_msg}")
                except Exception as exc:
                    err_msg = str(exc)
                    outbox_event.last_error = err_msg
                    logger.warning(f"Outbox event {event_id} attempt {attempt} error: {err_msg}")

                if attempt >= max_attempts:
                    outbox_event.status = "FAILED"
                    db.commit()
                    logger.error(f"Outbox event {event_id} permanently failed after {max_attempts} attempts: {outbox_event.last_error}")
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

def process_pending_outbox_events(db: Optional[Session] = None):
    """Process all pending outbox events in the database."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        pending = db.query(OutboxEvent).filter(
            OutboxEvent.status == "PENDING",
            OutboxEvent.attempts < OutboxEvent.max_attempts
        ).all()
        for ev in pending:
            trigger_single_event_delivery(ev.id)
    except Exception as e:
        logger.error(f"Error checking pending outbox events: {e}")
    finally:
        if close_db:
            db.close()

def trigger_outbox_worker():
    """Trigger background sweep of pending events."""
    t = threading.Thread(target=process_pending_outbox_events, daemon=True)
    t.start()

async def run_outbox_worker_loop():
    """Periodic background worker for pending/retryable outbox events."""
    while True:
        try:
            process_pending_outbox_events()
        except Exception as e:
            logger.error(f"Error in background outbox worker loop: {e}")
        await asyncio.sleep(5)

# --- SQLAlchemy Lifecycle Hooks for Committed Holdings Changes ---
@event.listens_for(Session, "before_flush")
def _handle_holdings_before_flush(session, flush_context, instances):
    """
    Automatically creates OutboxEvent in the same transaction whenever
    Holding rows are added, modified, or deleted.
    """
    try:
        pending_emails = session.info.setdefault("_outbox_emails_pending", set())
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            if isinstance(obj, Holding) and obj.user_id:
                # Find user email
                user = obj.user or session.query(User).filter(User.id == obj.user_id).first()
                if user and user.email:
                    norm = normalize_email(user.email)
                    if norm not in pending_emails:
                        enqueue_outbox_event_in_tx(session, norm, "HOLDINGS_CHANGED")
    except Exception as e:
        logger.error(f"Error in before_flush outbox hook: {e}")

@event.listens_for(Session, "after_commit")
def _notify_holdings_after_commit(session):
    """
    After the transaction commits, dispatch background delivery for any newly created events.
    """
    try:
        pending_objs = session.info.get("_pending_outbox_objs", [])
        event_ids = [ev.id for ev in pending_objs if hasattr(ev, "id") and ev.id]
        session.info["_pending_outbox_objs"] = []
        if "_outbox_emails_pending" in session.info:
            session.info["_outbox_emails_pending"].clear()

        for eid in event_ids:
            trigger_single_event_delivery(eid)
    except Exception as e:
        logger.error(f"Error in after_commit outbox hook: {e}")

@event.listens_for(Session, "after_rollback")
def _cleanup_holdings_after_rollback(session):
    """Clean up tracking state if transaction rolls back."""
    try:
        if "_pending_outbox_objs" in session.info:
            session.info["_pending_outbox_objs"] = []
        if "_outbox_emails_pending" in session.info:
            session.info["_outbox_emails_pending"].clear()
    except Exception:
        pass
