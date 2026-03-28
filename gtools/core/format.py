def format_timespan(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds:.2g}s"

    units = [
        ("y", 31_536_000),
        ("w", 604_800),
        ("d", 86_400),
        ("h", 3_600),
        ("m", 60),
        ("s", 1),
    ]

    parts = []
    remaining = seconds

    for suffix, size in units:
        value = int(remaining // size)
        if value:
            parts.append(f"{value}{suffix}")
            remaining -= value * size
        if len(parts) == 2:
            break

    return " ".join(parts) if parts else "0s"
