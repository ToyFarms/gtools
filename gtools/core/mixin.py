import json
from dataclasses import fields, is_dataclass, asdict, MISSING
from typing import Any, Callable, get_type_hints, get_origin, get_args, Union
from pathlib import Path
from datetime import datetime, date
from enum import Enum

type Serializer = Callable[[Any], Any]
type Deserializer = Callable[[Any], Any]


class JsonMixin:
    _CODECS: dict[type, tuple[Serializer, Deserializer]] = {
        Path: (str, Path),
        datetime: (
            lambda dt: dt.isoformat(),
            lambda s: datetime.fromisoformat(s),
        ),
        date: (
            lambda d: d.isoformat(),
            lambda s: date.fromisoformat(s),
        ),
        bytes: (
            lambda b: b.decode("utf-8"),
            lambda s: s.encode("utf-8"),
        ),
        int: (int, lambda v: int(v) if not isinstance(v, bool) else v),
        float: (float, float),
        bool: (bool, bool),
        str: (str, str),
    }

    @staticmethod
    def _convert_by_type(field_type: type, value: Any) -> Any:
        origin = get_origin(field_type)

        # Optional[T] / Union[T, None]
        if origin is Union:
            for arg in get_args(field_type):
                if arg is type(None):
                    continue
                try:
                    return JsonMixin._convert_by_type(arg, value)
                except Exception:
                    pass
            return value

        # list[T]
        if origin is list and isinstance(value, list):
            args = get_args(field_type)
            if args:
                (item_type,) = args
                return [JsonMixin._convert_by_type(item_type, v) for v in value]
            return value

        # nested dataclass
        if is_dataclass(field_type) and isinstance(value, dict):
            return field_type.from_dict(value)  # pyright: ignore

        if isinstance(field_type, type) and issubclass(field_type, Enum):
            return field_type(value)

        codec = JsonMixin._CODECS.get(field_type)
        if codec:
            _, deser = codec
            return deser(value)

        return value

    @classmethod
    def convert_field_value(cls, field_name: str, value: Any) -> Any:
        type_hints = get_type_hints(cls)
        field_type = type_hints.get(field_name)
        if field_type is None:
            return value

        return cls._convert_by_type(field_type, value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # pyright: ignore[reportArgumentType]

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=self._json_serializer)

    def to_json_file(self, filepath: str | Path, indent: int = 2) -> None:
        filepath = Path(filepath)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=indent, default=self._json_serializer)

    @classmethod
    def from_dict[T: "JsonMixin"](cls: type[T], data: dict[str, Any]) -> T:
        if not is_dataclass(cls):
            raise TypeError(f"{cls.__name__} must be a dataclass")

        field_values = {}
        for f in fields(cls):
            if f.name not in data:
                if f.default is not MISSING:
                    field_values[f.name] = f.default
                elif f.default_factory is not MISSING:
                    field_values[f.name] = f.default_factory()
                else:
                    raise ValueError(f"missing required field: {f.name}")
                continue
            field_values[f.name] = cls.convert_field_value(f.name, data[f.name])

        return cls(**field_values)

    @classmethod
    def from_json[T: "JsonMixin"](cls: type[T], json_str: str) -> T:
        data = json.loads(json_str)

        return cls.from_dict(data)

    @classmethod
    def from_json_file[T: "JsonMixin"](cls: type[T], filepath: str | Path) -> T:
        filepath = Path(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        return cls.from_dict(data)

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)

        if isinstance(obj, Enum):
            return obj.value

        for typ, (ser, _) in JsonMixin._CODECS.items():
            try:
                if isinstance(obj, typ):
                    return ser(obj)
            except TypeError:
                pass

        if isinstance(obj, dict):
            return {k: JsonMixin._json_serializer(v) for k, v in obj.items()}

        if isinstance(obj, (list, tuple, set)):
            return [JsonMixin._json_serializer(v) for v in obj]

        raise TypeError(f"object of type {type(obj).__name__} is not JSON serializable")
