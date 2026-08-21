from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.database import (
    PythonExtensionRecord,
    PythonExtensionRunRecord,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

ALLOWED_MODULES = {"datetime", "decimal", "json", "math", "re", "statistics"}
FORBIDDEN_CALLS = {"breakpoint", "compile", "eval", "exec", "globals", "help", "input", "open"}
MAX_CODE_BYTES = 100_000
MAX_OUTPUT_BYTES = 1_000_000


class PythonExtensionInput(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    label: str = Field(min_length=2, max_length=160)
    code: str = Field(min_length=20, max_length=MAX_CODE_BYTES)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    memory_mb: int = Field(default=256, ge=64, le=512)
    published: bool = False


class PythonRunInput(BaseModel):
    input_data: dict[str, Any] = Field(default_factory=dict)


class PythonExtensionService:
    """Store and run bounded pure-Python transforms in isolated subprocesses."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(PythonExtensionRecord).order_by(PythonExtensionRecord.key)
            ).all()
            return [self._serialize(record) for record in records]

    def save(self, payload: PythonExtensionInput) -> dict[str, Any]:
        validation = self.validate(payload.code)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        with self._session_factory() as session:
            record = session.get(PythonExtensionRecord, payload.key)
            if record is None:
                record = PythonExtensionRecord(
                    **payload.model_dump(), version=1, updated_at=datetime.now(UTC)
                )
                session.add(record)
            else:
                changed = record.code != payload.code
                for key, value in payload.model_dump().items():
                    setattr(record, key, value)
                record.version = record.version + 1 if changed else record.version
                record.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def delete(self, extension_key: str) -> None:
        with self._session_factory() as session:
            record = session.get(PythonExtensionRecord, extension_key)
            if record is None:
                raise LookupError(extension_key)
            session.delete(record)
            session.commit()

    @staticmethod
    def validate(code: str) -> dict[str, Any]:
        errors: list[str] = []
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as error:
            return {"valid": False, "errors": [f"语法错误：{error.msg}（第 {error.lineno} 行）"]}
        transform_found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = (
                    [alias.name.split(".", 1)[0] for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [(node.module or "").split(".", 1)[0]]
                )
                denied = [module for module in modules if module not in ALLOWED_MODULES]
                if denied:
                    errors.append(f"不允许导入：{', '.join(denied)}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and (node.func.id in FORBIDDEN_CALLS or node.func.id == "__import__")
            ):
                errors.append(f"不允许调用：{node.func.id}")
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                errors.append("不允许访问双下划线属性")
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                errors.append("不允许声明 global/nonlocal")
            if isinstance(node, ast.FunctionDef) and node.name == "transform":
                transform_found = len(node.args.args) == 1
        if not transform_found:
            errors.append("必须定义 transform(input_data) 函数")
        return {
            "valid": not errors,
            "errors": list(dict.fromkeys(errors)),
            "allowed_modules": sorted(ALLOWED_MODULES),
            "contract": "transform(input_data: dict) -> JSON-compatible value",
        }

    def run(self, extension_key: str, input_data: dict[str, Any]) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(PythonExtensionRecord, extension_key)
            if record is None:
                raise LookupError(extension_key)
            if not record.published:
                raise ValueError("Python 扩展尚未发布")
            code = record.code
            timeout = record.timeout_seconds
            version = record.version

        run_id = f"py_{uuid4().hex[:16]}"
        started_at = datetime.now(UTC)
        status = "completed"
        output_data: dict[str, Any] = {}
        logs = ""
        error_message: str | None = None
        try:
            execution = self._execute(code, input_data, timeout)
            raw_output = execution.get("output")
            output_data = raw_output if isinstance(raw_output, dict) else {"result": raw_output}
            logs = str(execution.get("logs", ""))[:20_000]
        except (ValueError, subprocess.SubprocessError) as error:
            status = "failed"
            error_message = str(error)

        finished_at = datetime.now(UTC)
        result = {
            "run_id": run_id,
            "extension_key": extension_key,
            "version": version,
            "status": status,
            "output": output_data,
            "logs": logs,
            "error": error_message,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        }
        with self._session_factory() as session:
            session.add(
                PythonExtensionRunRecord(
                    run_id=run_id,
                    extension_key=extension_key,
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    input_data=input_data,
                    output_data=output_data,
                    logs=logs,
                    error=error_message,
                )
            )
            session.commit()
        return result

    def runs(self, extension_key: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            query = select(PythonExtensionRunRecord)
            if extension_key:
                query = query.where(PythonExtensionRunRecord.extension_key == extension_key)
            records = session.scalars(
                query.order_by(PythonExtensionRunRecord.started_at.desc()).limit(
                    min(max(limit, 1), 200)
                )
            ).all()
            return [
                {
                    "run_id": record.run_id,
                    "extension_key": record.extension_key,
                    "status": record.status,
                    "output": record.output_data,
                    "logs": record.logs,
                    "error": record.error,
                    "started_at": record.started_at.isoformat(),
                    "finished_at": record.finished_at.isoformat(),
                }
                for record in records
            ]

    @staticmethod
    def _execute(code: str, input_data: dict[str, Any], timeout: int) -> dict[str, Any]:
        validation = PythonExtensionService.validate(code)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        wrapper = (
            code
            + "\n\nimport contextlib as _contextlib, io as _io, json as _json\n"
            + "_input = _json.loads(input())\n"
            + "_logs = _io.StringIO()\n"
            + "with _contextlib.redirect_stdout(_logs):\n"
            + "    _output = transform(_input)\n"
            + "print(_json.dumps({'output': _output, 'logs': _logs.getvalue()}, "
            + "ensure_ascii=False, default=str))\n"
        )
        with tempfile.TemporaryDirectory(prefix="fathom-python-") as directory:
            script = Path(directory) / "extension.py"
            script.write_text(wrapper, encoding="utf-8")
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", "-S", str(script)],
                    input=json.dumps(input_data, ensure_ascii=False),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=timeout,
                    cwd=directory,
                    env={"PYTHONIOENCODING": "utf-8"},
                    creationflags=creation_flags,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError(f"执行超过 {timeout} 秒，已终止") from error
        if completed.returncode != 0:
            raise ValueError((completed.stderr or "Python 扩展执行失败")[:2000])
        if len(completed.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise ValueError("输出超过 1 MB 限制")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("扩展未返回有效 JSON") from error
        if not isinstance(result, dict):
            raise ValueError("扩展输出契约无效")
        return result

    @staticmethod
    def _serialize(record: PythonExtensionRecord) -> dict[str, Any]:
        return {
            "key": record.key,
            "label": record.label,
            "version": record.version,
            "code": record.code,
            "timeout_seconds": record.timeout_seconds,
            "memory_mb": record.memory_mb,
            "published": record.published,
            "updated_at": record.updated_at.isoformat(),
            "limits": {
                "network": "blocked",
                "filesystem": "temporary working directory only",
                "output": "1 MB",
            },
        }
