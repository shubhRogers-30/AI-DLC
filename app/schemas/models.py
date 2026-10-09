from typing import Any
from pydantic import BaseModel, Field

class Approval(BaseModel):
    approved: bool
    comment: str = ""
    approver: str = "human"

class WorkflowRequest(BaseModel):
    jira_key: str
    repository: str
    story: str | None = None
