import json
import socket
from urllib.parse import urlparse, urlunparse
import urllib.request


def resolve_doh(hostname: str) -> list[str]:
    url = f"https://dns.google/resolve?name={hostname}&type=A"
    req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read().decode())

    ips = []
    for ans in data.get("Answer", []):
        if ans.get("type") == 1:
            ips.append(ans.get("data"))

    return ips


def is_up(host, port=80, timeout=2):
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except Exception:
        return False


def increment_port(url: str) -> str:
    parsed = urlparse(url)

    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("invalid URL")

    new_port = (parsed.port or 0) + 1

    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]:{new_port}"
    else:
        netloc = f"{hostname}:{new_port}"

    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        netloc = f"{auth}@{netloc}"

    return urlunparse(parsed._replace(netloc=netloc))
