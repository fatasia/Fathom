from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PipelineStep(BaseModel):
    operation: Literal[
        "rename",
        "cast",
        "filter",
        "derive",
        "deduplicate",
        "quality_check",
        "onn_map",
    ]
    configuration: dict[str, Any] = Field(default_factory=dict)


class PipelineDefinition(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    label: str = Field(min_length=2, max_length=160)
    source: str
    target: str
    mode: Literal["preview", "full", "incremental"] = "preview"
    cursor_field: str | None = None
    steps: list[PipelineStep] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_incremental_cursor(self) -> PipelineDefinition:
        if self.mode == "incremental" and not self.cursor_field:
            raise ValueError("增量管道必须声明 cursor_field")
        return self


class PythonExtensionManifest(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    label: str
    version: str
    entrypoint: str
    timeout_seconds: int = Field(default=30, ge=1, le=900)
    memory_mb: int = Field(default=256, ge=64, le=4096)
    network_access: bool = False
    writable_paths: list[str] = Field(default_factory=list)
    approved: bool = False
