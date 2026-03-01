from pydantic import BaseModel
from typing import List
import datetime


class GmailMessage(BaseModel):
    id: str
    threadId: str
    labelIds: List[str]
    snippet: str
    time: datetime.datetime
    subject: str
    sender: str