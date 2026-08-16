# -*- coding: utf-8 -*-
"""在模型输出进入业务决策前执行共享 Schema 校验。"""
from __future__ import annotations

import math
from typing import Any


class ModelResponseValidationError(ValueError):
    """模型结构化输出不满足当前场景契约。"""


def provider_response_schema(schema: Any) -> Any:
    """移除供应商不接受的提示约束，完整契约仍用于本地强校验。"""
    if isinstance(schema, dict):
        return {
            key: provider_response_schema(value)
            for key, value in schema.items()
            if key not in {"minItems", "maxItems"}
        }
    if isinstance(schema, list):
        return [provider_response_schema(value) for value in schema]
    return schema


def _error(path: str, message: str) -> ModelResponseValidationError:
    return ModelResponseValidationError(f"{path}: {message}")


def _validate(value: Any, schema: dict[str, Any], path: str) -> Any:
    if value is None:
        if schema.get("nullable") is True:
            return None
        raise _error(path, "不允许 null")

    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise _error(path, "必须是 object")
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                raise _error(f"{path}.{key}", "缺少必填字段")
        return {
            key: _validate(value[key], child_schema, f"{path}.{key}")
            for key, child_schema in properties.items()
            if key in value
        }

    if expected == "array":
        if not isinstance(value, list):
            raise _error(path, "必须是 array")
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and len(value) < int(minimum):
            raise _error(path, f"少于 minItems={minimum}")
        if maximum is not None and len(value) > int(maximum):
            raise _error(path, f"超过 maxItems={maximum}")
        item_schema = schema.get("items") or {}
        return [
            _validate(item, item_schema, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]

    if expected == "string":
        if not isinstance(value, str):
            raise _error(path, "必须是 string")
    elif expected == "boolean":
        if type(value) is not bool:
            raise _error(path, "必须是 boolean")
    elif expected == "integer":
        if type(value) is not int:
            raise _error(path, "必须是 integer")
    elif expected == "number":
        if type(value) not in {int, float} or not math.isfinite(float(value)):
            raise _error(path, "必须是有限 number")

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise _error(path, f"不在允许枚举 {enum} 中")
    return value


def validate_model_response(value: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """严格校验必填项、类型和枚举，并移除 Schema 外字段。"""
    validated = _validate(value, schema, "$")
    if not isinstance(validated, dict):
        raise _error("$", "顶层必须是 object")
    return validated


__all__ = [
    "ModelResponseValidationError",
    "provider_response_schema",
    "validate_model_response",
]
