"""
Classify-mails node — real LLM implementation using Gemini 2.5 Flash.

Each message is classified individually using LangChain's structured output.
The LLM returns a validated Pydantic object directly — no manual JSON parsing.

Flow:
    For each MessageRecord in state.messages:
        1. Build prompt from subject / sender / snippet / body_text
        2. Call LLM with structured output schema (EmailClassification)
        3. Update MessageRecord with suggested_action, confidence, reasoning
    Return updated messages + classified_count.
"""

import os
from typing import List, Literal, Optional

import structlog
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from mail_classifier.models import MessageRecord
from mail_classifier.state import MailClassifierState
from mail_classifier.nodes.classify_mail.prompts import (
    BODY_MAX_CHARS,
    CLASSIFIER_SYSTEM_PROMPT,
    CLASSIFIER_USER_PROMPT,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------

class EmailClassification(BaseModel):
    """
    Structured output schema for the classifier LLM call.
    LangChain's with_structured_output() enforces this shape on the response.
    """
    suggested_action: Literal["keep", "delete", "review"] = Field(
        description="What to do with this email."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the classification between 0.0 and 1.0.",
    )
    reasoning: str = Field(
        description="One sentence explaining the classification decision."
    )


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _build_llm() -> ChatGoogleGenerativeAI:
    """
    Builds and returns the LLM client.

    Reads GOOGLE_API_KEY from environment — set this in your .env file.
    temperature=0 ensures deterministic, reproducible classifications.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GOOGLE_API_KEY environment variable is not set. "
            "Get a free key at https://aistudio.google.com and add it to your .env file."
        )
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        # temperature=0 → deterministic output, essential for classification
        temperature=0,
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(msg: MessageRecord) -> str:
    """Formats the user prompt for a single MessageRecord."""
    # Truncate body to control token usage.
    # If no body, fall back to snippet — classifier still works with less context.
    body = msg.body_text or msg.snippet or "(no body available)"
    if len(body) > BODY_MAX_CHARS:
        body = body[:BODY_MAX_CHARS] + "... [truncated]"

    return CLASSIFIER_USER_PROMPT.format(
        subject=msg.subject or "(no subject)",
        sender=msg.sender or "(unknown sender)",
        snippet=msg.snippet or "",
        body=body,
    )


# ---------------------------------------------------------------------------
# Single message classifier
# ---------------------------------------------------------------------------

def _classify_single(
    msg: MessageRecord,
    chain,
) -> Optional[EmailClassification]:
    """
    Classifies a single MessageRecord using the LLM chain.

    Returns an EmailClassification on success, None on failure.
    Failure is intentionally non-fatal — the node continues with other messages.
    """
    log = logger.bind(message_id=msg.id, subject=msg.subject or "(no subject)")
    try:
        log.debug("llm_call_started")
        user_prompt = _build_prompt(msg)
        result: EmailClassification = chain.invoke({"user_prompt": user_prompt})
        log.debug(
            "llm_call_complete",
            suggested_action=result.suggested_action,
            confidence=result.confidence,
            reasoning=result.reasoning,
        )
        return result
    except Exception as e:
        log.error("llm_call_failed", error=str(e))
        return None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def classify_mails_node(state: MailClassifierState) -> dict:
    """
    LangGraph node: classifies each fetched message using Gemini 2.5 Flash.

    - Reads messages from state (populated by read_mails_node)
    - Classifies each one as keep / delete / review
    - Updates MessageRecord with suggested_action, confidence, reasoning
    - On LLM failure for a message, defaults to suggested_action="review"
      so no message is silently lost
    """

    messages = state.messages

    logger.info(
        "classify_mails_node_started",
        messages_to_classify=len(messages),
    )

    if not messages:
        logger.warning(
            "classify_mails_no_messages",
            hint="Ensure read_mails_node ran successfully before this node",
        )
        return {"classified_count": 0, "status": "classified"}

    # --- Build LLM chain ---
    # Chain = prompt | llm.with_structured_output(EmailClassification)
    # with_structured_output() tells the LLM to return JSON matching the schema
    # and validates it into an EmailClassification Pydantic object automatically.
    try:
        llm = _build_llm()
        structured_llm = llm.with_structured_output(EmailClassification)
        prompt = ChatPromptTemplate.from_messages([
            ("system", CLASSIFIER_SYSTEM_PROMPT),
            ("human", "{user_prompt}"),
        ])
        chain = prompt | structured_llm
        logger.info("llm_chain_built", model="gemini-2.5-flash")
    except EnvironmentError as e:
        logger.error("llm_chain_build_failed", error=str(e))
        return {
            "status": "failed",
            "errors": [str(e)],
        }

    # --- Classify each message ---
    classified: List[MessageRecord] = []
    llm_errors = 0
    action_counts = {"keep": 0, "delete": 0, "review": 0}

    for idx, msg in enumerate(messages, 1):
        log = logger.bind(
            message_id=msg.id,
            index=idx,
            total=len(messages),
        )
        log.info("classifying_message")

        result = _classify_single(msg, chain)

        if result:
            updated = msg.model_copy(update={
                "suggested_action": result.suggested_action,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
            })
            action_counts[result.suggested_action] += 1
            log.info(
                "message_classified",
                suggested_action=result.suggested_action,
                confidence=result.confidence,
            )
        else:
            # LLM call failed for this message — default to "review" so the
            # user still sees it rather than it being silently skipped.
            updated = msg.model_copy(update={
                "suggested_action": "review",
                "confidence": 0.0,
                "reasoning": "Classification failed — defaulting to review for safety.",
            })
            action_counts["review"] += 1
            llm_errors += 1
            log.warning(
                "message_classification_fallback",
                fallback_action="review",
                hint="LLM call failed — message marked for review",
            )

        classified.append(updated)

    # --- Build summary ---
    summary = {
        "keep":   action_counts["keep"],
        "delete": action_counts["delete"],
        "review": action_counts["review"],
        "llm_errors": llm_errors,
    }

    logger.info(
        "classify_mails_node_complete",
        classified=len(classified),
        keep=action_counts["keep"],
        delete=action_counts["delete"],
        review=action_counts["review"],
        llm_errors=llm_errors,
        status="classified",
    )

    # NOTE: merge_messages reducer in state.py handles updating existing
    # MessageRecords by ID — no duplicates, classified fields are enriched.
    return {
        "messages": classified,
        "classified_count": len(classified),
        "status": "classified",
        "summary": summary,
    }