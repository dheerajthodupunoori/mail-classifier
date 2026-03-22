"""Classify-mails node — dummy implementation for workflow validation."""

import logging

from mail_classifier.state import MailClassifierState

logger = logging.getLogger(__name__)


def classify_mails_node(state: MailClassifierState) -> dict:
    """LangGraph node: classifies fetched messages (dummy implementation).

    Dummy behaviour:
    - Marks every message with suggested_action="review"
    - Sets confidence=1.0 and a placeholder reasoning string
    Real implementation will call an LLM here.
    """

    messages = state.messages

    logger.info(
        "classify_mails_node started (dummy) | messages_to_classify=%d",
        len(messages),
    )

    if not messages:
        logger.warning(
            "No messages in state to classify. "
            "Ensure read_mails_node ran successfully before this node."
        )
        return {
            "classified_count": 0,
            "status": "classified",
        }

    # Dummy: stamp every message with suggested_action="review"
    classified = []
    for msg in messages:
        updated = msg.model_copy(update={
            "suggested_action": "review",
            "confidence": 1.0,
            "reasoning": "[DUMMY] Classification not yet implemented — defaulting to review.",
        })
        classified.append(updated)
        logger.debug(
            "Classified (dummy) | id=%s | subject='%s' | suggested_action=%s",
            updated.id,
            updated.subject or "(no subject)",
            updated.suggested_action,
        )

    logger.info(
        "classify_mails_node complete (dummy) | classified=%d | status=classified",
        len(classified),
    )

    # Replace messages entirely with the updated copies.
    # NOTE: We return the full list here because messages uses operator.add as a
    # reducer — to avoid doubling the list, the graph must be configured to
    # reset messages before this node runs, OR we clear and rebuild.
    # Simplest pattern for MVP: store classified results in a separate key,
    # or ensure this is the only node writing to messages after read_mails_node.
    return {
        "messages": classified,
        "classified_count": len(classified),
        "status": "classified",
    }