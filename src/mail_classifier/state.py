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
