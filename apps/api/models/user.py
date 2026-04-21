from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class APIKeyResponse(BaseModel):
    id: UUID
    key_prefix: str
    name: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked: bool


class UsageSummary(BaseModel):
    user_id: UUID
    plan: str
    period_start: str
    period_end: str
    api_calls: int
    limit: int
    remaining: int
