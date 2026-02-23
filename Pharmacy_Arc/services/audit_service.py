"""Audit service — encapsulates DB operations for audit entries."""
import logging
import extensions
from helpers.auth_utils import is_admin_role
from helpers.db import db_retry, is_unique_violation
from helpers.exceptions import AuditNotFoundError, DuplicateEntryError, StoreMismatchError

logger = logging.getLogger(__name__)


def get_audit(audit_id: int) -> dict:
    """Fetch a single non-deleted audit entry by ID.

    Raises AuditNotFoundError if the entry does not exist or is soft-deleted.
    """
    db = extensions.get_db()
    result = db.table("audits").select("*").eq("id", audit_id).is_("deleted_at", "null").execute()
    if not result.data:
        raise AuditNotFoundError(audit_id)
    return result.data[0]


def check_store_access(audit_data: dict, user_role: str, user_store: str) -> None:
    """Verify the user is allowed to access an audit's store.

    Raises StoreMismatchError if a non-admin user tries to access another store.
    """
    if is_admin_role(user_role):
        return
    entry_store = audit_data.get('store')
    if entry_store != user_store:
        raise StoreMismatchError(user_store=user_store, target_store=entry_store)


def check_duplicate(date: str, store: str, reg: str) -> None:
    """Check for duplicate audit entry. Raises DuplicateEntryError if found."""
    db = extensions.get_db()
    dup = db.table("audits").select("id") \
        .eq("date", date) \
        .eq("store", store) \
        .eq("reg", reg) \
        .is_("deleted_at", "null") \
        .execute()
    if dup.data:
        raise DuplicateEntryError(date=date, store=store, reg=reg)


def insert_audit(record: dict) -> dict:
    """Insert an audit record. Returns the inserted row.

    Raises DuplicateEntryError on unique constraint violation.
    """
    try:
        result = db_retry(
            lambda: extensions.get_db().table("audits").insert(record).execute(),
            label="insert_audit",
        )
        return result.data[0] if result.data else {}
    except Exception as e:
        if is_unique_violation(e):
            raise DuplicateEntryError(
                date=record.get('date', ''),
                store=record.get('store', ''),
                reg=record.get('reg', ''),
            ) from e
        raise


def update_audit(audit_id: int, record: dict) -> None:
    """Update an audit entry by ID."""
    db_retry(
        lambda: extensions.get_db().table("audits").update(record).eq("id", audit_id).execute(),
        label="update_audit",
    )


def soft_delete_audit(audit_id: int) -> None:
    """Soft-delete an audit entry by setting deleted_at."""
    from datetime import datetime, timezone
    db_retry(
        lambda: extensions.get_db().table("audits").update(
            {"deleted_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", audit_id).execute(),
        label="soft_delete_audit",
    )
