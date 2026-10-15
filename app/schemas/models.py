from typing import Literal
from pydantic import BaseModel, Field

class Approval(BaseModel):
    approved: bool
    comment: str = ""
    approver: str = "human"
    approval_type: Literal["architecture_approval", "code_approval", "merge_approval"] | None = None

class WorkflowRequest(BaseModel):
    jira_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*-\d+$", max_length=100)
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=200)
    story: str | None = None
    stack: str | None = None
    target: str | None = None
    branch_name: str | None = Field(default=None, min_length=1, max_length=240)
    base_branch: str | None = Field(default=None, min_length=1, max_length=240)
    reuse_existing_branch: bool = False
