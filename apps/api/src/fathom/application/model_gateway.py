from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

import certifi
from fathom.adapters.storage.database import ModelProviderRecord, ModelRouteRecord
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

PROVIDER_PROFILES = [
    {
        "key": "openai",
        "label": "OpenAI",
        "default_url": "https://api.openai.com/v1",
        "modes": ["responses", "chat_completions", "embeddings"],
        "capabilities": ["text", "vision", "tools", "structured_output", "embeddings"],
    },
    {
        "key": "azure_openai",
        "label": "Azure OpenAI",
        "default_url": "https://{resource}.openai.azure.com/openai",
        "modes": ["responses", "chat_completions", "embeddings"],
        "capabilities": ["text", "vision", "tools", "structured_output", "embeddings"],
    },
    {
        "key": "anthropic",
        "label": "Anthropic",
        "default_url": "https://api.anthropic.com/v1",
        "modes": ["messages"],
        "capabilities": ["text", "vision", "tools", "structured_output"],
    },
    {
        "key": "deepseek",
        "label": "DeepSeek",
        "default_url": "https://api.deepseek.com",
        "modes": ["chat_completions"],
        "capabilities": ["text", "tools", "structured_output"],
    },
    {
        "key": "qwen",
        "label": "通义千问",
        "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "modes": ["chat_completions", "embeddings"],
        "capabilities": ["text", "vision", "tools", "structured_output", "embeddings"],
    },
    {
        "key": "openai_compatible",
        "label": "OpenAI 兼容服务",
        "default_url": "http://127.0.0.1:8001/v1",
        "modes": ["chat_completions", "embeddings"],
        "capabilities": ["text", "tools", "structured_output", "embeddings"],
    },
    {
        "key": "ollama",
        "label": "Ollama",
        "default_url": "http://127.0.0.1:11434/v1",
        "modes": ["chat_completions", "embeddings"],
        "capabilities": ["text", "vision", "tools", "embeddings"],
    },
    {
        "key": "vllm",
        "label": "vLLM",
        "default_url": "http://127.0.0.1:8000/v1",
        "modes": ["chat_completions", "embeddings"],
        "capabilities": ["text", "tools", "structured_output", "embeddings"],
    },
    {
        "key": "custom",
        "label": "自定义 HTTP 模型",
        "default_url": "https://model.example.com/v1",
        "modes": ["responses", "chat_completions", "messages", "embeddings"],
        "capabilities": ["text"],
    },
]

MODEL_ROLES = [
    {"key": "planner", "label": "规划与意图", "recommended_temperature": 0.0},
    {"key": "semantic_extractor", "label": "语义抽取", "recommended_temperature": 0.0},
    {"key": "explainer", "label": "答案解释", "recommended_temperature": 0.2},
    {"key": "vision", "label": "跨模态理解", "recommended_temperature": 0.1},
    {"key": "embedding", "label": "向量嵌入", "recommended_temperature": None},
    {"key": "agent", "label": "上层 Agent", "recommended_temperature": 0.2},
]


class ModelProviderInput(BaseModel):
    key: str = Field(min_length=2, max_length=160, pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=160)
    provider_type: str = Field(min_length=2, max_length=64)
    base_url: str = Field(min_length=4, max_length=1000)
    api_mode: Literal["auto", "responses", "chat_completions", "messages", "embeddings"] = "auto"
    default_model: str = Field(min_length=1, max_length=256)
    secret_reference: str | None = Field(default=None, max_length=256)
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    capabilities: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url 必须是完整的 http/https URL")
        return value.rstrip("/")

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, value: str) -> str:
        supported = {profile["key"] for profile in PROVIDER_PROFILES}
        if value not in supported:
            raise ValueError(f"不支持的模型供应商类型：{value}")
        return value

    @model_validator(mode="after")
    def validate_parameters(self) -> ModelProviderInput:
        allowed = {
            "temperature",
            "top_p",
            "max_output_tokens",
            "timeout_seconds",
            "seed",
            "frequency_penalty",
            "presence_penalty",
        }
        unexpected = set(self.parameters) - allowed
        if unexpected:
            raise ValueError(f"不支持的模型参数：{', '.join(sorted(unexpected))}")
        temperature = self.parameters.get("temperature")
        if temperature is not None and not 0 <= float(temperature) <= 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        top_p = self.parameters.get("top_p")
        if top_p is not None and not 0 <= float(top_p) <= 1:
            raise ValueError("top_p 必须在 0 到 1 之间")
        max_tokens = self.parameters.get("max_output_tokens")
        if max_tokens is not None and not 1 <= int(max_tokens) <= 131072:
            raise ValueError("max_output_tokens 必须在 1 到 131072 之间")
        return self


class ModelRouteInput(BaseModel):
    role: str
    provider_key: str
    model_override: str | None = None
    parameter_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {role["key"] for role in MODEL_ROLES}:
            raise ValueError(f"不支持的模型角色：{value}")
        return value


class SecretStore:
    """Write-only OS credential storage with env references for server deployments."""

    service_name = "fathom-model-gateway"

    def save(self, provider_key: str, secret: str) -> str:
        try:
            import keyring

            keyring.set_password(self.service_name, provider_key, secret)
        except Exception as error:  # pragma: no cover - backend differs by operating system
            raise RuntimeError(
                "操作系统凭证库不可用，请改用 env://VARIABLE 引用 API Key"
            ) from error
        return f"keyring://model/{provider_key}"

    def resolve(self, reference: str | None) -> str | None:
        if not reference:
            return None
        if reference.startswith("env://"):
            return os.getenv(reference.removeprefix("env://"))
        if reference.startswith("keyring://model/"):
            try:
                import keyring

                return keyring.get_password(
                    self.service_name, reference.removeprefix("keyring://model/")
                )
            except Exception:
                return None
        return None


class ModelGatewayService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        secret_store: SecretStore | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.secret_store = secret_store or SecretStore()

    def seed_from_configuration(self, configuration: dict[str, Any]) -> None:
        for provider in configuration.get("providers", []):
            payload = ModelProviderInput.model_validate(provider)
            self.save_provider(payload, source="yaml", overwrite=False)
        for role, provider_key in configuration.get("routes", {}).items():
            payload = ModelRouteInput(role=role, provider_key=provider_key)
            self.save_route(payload, source="yaml", overwrite=False)

    def list_providers(self) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            records = session.scalars(
                select(ModelProviderRecord).order_by(ModelProviderRecord.name)
            )
            return [self._serialize_provider(record) for record in records]

    def save_provider(
        self,
        payload: ModelProviderInput,
        *,
        source: str = "web",
        overwrite: bool = True,
    ) -> dict[str, Any]:
        values = payload.model_dump(exclude={"api_key"})
        api_key = payload.api_key.get_secret_value() if payload.api_key else None
        if api_key:
            values["secret_reference"] = self.secret_store.save(payload.key, api_key)
        profile = self._profile(payload.provider_type)
        values["capabilities"] = payload.capabilities or profile["capabilities"]
        values["source"] = source
        with self.session_factory() as session:
            record = session.get(ModelProviderRecord, payload.key)
            if record is not None and not overwrite:
                return self._serialize_provider(record)
            if record is None:
                record = ModelProviderRecord(**values)
                session.add(record)
            else:
                for field, value in values.items():
                    setattr(record, field, value)
                record.status = "untested"
            session.commit()
            session.refresh(record)
            return self._serialize_provider(record)

    def probe(self, key: str) -> dict[str, Any]:
        with self.session_factory() as session:
            record = session.get(ModelProviderRecord, key)
            if record is None:
                raise LookupError(f"Model provider not found: {key}")
            profile = self._profile(record.provider_type)
            detected_mode = self._detected_mode(record.api_mode, profile["modes"])
            models: list[str] = []
            warning: str | None = None
            protocols: dict[str, dict[str, Any]] = {}
            try:
                models = self._fetch_models(record)
                candidate_modes = (
                    ["responses", "chat_completions"]
                    if record.api_mode == "auto"
                    else [record.api_mode]
                )
                for mode in candidate_modes:
                    if mode in {"responses", "chat_completions"}:
                        protocols[mode] = self._probe_text_mode(record, mode)
                successful_modes = [
                    mode for mode, result in protocols.items() if result["available"]
                ]
                if successful_modes:
                    detected_mode = successful_modes[0]
                    status = "ready"
                    message = f"连接成功，已识别 {len(models)} 个模型；{detected_mode} 调用通过"
                elif protocols:
                    status = "models_only"
                    message = (
                        f"可读取 {len(models)} 个模型，但文本生成调用未通过；"
                        "请检查令牌权限、额度或协议"
                    )
                else:
                    status = "ready"
                    message = f"连接成功，已识别 {len(models)} 个模型"
            except (OSError, ValueError, urllib.error.URLError) as error:
                status = "unreachable"
                message = "暂未连通；配置已保留，可检查 URL、网络与密钥"
                warning = str(error)
            record.status = status
            record.available_models = models[:500]
            record.last_tested_at = datetime.now(UTC)
            session.commit()
            return {
                "status": status,
                "message": message,
                "detected_mode": detected_mode,
                "capabilities": record.capabilities,
                "models": models[:500],
                "protocols": protocols,
                "warning": warning,
                "confirmation_required": record.api_mode == "auto",
            }

    def list_routes(self) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            records = {record.role: record for record in session.scalars(select(ModelRouteRecord))}
            return [
                {
                    **role,
                    "provider_key": records[role["key"]].provider_key
                    if role["key"] in records
                    else None,
                    "model_override": records[role["key"]].model_override
                    if role["key"] in records
                    else None,
                    "parameter_overrides": records[role["key"]].parameter_overrides
                    if role["key"] in records
                    else {},
                    "source": records[role["key"]].source if role["key"] in records else "default",
                }
                for role in MODEL_ROLES
            ]

    def invoke_role(
        self,
        role: str,
        prompt: str,
        image_data_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        if role not in {item["key"] for item in MODEL_ROLES}:
            raise ValueError(f"不支持的模型角色：{role}")
        with self.session_factory() as session:
            route = session.get(ModelRouteRecord, role)
            if route is None:
                raise ValueError(f"模型角色尚未绑定：{role}")
            provider = session.get(ModelProviderRecord, route.provider_key)
            if provider is None or not provider.enabled:
                raise ValueError(f"模型服务不可用：{route.provider_key}")
            if image_data_urls and "vision" not in provider.capabilities:
                raise ValueError("当前模型服务未声明 vision 能力")
            mode = self._detected_mode(
                provider.api_mode, self._profile(provider.provider_type)["modes"]
            )
            model = route.model_override or provider.default_model
            parameters = {**provider.parameters, **route.parameter_overrides}
            payload = self._invocation_payload(
                mode, model, prompt, image_data_urls or [], parameters
            )
            response = self._post_json(provider, self._mode_path(mode), payload)
            normalized = self.normalize_response(mode, response)
            return {
                **normalized,
                "role": role,
                "provider_key": provider.key,
                "model": model,
                "mode": mode,
            }

    def save_route(
        self,
        payload: ModelRouteInput,
        *,
        source: str = "web",
        overwrite: bool = True,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            if session.get(ModelProviderRecord, payload.provider_key) is None:
                raise ValueError(f"模型服务不存在：{payload.provider_key}")
            record = session.get(ModelRouteRecord, payload.role)
            if record is not None and not overwrite:
                return self._serialize_route(record)
            values = payload.model_dump()
            values.update(source=source, updated_at=datetime.now(UTC))
            if record is None:
                record = ModelRouteRecord(**values)
                session.add(record)
            else:
                for field, value in values.items():
                    setattr(record, field, value)
            session.commit()
            session.refresh(record)
            return self._serialize_route(record)

    @staticmethod
    def normalize_response(api_mode: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize provider-specific payloads into one internal response contract."""

        if api_mode == "responses":
            text = payload.get("output_text", "")
            if not text:
                text = "".join(
                    block.get("text", "")
                    for output in payload.get("output", [])
                    for block in output.get("content", [])
                    if block.get("type") in {"output_text", "text"}
                )
            usage = payload.get("usage", {})
            return {"text": text, "tool_calls": payload.get("output", []), "usage": usage}
        if api_mode == "messages":
            blocks = payload.get("content", [])
            text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
            return {"text": text, "tool_calls": blocks, "usage": payload.get("usage", {})}
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message", {})
        return {
            "text": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
            "usage": payload.get("usage", {}),
        }

    def _fetch_models(self, record: ModelProviderRecord) -> list[str]:
        url = f"{record.base_url.rstrip('/')}/models"
        headers = {"Accept": "application/json", "User-Agent": "FATHOM/0.1"}
        secret = self.secret_store.resolve(record.secret_reference)
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(  # noqa: S310
            request,
            timeout=5,
            context=self._ssl_context(),
        ) as response:
            payload = json.loads(response.read(2_000_000))
        return [str(item.get("id")) for item in payload.get("data", []) if item.get("id")]

    def _probe_text_mode(self, record: ModelProviderRecord, mode: str) -> dict[str, Any]:
        if mode == "responses":
            path = "responses"
            payload = {
                "model": record.default_model,
                "input": "Reply only FATHOM_OK",
                "max_output_tokens": 32,
            }
        else:
            path = "chat/completions"
            payload = {
                "model": record.default_model,
                "messages": [{"role": "user", "content": "Reply only FATHOM_OK"}],
                "temperature": 0,
                "max_tokens": 32,
                "stream": False,
            }
        try:
            response = self._post_json(record, path, payload)
            normalized = self.normalize_response(mode, response)
            return {"available": True, "sample": normalized["text"][:80]}
        except urllib.error.HTTPError as error:
            detail = self._safe_http_error(error)
            return {"available": False, "status_code": error.code, "detail": detail}
        except (OSError, ValueError, urllib.error.URLError) as error:
            return {"available": False, "detail": str(error)[:300]}

    def _post_json(
        self, record: ModelProviderRecord, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "FATHOM/0.1",
        }
        secret = self.secret_store.resolve(record.secret_reference)
        if secret:
            if record.provider_type == "anthropic":
                headers["x-api-key"] = secret
                headers["anthropic-version"] = "2023-06-01"
            else:
                headers["Authorization"] = f"Bearer {secret}"
        request = urllib.request.Request(
            f"{record.base_url.rstrip('/')}/{path}",
            headers=headers,
            data=json.dumps(payload).encode("utf-8"),
        )
        timeout = int(record.parameters.get("timeout_seconds", 45))
        with urllib.request.urlopen(  # noqa: S310
            request,
            timeout=timeout,
            context=self._ssl_context(),
        ) as response:
            return json.loads(response.read(2_000_000))

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        """Use an explicit, current CA bundle across Windows and server installs."""

        return ssl.create_default_context(cafile=certifi.where())

    @staticmethod
    def _mode_path(mode: str) -> str:
        return {
            "responses": "responses",
            "chat_completions": "chat/completions",
            "messages": "messages",
        }.get(mode, mode)

    @staticmethod
    def _invocation_payload(
        mode: str,
        model: str,
        prompt: str,
        images: list[str],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        temperature = parameters.get("temperature", 0.1)
        top_p = parameters.get("top_p", 0.9)
        max_tokens = int(parameters.get("max_output_tokens", 2048))
        if mode == "responses":
            content = [{"type": "input_text", "text": prompt}]
            content.extend({"type": "input_image", "image_url": image} for image in images)
            return {
                "model": model,
                "input": [{"role": "user", "content": content}],
                "temperature": temperature,
                "top_p": top_p,
                "max_output_tokens": max_tokens,
            }
        if mode == "messages":
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for image in images:
                header, encoded = image.split(",", 1)
                media_type = header.removeprefix("data:").split(";", 1)[0]
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": encoded,
                        },
                    }
                )
            return {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
            }
        content: str | list[dict[str, Any]] = prompt
        if images:
            blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            blocks.extend({"type": "image_url", "image_url": {"url": image}} for image in images)
            content = blocks
        return {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": False,
        }

    @staticmethod
    def _safe_http_error(error: urllib.error.HTTPError) -> str:
        body = error.read(100_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            detail = payload.get("error", payload)
            if isinstance(detail, dict):
                detail = detail.get("message", detail.get("code", "request rejected"))
            return str(detail)[:300]
        except json.JSONDecodeError:
            return body[:300] or str(error)

    @staticmethod
    def _profile(provider_type: str) -> dict[str, Any]:
        return next(profile for profile in PROVIDER_PROFILES if profile["key"] == provider_type)

    @staticmethod
    def _detected_mode(configured: str, modes: list[str]) -> str:
        if configured != "auto":
            return configured
        return "responses" if "responses" in modes else modes[0]

    @staticmethod
    def _serialize_provider(record: ModelProviderRecord) -> dict[str, Any]:
        parsed = urlparse(record.base_url)
        transport_warning = parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        return {
            "key": record.key,
            "name": record.name,
            "provider_type": record.provider_type,
            "base_url": record.base_url,
            "api_mode": record.api_mode,
            "default_model": record.default_model,
            "secret_reference": record.secret_reference,
            "has_secret": bool(record.secret_reference),
            "capabilities": record.capabilities,
            "available_models": record.available_models,
            "parameters": record.parameters,
            "enabled": record.enabled,
            "status": record.status,
            "source": record.source,
            "last_tested_at": record.last_tested_at.isoformat() if record.last_tested_at else None,
            "warnings": ["远程模型服务正在使用未加密 HTTP"] if transport_warning else [],
        }

    @staticmethod
    def _serialize_route(record: ModelRouteRecord) -> dict[str, Any]:
        return {
            "role": record.role,
            "provider_key": record.provider_key,
            "model_override": record.model_override,
            "parameter_overrides": record.parameter_overrides,
            "source": record.source,
            "updated_at": record.updated_at.isoformat(),
        }
