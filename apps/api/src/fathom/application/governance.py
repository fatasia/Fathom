from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fathom.adapters.storage.database import (
    EvaluationRunRecord,
    SemanticAssetRecord,
    SemanticChangeRecord,
)
from fathom.domains.semantics.models import AssetKind, SemanticAsset
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified


class GovernanceDecision(BaseModel):
    action: Literal["start_review", "approve", "reject", "publish", "rollback"]
    actor: str = Field(min_length=2, max_length=160)
    comment: str = Field(default="", max_length=1000)


class SemanticAssetProposal(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$", max_length=160)
    kind: AssetKind
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    domain: str = Field(min_length=1, max_length=160)
    owner: str = Field(min_length=1, max_length=160)
    aliases: list[str] = Field(default_factory=list)
    source: str | None = None
    unit: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    expression: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GovernanceService:
    """Human-gated semantic evolution with evaluation receipts and rollback."""

    transitions = {
        "start_review": ({"candidate"}, "in_review"),
        "approve": ({"in_review"}, "approved"),
        "reject": ({"candidate", "in_review"}, "rejected"),
        "publish": ({"approved"}, "published"),
        "rollback": ({"published"}, "rolled_back"),
    }

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def seed(self) -> None:
        now = datetime.now(UTC)
        proposals = [
            {
                "change_id": "chg_alias_completion_rate",
                "kind": "alias",
                "title": "“完成率”可能是“订单达成率”的同义词",
                "description": "来源于生产用户的重复纠正，发布后进入受控业务词典。",
                "confidence": 0.86,
                "impact": {"assets": 1, "risk": "low"},
                "evidence": ["feedback:27", "users:12", "conflicts:0"],
                "patch": {
                    "operation": "add_alias",
                    "asset_key": "order_fulfillment_rate",
                    "alias": "完成率",
                },
            },
            {
                "change_id": "chg_oee_description",
                "kind": "definition",
                "title": "补充 OEE 的工业计算边界说明",
                "description": "明确计划停机、换型和质量损失的处理边界。",
                "confidence": 0.93,
                "impact": {"assets": 1, "risk": "medium"},
                "evidence": ["queries:38", "golden_cases:18", "conflicts:0"],
                "patch": {
                    "operation": "update_description",
                    "asset_key": "oee",
                    "description": "设备综合效率；计算边界、计划停机与质量损失规则由认证口径定义。",
                },
            },
            {
                "change_id": "chg_downtime_alias",
                "kind": "alias",
                "title": "将“停线时长”纳入停机时长词典",
                "description": "来自车间班组的稳定用语，未发现指标冲突。",
                "confidence": 0.91,
                "impact": {"assets": 1, "risk": "low"},
                "evidence": ["queries:19", "users:8", "conflicts:0"],
                "patch": {
                    "operation": "add_alias",
                    "asset_key": "downtime_minutes",
                    "alias": "停线时长",
                },
            },
        ]
        with self._session_factory() as session:
            for proposal in proposals:
                if session.get(SemanticChangeRecord, proposal["change_id"]):
                    continue
                session.add(
                    SemanticChangeRecord(
                        **proposal,
                        created_at=now,
                        updated_at=now,
                        status="candidate",
                        history=[
                            {
                                "action": "proposed",
                                "actor": "evolution_agent",
                                "at": now.isoformat(),
                                "comment": "由失败问题、反馈与口径差异生成候选",
                            }
                        ],
                    )
                )
            session.commit()

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            statement = select(SemanticChangeRecord).order_by(
                SemanticChangeRecord.updated_at.desc()
            )
            if status:
                statement = statement.where(SemanticChangeRecord.status == status)
            return [self._serialize(item) for item in session.scalars(statement).all()]

    def propose_asset(
        self, proposal: SemanticAssetProposal, actor: str = "semantic_builder"
    ) -> dict[str, Any]:
        asset = SemanticAsset.model_validate(proposal.model_dump())
        now = datetime.now(UTC)
        with self._session_factory() as session:
            if session.get(SemanticAssetRecord, asset.key):
                raise ValueError(f"语义资产已存在：{asset.key}")
            duplicate = session.scalar(
                select(SemanticChangeRecord.change_id).where(
                    SemanticChangeRecord.status.in_(["candidate", "in_review", "approved"]),
                    SemanticChangeRecord.title == f"新增{asset.kind.value}：{asset.label}",
                )
            )
            if duplicate:
                raise ValueError(f"该资产已有未完成候选：{duplicate}")
            record = SemanticChangeRecord(
                change_id=f"chg_{uuid4().hex[:16]}",
                created_at=now,
                updated_at=now,
                kind=asset.kind.value,
                title=f"新增{asset.kind.value}：{asset.label}",
                description=asset.description or "由语义建设工作台提交的新资产候选。",
                confidence=1.0,
                impact={"assets": 1, "risk": "medium", "new_asset": True},
                evidence=["source:human_builder", "schema:validated"],
                patch={"operation": "add_asset", "definition": asset.model_dump(mode="json")},
                status="candidate",
                history=[
                    {
                        "action": "proposed",
                        "actor": actor,
                        "at": now.isoformat(),
                        "comment": "人工提交并通过结构校验",
                    }
                ],
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def get(self, change_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            item = session.get(SemanticChangeRecord, change_id)
            return self._serialize(item) if item else None

    def decide(self, change_id: str, decision: GovernanceDecision) -> dict[str, Any]:
        allowed, target = self.transitions[decision.action]
        with self._session_factory() as session:
            change = session.get(SemanticChangeRecord, change_id)
            if change is None:
                raise LookupError(change_id)
            if change.status not in allowed:
                raise ValueError(
                    f"状态 {change.status} 不能执行 {decision.action}；"
                    f"允许状态：{', '.join(sorted(allowed))}"
                )
            evaluation = None
            if decision.action == "approve":
                evaluation = session.scalar(
                    select(EvaluationRunRecord)
                    .order_by(EvaluationRunRecord.created_at.desc())
                    .limit(1)
                )
                if evaluation is None or not evaluation.passed:
                    raise ValueError("批准前必须通过最新认证问题集，门槛为 99%")
                change.evaluation_run_id = evaluation.run_id
            if decision.action == "publish":
                self._apply_patch(session, change)
            if decision.action == "rollback":
                self._rollback(session, change)
            now = datetime.now(UTC)
            change.status = target
            change.updated_at = now
            change.history = [
                *change.history,
                {
                    "action": decision.action,
                    "actor": decision.actor,
                    "at": now.isoformat(),
                    "comment": decision.comment,
                    "evaluation_run_id": evaluation.run_id if evaluation else None,
                },
            ]
            session.commit()
            session.refresh(change)
            return self._serialize(change)

    @staticmethod
    def _apply_patch(session: Session, change: SemanticChangeRecord) -> None:
        patch = change.patch
        if patch.get("operation") == "add_asset":
            asset = SemanticAsset.model_validate(patch.get("definition"))
            if session.get(SemanticAssetRecord, asset.key):
                raise ValueError(f"目标语义资产已经存在：{asset.key}")
            change.previous_state = {"created": True, "asset_key": asset.key}
            session.add(
                SemanticAssetRecord(
                    key=asset.key,
                    kind=asset.kind.value,
                    label=asset.label,
                    domain=asset.domain,
                    owner=asset.owner,
                    definition=asset.model_dump(mode="json"),
                )
            )
            return
        asset = session.get(SemanticAssetRecord, patch.get("asset_key"))
        if asset is None:
            raise ValueError(f"目标语义资产不存在：{patch.get('asset_key')}")
        definition = deepcopy(asset.definition)
        change.previous_state = {"definition": deepcopy(definition)}
        operation = patch.get("operation")
        if operation == "add_alias":
            aliases = list(definition.get("aliases", []))
            alias = str(patch.get("alias", "")).strip()
            if not alias:
                raise ValueError("同义词不能为空")
            if alias not in aliases:
                aliases.append(alias)
            definition["aliases"] = aliases
        elif operation == "update_description":
            definition["description"] = str(patch.get("description", ""))
        else:
            raise ValueError(f"不支持的语义变更操作：{operation}")
        asset.definition = definition
        flag_modified(asset, "definition")

    @staticmethod
    def _rollback(session: Session, change: SemanticChangeRecord) -> None:
        previous = change.previous_state or {}
        if previous.get("created"):
            asset = session.get(SemanticAssetRecord, previous.get("asset_key"))
            if asset is None:
                raise ValueError("回滚目标语义资产不存在")
            session.delete(asset)
            return
        definition = previous.get("definition")
        if not definition:
            raise ValueError("没有可恢复的发布前快照")
        asset = session.get(SemanticAssetRecord, change.patch.get("asset_key"))
        if asset is None:
            raise ValueError("回滚目标语义资产不存在")
        asset.definition = deepcopy(definition)
        flag_modified(asset, "definition")

    @staticmethod
    def _serialize(change: SemanticChangeRecord) -> dict[str, Any]:
        return {
            "change_id": change.change_id,
            "created_at": change.created_at.isoformat(),
            "updated_at": change.updated_at.isoformat(),
            "kind": change.kind,
            "title": change.title,
            "description": change.description,
            "confidence": change.confidence,
            "confidence_percent": round(change.confidence * 100),
            "impact": change.impact,
            "evidence": change.evidence,
            "patch": change.patch,
            "status": change.status,
            "evaluation_run_id": change.evaluation_run_id,
            "history": change.history,
            "rollback_available": change.status == "published" and bool(change.previous_state),
        }
