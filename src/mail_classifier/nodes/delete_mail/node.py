"""Delete-mails node — dummy implementation for workflow validation."""

import structlog

from mail_classifier.state import MailClassifierState

logger = structlog.get_logger(__name__)

def delete_mails_node(state: MailClassifierState) -> dict:
    """LangGraph node: deletes approved messages (dummy implementation).

    Dummy behaviour:
    - Logs which message IDs would be deleted
    - Marks them as deleted=True in state without calling Gmail API
    Real implementation will call service.users().messages().trash() here.
    """

    approved_ids = state.approved_delete_ids
    dry_run = state.config.dry_run

    logger.info(
        "delete_mails_node started (dummy) | approved_for_delete=%d | dry_run=%s",
        len(approved_ids),
        dry_run,
    )

    if not approved_ids:
        logger.warning(
            "No message IDs in approved_delete_ids. "
            "Either no messages were marked for deletion or user confirmation step was skipped."
        )
        return {
            "deleted_ids": [],
            "status": "completed",
        }

    deleted_ids = []
    kept_ids = []

    for msg_id in approved_ids:
        if dry_run:
            logger.info(
                "DRY RUN — would delete message | id=%s", msg_id
            )
            deleted_ids.append(msg_id)
        else:
            # Dummy: pretend deletion succeeded
            logger.info(
                "DUMMY DELETE — skipping actual Gmail API call | id=%s", msg_id
            )
            deleted_ids.append(msg_id)

    # Mark deleted=True on the corresponding MessageRecord objects in state
    updated_messages = []
    for msg in state.messages:
        if msg.id in deleted_ids:
            updated_messages.append(msg.model_copy(update={"deleted": True}))
            logger.debug("Marked as deleted | id=%s | subject='%s'", msg.id, msg.subject)
        else:
            updated_messages.append(msg)
            kept_ids.append(msg.id)

    logger.info(
        "delete_mails_node complete (dummy) | deleted=%d | kept=%d | status=completed",
        len(deleted_ids),
        len(kept_ids),
    )

    return {
        "messages": updated_messages,
        "deleted_ids": deleted_ids,
        "kept_ids": kept_ids,
        "status": "completed",
    }