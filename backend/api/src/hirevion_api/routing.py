"""Route conventions: `/api/v1`, readable operation ids, problem responses in the OpenAPI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from hirevion_api.problems import PROBLEM_MEDIA_TYPE, Problem

API_PREFIX = "/api/v1"
_PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}
_ERROR_RESPONSES = {
    "4XX": "Client error, as an RFC 9457 problem",
    "5XX": "Server error, as an RFC 9457 problem",
}


def operation_id(route: APIRoute) -> str:
    """The route function's name (`get_liveness`), which the TypeScript client exposes."""
    return route.name


def api_router(**kwargs: Any) -> APIRouter:
    return APIRouter(prefix=API_PREFIX, **kwargs)


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """FastAPI's document, with every operation's errors described as problems."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, description=app.description, routes=app.routes
    )
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    schemas["Problem"] = Problem.model_json_schema()
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            responses = operation.setdefault("responses", {})
            responses.pop("422", None)  # validation errors are problems too (covered by 4XX)
            for status, description in _ERROR_RESPONSES.items():
                responses[status] = {
                    "description": description,
                    "content": {PROBLEM_MEDIA_TYPE: {"schema": _PROBLEM_REF}},
                }
    for unused in ("HTTPValidationError", "ValidationError"):
        schemas.pop(unused, None)
    app.openapi_schema = schema
    return schema
