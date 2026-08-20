from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AssetKind(StrEnum):
    OBJECT = "object"
    RELATION = "relation"
    ATTRIBUTE = "attribute"
    METRIC = "metric"
    EVENT = "event"
    POLICY = "policy"


class SemanticAsset(BaseModel):
    key: str
    kind: AssetKind
    label: str
    description: str = ""
    domain: str
    owner: str
    aliases: list[str] = Field(default_factory=list)
    source: str | None = None
    unit: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    expression: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticRelation(BaseModel):
    key: str
    label: str
    source_object: str
    target_object: str
    cardinality: str
    description: str = ""


class DomainContract(BaseModel):
    name: str
    label: str
    version: str
    domain: str
    owner: str
    assets: list[SemanticAsset]
    relations: list[SemanticRelation]
