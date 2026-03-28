"""LangGraph state models for the mail-classifier workflow."""

from __future__ import annotations

import operator

from typing import Dict, List, Literal, Annotated
from mail_classifier.models import MessageRecord, WorkflowConfig

from pydantic import BaseModel, Field


WorkflowStatus = Literal[
    "initialized",
    "authenticated",
    "fetched",
    "classified",
    "awaiting_confirmation",
    "executed",
    "completed",
    "failed",
]

# ---------------------------------------------------------------------------
# Custom reducer for messages
# ---------------------------------------------------------------------------
 
def merge_messages(
    existing: List[MessageRecord],
    new: List[MessageRecord],
) -> List[MessageRecord]:
    """
    Smart reducer for the messages field.
 
    Behaviour:
    - If a message in `new` has the same ID as one in `existing`, it UPDATES
      the existing record in place (e.g. classifier enriching a fetched message).
    - If a message in `new` has a new ID, it APPENDS it (e.g. read_mails adding
      freshly fetched messages to an empty list).
 
    This replaces operator.add which would blindly append and cause duplicates
    when classify_mails_node returns updated copies of already-stored messages.
 
    Example:
        existing = [MessageRecord(id="1", suggested_action=None)]
        new      = [MessageRecord(id="1", suggested_action="delete")]
        result   = [MessageRecord(id="1", suggested_action="delete")]  ← updated, not doubled
    """
    # Build a dict keyed by message ID to preserve insertion order + allow updates
    merged: Dict[str, MessageRecord] = {m.id: m for m in existing}
    for msg in new:
        merged[msg.id] = msg     # update if exists, insert if new
    return list(merged.values())

class MailClassifierState(BaseModel):
    """Serializable state shared across LangGraph nodes."""

    config: WorkflowConfig
    status: WorkflowStatus = "initialized"

    messages: Annotated[List[MessageRecord], operator.add]  = Field(default_factory=list)

    fetched_count: int = 0
    classified_count: int = 0

    delete_candidates: List[str] = Field(default_factory=list)
    approved_delete_ids: List[str] = Field(default_factory=list)
    deleted_ids: List[str] = Field(default_factory=list)
    kept_ids: List[str] = Field(default_factory=list)

    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    summary: Dict[str, int] = Field(default_factory=dict)

def make_initial_state(config: WorkflowConfig) -> MailClassifierState:
    return MailClassifierState(config=config)
