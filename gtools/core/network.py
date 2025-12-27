import json
import socket
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
