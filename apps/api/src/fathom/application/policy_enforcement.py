from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.runtime_records import PolicyDecisionRecord
from fathom.application.security import ROLE_ORDER
from sqlalchemy.orm import Session, sessionmaker


class PolicyEnforcementPoint:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        max_rows: int = 1_000,
        timeout_seconds: int = 8,
    ) -> None:
        self._session_factory = session_factory
        self._max_rows = max_rows
        self._timeout_seconds = timeout_seconds

    def decide_query(
        self,
        *,
        principal: str,
        role: str,
        resource: str,
        object_ids: list[str],
        authorized_objects: set[str] | None,
    ) -> dict[str, Any]:
        denied_objects = (
            sorted(set(object_ids) - authorized_objects)
            if authorized_objects is not None
            else []
        )
        allowed = ROLE_ORDER.get(role, -1) >= ROLE_ORDER["viewer"] and not denied_objects
        reason = (
            "只读语义查询已授权"
            if allowed
            else (
                f"对象范围越权：{', '.join(denied_objects)}"
                if denied_objects
                else "角色无查询权限"
            )
        )
        return self._record(
            principal=principal,
            role=role,
            action="semantic.query",
            resource=resource,
            effect="allow" if allowed else "deny",
            reason=reason,
            obligations=[
                {"kind": "read_only"},
                {"kind": "max_rows", "value": self._max_rows},
                {"kind": "timeout_seconds", "value": self._timeout_seconds},
                {"kind": "object_scope", "value": object_ids},
            ],
            context={"object_ids": object_ids},
        )

    def decide_capability(
        self,
        *,
        principal: str,
        role: str,
        resource: str,
        minimum_role: str,
        approval_required: bool,
        approval_token: str | None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        role_allowed = ROLE_ORDER.get(role, -1) >= ROLE_ORDER.get(minimum_role, 99)
        approval_allowed = not approval_required or self._approval_valid(approval_token)
        allowed = role_allowed and approval_allowed
        if not role_allowed:
            reason = f"能力要求至少 {minimum_role} 角色"
        elif not approval_allowed:
            reason = "缺少有效动作批准令牌"
        else:
            reason = "受治理能力调用已授权"
        return self._record(
            principal=principal,
            role=role,
            action="capability.invoke",
            resource=resource,
            effect="allow" if allowed else "deny",
            reason=reason,
            obligations=[{"kind": "audit"}, {"kind": "idempotency"}],
            context=context or {},
        )

    def _approval_valid(self, approval_token: str | None) -> bool:
        expected = os.getenv("FATHOM_ACTION_APPROVAL_TOKEN", "")
        return bool(expected and approval_token and hmac.compare_digest(expected, approval_token))

    def _record(
        self,
        *,
        principal: str,
        role: str,
        action: str,
        resource: str,
        effect: str,
        reason: str,
        obligations: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        decision_id = f"pd_{uuid4().hex[:20]}"
        created_at = datetime.now(UTC)
        with self._session_factory() as session:
            session.add(
                PolicyDecisionRecord(
                    decision_id=decision_id,
                    created_at=created_at,
                    principal=principal,
                    role=role,
                    action=action,
                    resource=resource,
                    effect=effect,
                    reason=reason,
                    obligations=obligations,
                    context=context,
                )
            )
            session.commit()
        return {
            "decision_id": decision_id,
            "created_at": created_at.isoformat(),
            "principal": principal,
            "role": role,
            "action": action,
            "resource": resource,
            "effect": effect,
            "reason": reason,
            "obligations": obligations,
            "context": context,
        }

