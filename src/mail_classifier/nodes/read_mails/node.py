"""Read-mails node for the LangGraph mail-classifier workflow."""

import structlog

from mail_classifier.state import MailClassifierState
from mail_classifier.nodes.read_mails.gmail_authenticate import authenticate
from mail_classifier.nodes.read_mails.read_mails import read_messages

logger = structlog.get_logger(__name__)


def read_mails_node(state: MailClassifierState) -> dict:
    """LangGraph node: authenticates with Gmail and fetches messages into state."""

    since = state.config.since_timestamp
    max_messages = state.config.max_messages

    logger.info(
        "read_mails_node started | since=%s | max_messages=%s | dry_run=%s",
        since.isoformat(),
        max_messages if max_messages else "unlimited",
        state.config.dry_run,
    )

    try:
        logger.info("Initiating Gmail OAuth authentication.")
        creds = authenticate()
        logger.info("Gmail authentication successful.")

        logger.info(
            "Calling read_messages | since=%s | max_messages=%s",
            since.isoformat(),
            max_messages if max_messages else "unlimited",
        )
        records = read_messages(
            timestamp=since,
            creds=creds,
            max_messages=max_messages,
        )

        logger.info(
            "read_mails_node complete | fetched=%d | status=fetched",
            len(records),
        )

        return {
            "messages": records,
            "fetched_count": len(records),
            "status": "fetched",
        }

    except Exception as e:
        logger.exception(
            "read_mails_node failed with an unexpected error | error=%s", str(e)
        )
        return {
            "status": "failed",
            "errors": [f"read_mails_node failed: {str(e)}"],
        }