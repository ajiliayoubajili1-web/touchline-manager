"""Generic JSON-safe serialization for dataclass model graphs.

``dump`` converts any object graph of dataclasses, enums, dates, primitives,
lists, tuples and dicts into JSON-serializable data.

``load`` rebuilds that graph from plain data, using the field annotations of the
target dataclass. This gives every future model serialization for free, which
is what the structured save system is built on.
"""

from __future__ import annotations

import dataclasses
import typing
from datetime import date, datetime
from enum import Enum


def dump(obj):
    """Convert ``obj`` into a JSON-serializable structure."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            field.name: dump(getattr(obj, field.name))
            for field in dataclasses.fields(obj)
        }
    if isinstance(obj, dict):
        return {dump(key): dump(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [dump(item) for item in obj]
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    raise TypeError(f"cannot serialize {type(obj).__name__}: {obj!r}")


def load(target_type, data):
    """Rebuild an instance of ``target_type`` from plain ``data``."""
    if data is None:
        return None

    origin = typing.get_origin(target_type)
    args = typing.get_args(target_type)

    if origin is not None and args:
        if origin in (typing.Union,) or _is_union(origin):
            for arg in args:
                if arg is type(None):
                    continue
                return load(arg, data)
            raise ValueError(f"cannot load {data!r} as {target_type}")
        if origin is list:
            item_type = args[0] if args else None
            return [load(item_type, item) for item in data]
        if origin is dict:
            if not args:
                return {key: value for key, value in data.items()}
            key_type, value_type = args
            return {
                load(key_type, key): load(value_type, value)
                for key, value in data.items()
            }
        if origin is list and not args:
            return list(data)
        raise ValueError(f"unsupported generic {target_type!r}")

    if target_type is object:
        return data

    if isinstance(target_type, type):
        if issubclass(target_type, Enum):
            return target_type(data)
        if issubclass(target_type, (date, datetime)):
            return target_type.fromisoformat(data)
        if dataclasses.is_dataclass(target_type):
            hints = typing.get_type_hints(target_type)
            kwargs = {}
            for field in dataclasses.fields(target_type):
                if field.name not in data:
                    if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:
                        continue
                    raise ValueError(f"missing field {field.name} for {target_type.__name__}")
                kwargs[field.name] = load(hints[field.name], data[field.name])
            return target_type(**kwargs)
        if target_type in (str, int, float, bool):
            return target_type(data)
        if target_type is dict:
            return {key: value for key, value in data.items()}
        if target_type is list:
            return list(data)
        if target_type is tuple:
            return tuple(data)
        if target_type is bytes:
            return bytes(data)
        raise ValueError(f"unsupported scalar type {target_type}")

    raise ValueError(f"unsupported annotation {target_type!r}")


def _is_union(origin) -> bool:
    return hasattr(typing, "UnionType") and origin is typing.UnionType