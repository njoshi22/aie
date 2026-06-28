from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PermissionTier:
    OBSERVER = "observer"
    ANALYST = "analyst"
    AUTONOMOUS = "autonomous"


class MemoryType:
    PRICING_FIELD_RULE = "pricing_field_rule"
    MATERIALITY_THRESHOLD = "materiality_threshold"
    CONTRACT_TERM = "contract_term"
    CRM_RECORD = "crm_record"


class Memory(BaseModel):
    id: str = Field(default_factory=_uuid)
    session_id: str
    agent_id: str
    type: str
    content: str
    embedding: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 0.5
    access_count: int = 0
    sessions_since_used: int = 0   # consecutive sessions a memory has gone unused → idle decay
    created_at: datetime = Field(default_factory=_now)
    last_used_at: datetime | None = None


class PolicyRule(BaseModel):
    id: str = Field(default_factory=_uuid)
    description: str
    condition: dict[str, Any]
    route_to: str | None
    action: str = "escalate"
    version: int = 1


class Session(BaseModel):
    id: str = Field(default_factory=_uuid)
    agent_id: str
    env_id: str | None = None
    task: str
    status: str = "running"
    outcome: dict[str, Any] | None = None
    memories_used: list[str] = Field(default_factory=list)
    memories_created: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None


class Agent(BaseModel):
    id: str = Field(default_factory=_uuid)
    name: str
    reputation_score: float = 0.1
    total_sessions: int = 0
    successful_sessions: int = 0
    permission_tier: str = PermissionTier.OBSERVER
    created_at: datetime = Field(default_factory=_now)


class ApprovalStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REROUTED = "rerouted"


class Approval(BaseModel):
    id: str = Field(default_factory=_uuid)
    request_id: str = Field(default_factory=_uuid)
    method: str = "approval.route"
    join: str = "all"
    step_id: str = ""
    depends_on: list[str] = Field(default_factory=list)
    deal_id: str
    discrepancy: dict[str, Any]
    approver_role: str
    status: str = ApprovalStatus.PENDING
    comment: str = ""
    token: str = Field(default_factory=_uuid)
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None
