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
    assert data == expected, f"snapshot mismatch {data=} != {expected=}"
