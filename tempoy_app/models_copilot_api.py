from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass(slots=True)
class CopilotApiCapabilities:
    api_enabled: bool
    mode: str
    allowed_projects: List[str] = field(default_factory=list)
    allowed_issue_types: List[str] = field(default_factory=list)
    require_write_confirmation: bool = True
    session_active: bool = False
    session_expires_at: Optional[int] = None
    endpoints: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CopilotApiHealth:
    status: str
    api_enabled: bool
    mode: str
    session_active: bool
    session_expires_at: Optional[int]
    bound_host: str
    bound_port: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CopilotApiSession:
    token: str
    mode: str
    client_name: Optional[str] = None
    expires_at: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)
