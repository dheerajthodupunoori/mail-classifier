from pydantic import BaseModel, Field
from typing import List, Literal
import datetime
from typing import List, Optional

SuggestedAction = Literal["keep", "review", "delete"]
UserDecision = Literal["approved_delete", "keep", "skip"]

class MessageRecord(BaseModel):
    """Normalized message payload enriched as it moves through the graph."""

    id: str
    thread_id: str
    label_ids: List[str] = Field(default_factory=list)
    snippet: str = ""
    time: datetime.datetime
    subject: str = ""
    sender: str = ""
    body_text: Optional[str] = None

    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reasoning: Optional[str] = None

    suggested_action: Optional[SuggestedAction] = None
    user_decision: Optional[UserDecision] = None

    deleted: bool = False
    delete_error: Optional[str] = None

class WorkflowConfig(BaseModel):
    """Inputs that control how the graph fetches and processes messages."""

    since_timestamp: datetime.datetime
    allow_delete: bool = False
    dry_run: bool = True
    max_messages: Optional[int] = None