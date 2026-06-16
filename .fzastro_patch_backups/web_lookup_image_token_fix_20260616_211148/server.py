from __future__ import annotations

import json
import os
import time
from datetime import datetime
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from ..config import (
    APP_DIR,
    APP_NAME,
    APP_VERSION,
    APP_VERSION_LABEL,
    BASE_URL,
    DAILY_NEWS_CACHE_FILE,
    DEFAULT_MODEL_NAME,
    RUNTIME_CHAT_TIMEOUT_SECONDS,
)
from ..logging_utils import log_exception, log_warning
from ..runtime import (
    format_runtime_model_unavailable_message,
    is_local_ollama_base_url,
    is_ollama_base_url,
    is_ollama_server_available,
    is_runtime_connection_error,
    is_runtime_model_not_found_error,
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
    should_auto_start_ollama,
    start_ollama_server_if_available,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_WEB_HOST = os.environ.get("FZASTRO_WEB_HOST", "127.0.0.1")
DEFAULT_WEB_PORT = int(os.environ.get("FZASTRO_WEB_PORT", "7860"))


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str


class ChatRequest(BaseModel):
    prompt: str | None = None
    messages: list[ChatMessage] | None = None
    model: str = Field(default=DEFAULT_MODEL_NAME, min_length=1)
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    think_enabled: bool = True
    num_predict: int = Field(default=4096, ge=64, le=32768)
    stream_reasoning: bool = False


class AstroLookupRequest(BaseModel):
    query: str = Field(min_length=1)
    with_image: bool = False
    fov_deg: float = Field(default=2.337, gt=0.0, le=20.0)


class AstroLocationRequest(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    elev: float = 0.0
    tz: str | None = None


class SiteResolveRequest(AstroLocationRequest):
    pass


class SeeingRequest(AstroLocationRequest):
    nights: int = Field(default=4, ge=1, le=4)


class TargetsRequest(AstroLocationRequest):
    date: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    min_alt: float = Field(default=45.0, ge=0.0, le=89.0)


def _web_token() -> str:
    return str(os.environ.get("FZASTRO_WEB_TOKEN", "")).strip()


def _public_network_enabled() -> bool:
    value = str(os.environ.get("FZASTRO_WEB_ALLOW_LAN", "0")).strip().casefold()
    return value in {"1", "true", "yes", "on"}


def _request_token(request: Any) -> str:
    auth_header = str(request.headers.get("authorization", "")).strip()

    if auth_header.casefold().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()

    return str(request.headers.get("x-fzastro-token", "")).strip()


def _model_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()

    return value.dict()


def _messages_from_request(payload: ChatRequest) -> list[dict[str, str]]:
    if payload.messages:
        return [_model_to_dict(message) for message in payload.messages]

    clean_prompt = str(payload.prompt or "").strip()

    if not clean_prompt:
        raise ValueError("No prompt or messages were provided.")

    return [{"role": "user", "content": clean_prompt}]


def _reasoning_from_delta(delta: Any, delta_data: dict[str, Any]) -> str:
    reasoning = (
        getattr(delta, "thinking", None)
        or getattr(delta, "reasoning", None)
        or getattr(delta, "reasoning_content", None)
    )

    if not reasoning:
        reasoning = (
            delta_data.get("thinking")
            or delta_data.get("reasoning")
            or delta_data.get("reasoning_content")
        )

    delta_extra = getattr(delta, "model_extra", None)

    if not reasoning and isinstance(delta_extra, dict):
        reasoning = (
            delta_extra.get("thinking")
            or delta_extra.get("reasoning")
            or delta_extra.get("reasoning_content")
        )

    return str(reasoning or "")


def _chat_request_params(payload: ChatRequest, *, stream: bool) -> dict[str, Any]:
    base_url = normalize_runtime_base_url(payload.base_url)
    request_params: dict[str, Any] = {
        "model": str(payload.model or DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME,
        "messages": _messages_from_request(payload),
        "temperature": float(payload.temperature),
        "top_p": float(payload.top_p),
        "presence_penalty": 0.2,
        "stream": bool(stream),
    }

    if is_ollama_base_url(base_url):
        request_params["extra_body"] = {
            "think": bool(payload.think_enabled),
            "top_k": 20,
            "options": {
                "num_predict": int(payload.num_predict),
                "repeat_penalty": 1.08,
                "repeat_last_n": 64,
            },
        }

    return request_params


def _runtime_client_for(payload: ChatRequest):
    return make_runtime_client(
        payload.base_url,
        payload.api_key,
        timeout=RUNTIME_CHAT_TIMEOUT_SECONDS,
    )


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _serialize_astro_result(result: Any) -> dict[str, Any]:
    try:
        data = asdict(result)
    except TypeError:
        data = {
            "title": getattr(result, "title", "Astro tool"),
            "text": getattr(result, "text", str(result)),
            "files": getattr(result, "files", []),
            "success": bool(getattr(result, "success", True)),
            "source": getattr(result, "source", "Astro Tools"),
            "metadata": getattr(result, "metadata", {}),
        }

    data["files"] = [str(path) for path in data.get("files") or []]
    data["metadata"] = data.get("metadata") or {}
    return data


def _maybe_start_local_ollama(base_url: str) -> dict[str, Any]:
    if not is_local_ollama_base_url(base_url):
        return {"attempted": False, "available": False, "message": "not local Ollama"}

    if is_ollama_server_available(base_url, timeout=0.8):
        return {"attempted": False, "available": True, "message": "Ollama is running."}

    if not should_auto_start_ollama():
        return {
            "attempted": False,
            "available": False,
            "message": "Ollama is not running and auto-start is disabled.",
        }

    result = start_ollama_server_if_available(base_url, wait_seconds=8.0)
    return {
        "attempted": bool(result.attempted_start),
        "available": bool(result.available),
        "status": result.status,
        "message": result.message,
        "executable": result.executable,
    }



_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_asset_path(raw_path: str) -> Path:
    candidate = Path(str(raw_path or "")).expanduser().resolve()
    allowed_roots = [
        Path(APP_DIR).resolve(),
        Path(__file__).resolve().parents[2],
    ]

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    if candidate.suffix.casefold() not in _IMAGE_SUFFIXES:
        raise HTTPException(status_code=403, detail="Only image assets can be served.")

    if not any(_is_relative_to(candidate, root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="File is outside allowed FZAstro folders.")

    return candidate


def _source_sections_from_news_context(context: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    item: dict[str, str] | None = None

    def commit_item() -> None:
        nonlocal item
        if current is not None and item and item.get("title"):
            current.setdefault("items", []).append(item)
        item = None

    for raw_line in str(context or "").splitlines():
        line = raw_line.strip()
        if not line or line == "[NEWS HEADLINES]":
            continue
        if line.upper() == line and not line.startswith("-") and len(line) <= 64:
            commit_item()
            current = {"name": line.title(), "items": []}
            sections.append(current)
            continue
        if line.startswith("- "):
            commit_item()
            item = {"title": line[2:].strip()}
            continue
        if item is None:
            continue
        if line.startswith("SourceID:"):
            item["source_id"] = line.replace("SourceID:", "", 1).strip()
        elif line.startswith("SourceName:"):
            item["source_name"] = line.replace("SourceName:", "", 1).strip()
        elif line.startswith("SourceURL:"):
            item["url"] = line.replace("SourceURL:", "", 1).strip()
        elif line.startswith("Summary:"):
            item["summary"] = line.replace("Summary:", "", 1).strip()
    commit_item()
    return sections

def _create_app_impl():
    async def require_token(
        request: Request, x_fzastro_token: str | None = Header(None)
    ):
        expected = _web_token()

        if not expected:
            return True

        provided = x_fzastro_token or _request_token(request)

        if provided != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing FZAstro web token.",
            )

        return True

    app = FastAPI(
        title="FZAstro AI Web Companion",
        version="0.1.0",
        description="Local browser companion for FZAstro AI desktop engine.",
    )

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")


    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        icon_path = Path(__file__).resolve().parents[2] / "favicon.ico"
        if icon_path.exists():
            return FileResponse(icon_path)
        raise HTTPException(status_code=404, detail="favicon not found")

    @app.get("/api/assets/file", dependencies=[Depends(require_token)], include_in_schema=False)
    async def asset_file(path: str):
        return FileResponse(_allowed_asset_path(path))

    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "app": APP_NAME,
            "version": APP_VERSION,
            "label": APP_VERSION_LABEL,
            "web_companion": "0.1.0",
            "auth_required": bool(_web_token()),
            "lan_enabled": _public_network_enabled(),
            "time": int(time.time()),
        }

    @app.get("/api/status", dependencies=[Depends(require_token)])
    async def status_endpoint():
        base_url = normalize_runtime_base_url(BASE_URL)
        ollama_available = is_ollama_server_available(base_url, timeout=0.8)
        return {
            "app": APP_NAME,
            "label": APP_VERSION_LABEL,
            "default_model": DEFAULT_MODEL_NAME,
            "base_url": base_url,
            "local_ollama": is_local_ollama_base_url(base_url),
            "ollama_available": ollama_available,
            "auth_required": bool(_web_token()),
            "lan_enabled": _public_network_enabled(),
        }

    @app.get("/api/models", dependencies=[Depends(require_token)])
    async def models_endpoint(base_url: str | None = None, api_key: str | None = None):
        clean_base_url = normalize_runtime_base_url(base_url)
        _maybe_start_local_ollama(clean_base_url)

        try:
            client = make_runtime_client(clean_base_url, api_key, timeout=12.0)
            response = await run_in_threadpool(client.models.list)
            models = sorted(
                {str(model.id).strip() for model in response.data if model.id},
                key=str.casefold,
            )
            return {"models": models or [DEFAULT_MODEL_NAME]}
        except Exception as exc:
            if is_runtime_connection_error(exc):
                log_warning("Web companion model discovery provider unavailable", exc)
                return JSONResponse(
                    status_code=503,
                    content={
                        "models": [DEFAULT_MODEL_NAME],
                        "error": (
                            "Model provider unavailable. Start Ollama or check "
                            "the runtime URL."
                        ),
                    },
                )

            log_exception("Web companion model discovery failed", exc)
            return JSONResponse(
                status_code=500,
                content={"models": [DEFAULT_MODEL_NAME], "error": str(exc)},
            )

    @app.post("/api/chat", dependencies=[Depends(require_token)])
    async def chat_endpoint(payload: ChatRequest):
        clean_base_url = normalize_runtime_base_url(payload.base_url)
        _maybe_start_local_ollama(clean_base_url)

        try:
            client = _runtime_client_for(payload)
            response = await run_in_threadpool(
                client.chat.completions.create,
                **_chat_request_params(payload, stream=False),
            )
            content = response.choices[0].message.content if response.choices else ""
            return {"text": content or "", "model": payload.model}
        except Exception as exc:
            if is_runtime_model_not_found_error(exc):
                raise HTTPException(
                    status_code=404,
                    detail=format_runtime_model_unavailable_message(
                        payload.model, payload.base_url
                    ),
                ) from exc

            if is_runtime_connection_error(exc):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Model provider unavailable. Start Ollama or check "
                        "the runtime URL."
                    ),
                ) from exc

            log_exception("Web companion chat failed", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/chat/stream", dependencies=[Depends(require_token)])
    async def chat_stream_endpoint(payload: ChatRequest):
        def generate() -> Iterable[str]:
            clean_base_url = normalize_runtime_base_url(payload.base_url)
            start_info = _maybe_start_local_ollama(clean_base_url)
            yield _sse("status", {"message": start_info.get("message", "Starting")})

            full_text = ""
            reasoning_text = ""

            try:
                client = _runtime_client_for(payload)
                stream = client.chat.completions.create(
                    **_chat_request_params(payload, stream=True)
                )

                for chunk in stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    try:
                        delta_data = delta.model_dump()
                    except Exception:
                        delta_data = {}

                    reasoning = _reasoning_from_delta(delta, delta_data)
                    content = getattr(delta, "content", None) or delta_data.get(
                        "content"
                    )

                    if reasoning:
                        reasoning_text += reasoning
                        if payload.stream_reasoning:
                            yield _sse("reasoning", {"text": reasoning})

                    if content:
                        full_text += str(content)
                        yield _sse("token", {"text": str(content)})

                yield _sse(
                    "done",
                    {
                        "text": full_text,
                        "reasoning_chars": len(reasoning_text),
                        "model": payload.model,
                    },
                )
            except Exception as exc:
                if is_runtime_model_not_found_error(exc):
                    message = format_runtime_model_unavailable_message(
                        payload.model, payload.base_url
                    )
                elif is_runtime_connection_error(exc):
                    message = (
                        "Model provider unavailable. Start Ollama or check "
                        "the runtime URL."
                    )
                else:
                    log_exception("Web companion streaming chat failed", exc)
                    message = str(exc)

                yield _sse("error", {"message": message})

        return StreamingResponse(generate(), media_type="text/event-stream")





    @app.post("/api/location/resolve", dependencies=[Depends(require_token)])
    async def location_resolve_endpoint(payload: SiteResolveRequest):
        from ..astro_tools.engine import _resolve_timezone

        lat = max(-90.0, min(90.0, float(payload.lat)))
        lon = max(-180.0, min(180.0, float(payload.lon)))
        fallback_tz = str(payload.tz or "").strip() or "UTC"
        timezone_name = _resolve_timezone(lat, lon, fallback_tz)

        try:
            local_time = datetime.now(ZoneInfo(timezone_name)).strftime(
                "%Y-%m-%d %H:%M"
            )
        except Exception:
            timezone_name = "UTC"
            local_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        return {
            "lat": lat,
            "lon": lon,
            "elev": float(payload.elev or 0.0),
            "timezone": timezone_name,
            "local_time": local_time,
        }

    @app.get("/api/news/daily", dependencies=[Depends(require_token)])
    async def daily_news_endpoint(refresh: bool = False):
        from ..news_tools import (
            build_deterministic_daily_news_brief,
            parse_news_sources,
            perform_daily_news_search,
        )

        if refresh:
            try:
                DAILY_NEWS_CACHE_FILE.unlink(missing_ok=True)
            except Exception as exc:
                log_warning("Web companion daily news cache refresh failed", exc)

        try:
            context = await run_in_threadpool(perform_daily_news_search)
            brief = build_deterministic_daily_news_brief(context)
            return {
                "title": "Daily News Brief",
                "brief": brief,
                "sources": parse_news_sources(context),
                "sections": _source_sections_from_news_context(context),
                "generated_at": int(time.time()),
            }
        except Exception as exc:
            log_exception("Web companion daily news failed", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/astro/tools", dependencies=[Depends(require_token)])
    async def astro_tools_endpoint():
        return {
            "tools": [
                {
                    "id": "lookup",
                    "name": "LOOKUP",
                    "description": (
                        "Resolve an astronomy object and return coordinates/details."
                    ),
                },
                {
                    "id": "seeing",
                    "name": "SEEING / Astro Night Planner",
                    "description": (
                        "Forecast cloud, moon, darkness, wind, and imaging score."
                    ),
                },
                {
                    "id": "targets",
                    "name": "TARGETS",
                    "description": (
                        "Find astrophotography targets for a location and date."
                    ),
                },
            ]
        }

    @app.post("/api/astro/lookup", dependencies=[Depends(require_token)])
    async def astro_lookup_endpoint(payload: AstroLookupRequest):
        from ..astro_tools.engine import lookup_object

        result = await run_in_threadpool(
            lookup_object,
            payload.query,
            with_image=payload.with_image,
            fov_deg=payload.fov_deg,
        )
        return _serialize_astro_result(result)

    @app.post("/api/astro/seeing", dependencies=[Depends(require_token)])
    async def astro_seeing_endpoint(payload: SeeingRequest):
        from ..astro_tools.engine import observing_forecast

        result = await run_in_threadpool(
            observing_forecast,
            payload.lat,
            payload.lon,
            elev=payload.elev,
            tz=payload.tz,
            nights=payload.nights,
        )
        return _serialize_astro_result(result)

    @app.post("/api/astro/targets", dependencies=[Depends(require_token)])
    async def astro_targets_endpoint(payload: TargetsRequest):
        from ..astro_tools.engine import best_targets

        result = await run_in_threadpool(
            best_targets,
            payload.lat,
            payload.lon,
            elev=payload.elev,
            date=payload.date,
            limit=payload.limit,
            min_alt=payload.min_alt,
            tz=payload.tz,
        )
        return _serialize_astro_result(result)

    return app


def create_app():
    return _create_app_impl()


app = create_app()
