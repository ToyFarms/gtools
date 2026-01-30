from ast import List
from ctypes import Union
from dataclasses import dataclass, fields, is_dataclass, asdict
from typing import Any, Callable, get_type_hints, get_origin, get_args
import json
from pathlib import Path
from datetime import datetime, date
from enum import Enum


type Serializer = Callable[[Any], Any]
type Deserializer = Callable[[Any], Any]


class JsonMixin:
    _CODECS: dict[type, tuple[Serializer, Deserializer]] = {
        Path: (str, Path),
    }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # pyright: ignore[reportArgumentType]

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=self._json_serializer)

    def to_json_file(self, filepath: str | Path, indent: int = 2) -> None:
        filepath = Path(filepath)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=indent, default=self._json_serializer)

    @staticmethod
    def _coerce_value(field_type: type, value: Any) -> Any:
        origin = get_origin(field_type)

        # Optional[T] or Union[T, None]
        if origin is Union:
            for arg in get_args(field_type):
                if arg is type(None):
                    continue
                try:
                    return JsonMixin._coerce_value(arg, value)
                except Exception:
                    pass
            return value

        codec = JsonMixin._CODECS.get(field_type)
        if codec and isinstance(value, str):
            _, deser = codec
            return deser(value)

        return value

    @classmethod
    def from_dict[T: JsonMixin](cls: type[T], data: dict[str, Any]) -> T:
        if not is_dataclass(cls):
            raise TypeError(f"{cls.__name__} must be a dataclass")

        type_hints = get_type_hints(cls)
        field_values = {}

        for field in fields(cls):
            if field.name not in data:
                if field.default is not field.default_factory:
                    continue
                if field.default_factory is not dataclass.MISSING:  # type: ignore
                    continue
                raise ValueError(f"missing required field: {field.name}")

            value = data[field.name]
            field_type = type_hints.get(field.name, field.type)

            value = JsonMixin._coerce_value(field_type, value)
            if is_dataclass(field_type) and isinstance(value, dict):
                value = field_type.from_dict(value)  # pyright: ignore[reportAttributeAccessIssue]

            elif get_origin(field_type) in (list, List):
                args = get_args(field_type)
                if args and is_dataclass(args[0]) and isinstance(value, list):
                    value = [args[0].from_dict(item) if isinstance(item, dict) else item for item in value]  # pyright: ignore[reportAttributeAccessIssue]
            elif get_origin(field_type) is Union:
                args = get_args(field_type)
                for arg in args:
                    if is_dataclass(arg) and isinstance(value, dict):
                        value = arg.from_dict(value)  # pyright: ignore[reportAttributeAccessIssue]
                        break

            field_values[field.name] = value

        return cls(**field_values)

    @classmethod
    def from_json[T: JsonMixin](cls: type[T], json_str: str) -> T:
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_json_file[T: JsonMixin](cls: type[T], filepath: str | Path) -> T:
        filepath = Path(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        for typ, (ser, _) in JsonMixin._CODECS.items():
            if isinstance(obj, typ):
                return ser(obj)

        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, Enum):
            return obj.value
        elif is_dataclass(obj):
            return asdict(obj)  # pyright: ignore[reportArgumentType]
        elif hasattr(obj, "__dict__"):
            return obj.__dict__
        raise TypeError(f"object of type {type(obj).__name__} is not JSON serializable")
