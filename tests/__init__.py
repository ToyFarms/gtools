import json
import os
from pathlib import Path
import inspect
from typing import Protocol


SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
SNAPSHOT_DIR.mkdir(exist_ok=True)


class SupportsStr(Protocol):
    def __str__(self) -> str: ...


def verify(data: str | bytes | object, *, key: SupportsStr = "", name: SupportsStr | None = None) -> None:
    frame = inspect.currentframe().f_back  # pyright: ignore
    assert frame

    seen = frame.f_locals.get("_only_once_called")
    if seen is None:
        seen = set()
        frame.f_locals["_only_once_called"] = seen

    if key in seen:
        raise RuntimeError("verify() collision, use a unique key to avoid this")

    seen.add(key)

    frame = inspect.stack()[1]
    caller = frame.function if not name else str(name)

    name = f"{Path(frame.filename).stem}-{caller}{str(key)}"
    snapshot_file = SNAPSHOT_DIR / f"{name}.snap"
    output_file = SNAPSHOT_DIR / f"{name}.out"

    if isinstance(data, bytes):
        data = data.hex()
    elif isinstance(data, object):
        data = json.dumps(data, ensure_ascii=False)

    output_file.write_text(data, encoding="utf-8")

    if os.getenv("UPDATE") or not snapshot_file.exists():
        snapshot_file.write_text(data, encoding="utf-8")
        return

    expected = snapshot_file.read_text(encoding="utf-8")
    assert data == expected, f"snapshot mismatch {data=} != {expected=} ({output_file}, {snapshot_file})"
