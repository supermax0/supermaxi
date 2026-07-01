from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from modules.workspace.models.workspace_session import WorkspaceSession


@dataclass
class WorkflowContext:
    session: WorkspaceSession
    recipe: Dict[str, Any]
    user_id: Optional[int] = None
    user_input: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def session_id(self) -> str:
        return self.session.id

    @property
    def workflow_type(self) -> str:
        return self.session.workflow_type

    @property
    def current_step_id(self) -> Optional[str]:
        return self.session.current_step_id
