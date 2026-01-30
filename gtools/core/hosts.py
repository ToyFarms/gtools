from copy import deepcopy
import io
import platform
from pathlib import Path
from dataclasses import dataclass
import shutil
from typing import Optional
import ipaddress
from collections import Counter


@dataclass
class HostEntry:
    ip: str
    hostnames: list[str]
    comment: str = ""
    disabled: bool = False

    def render(self) -> str:
        base = f"{self.ip}\t{' '.join(self.hostnames)}"
        if self.comment:
            base += f"\t# {self.comment}"
        return f"# {base}" if self.disabled else base

    def __repr__(self) -> str:
        hostnames_str = " ".join(self.hostnames)
        if self.disabled:
            return f"{self.ip} {hostnames_str} (disabled)"
        return f"{self.ip} {hostnames_str}"


@dataclass
class ParsedLine:
    raw: str
    entry: Optional[HostEntry] = None
    dirty: bool = False


class HostsFileManager:
    def __init__(self, hosts_path: Path | str | None = None):
        self.hosts_path = Path(hosts_path) if hosts_path else self._get_default_hosts_path()

    def _get_default_hosts_path(self) -> Path:
        system = platform.system()
        if system == "Windows":
            return Path(r"C:\Windows\System32\drivers\etc\hosts")
        if system in {"Darwin", "Linux"}:
            return Path("/etc/hosts")

        raise RuntimeError(f"unsupported operating system: {system}")

    def _read_lines(self) -> list[str]:
        with open(self.hosts_path, "r", encoding="utf-8") as f:
            return f.readlines()

    def serialize(self, parsed: list[ParsedLine], reset: bool = True) -> str:
        x = io.StringIO()
        for p in parsed:
            if p.dirty and p.entry:
                x.write(p.entry.render() + "\n")
            else:
                x.write(p.raw)
            if reset:
                p.dirty = False

        return x.getvalue()

    def __repr__(self) -> str:
        return self.serialize(self._parse())

    def _write_parsed(self, parsed: list[ParsedLine]) -> None:
        with open(self.hosts_path, "w", encoding="utf-8") as f:
            f.write(self.serialize(parsed))

    @staticmethod
    def _validate_ip(ip: str) -> bool:
        try:
            ipaddress.ip_address(ip)
            return True
        except Exception:
            return False

    def _parse(self) -> list[ParsedLine]:
        parsed: list[ParsedLine] = []
        for raw in self._read_lines():
            stripped = raw.lstrip()
            if not stripped or stripped.startswith("##"):
                parsed.append(ParsedLine(raw=raw))
                continue

            disabled = stripped.startswith("#")
            content = stripped[1:].lstrip() if disabled else stripped

            parts = content.split("#", 1)
            tokens = parts[0].split()
            if len(tokens) < 2:
                parsed.append(ParsedLine(raw=raw))
                continue

            if not self._validate_ip(tokens[0]):
                parsed.append(ParsedLine(raw=raw))
                continue

            comment = parts[1].strip() if len(parts) > 1 else ""

            hostnames = tokens[1:]
            entry = HostEntry(tokens[0], hostnames, comment, disabled)
            parsed.append(ParsedLine(raw=raw, entry=entry))

        return parsed

    def get_all(self) -> list[HostEntry]:
        return [p.entry for p in self._parse() if p.entry and not p.entry.disabled]

    def get(self, hostname: str | list[str], include_disabled: bool = False) -> HostEntry | None:
        disabled: HostEntry | None = None
        enabled: HostEntry | None = None
        for p in self._parse():
            if not p.entry:
                continue
            if not self.entry_equal(p.entry, hostname, include_disabled):
                continue

            if p.entry.disabled:
                disabled = p.entry
            else:
                enabled = p.entry

        return enabled if enabled else disabled if disabled and include_disabled else None

    def get_by_ip(self, ip: str, include_commented: bool = False) -> HostEntry | None:
        for p in self._parse():
            if not p.entry:
                continue
            if p.entry.ip != ip:
                continue
            if p.entry.disabled and not include_commented:
                continue
            return p.entry

        return None

    def add(self, ip: str, hostnames: str | list[str], comment: str = "", insert_after_hostname: str | list[str] | None = None) -> HostEntry:
        if not self._validate_ip(ip):
            raise ValueError(f"invalid IP address: {ip}")

        if isinstance(hostnames, str):
            hostnames = [hostnames]

        if not hostnames:
            raise ValueError("at least one hostname must be provided")

        for hostname in hostnames:
            if self.get(hostname):
                raise KeyError(f"entry already exists for '{hostname}'")

        parsed = self._parse()
        anchor = None
        if insert_after_hostname:
            for i, p in enumerate(parsed):
                if p.entry and any(self.entry_equal(p.entry, x, include_disabled=True) for x in insert_after_hostname):
                    anchor = i + 1
                    break

        entry = HostEntry(ip, hostnames, comment, disabled=False)
        new_pl = ParsedLine(raw="", entry=entry, dirty=True)
        if anchor:
            parsed.insert(anchor, new_pl)
        else:
            parsed.append(new_pl)

        self._write_parsed(parsed)

        return entry

    def remove(self, hostname: str | list[str]) -> HostEntry:
        parsed = self._parse()
        removed = None
        out: list[ParsedLine] = []
        for p in parsed:
            if p.entry and self.entry_equal(p.entry, hostname):
                removed = p.entry
                continue
            out.append(p)
        if not removed:
            raise KeyError(f"no active entry found for hostname: {hostname}")

        self._write_parsed(out)

        return removed

    def remove_hostname(self, hostname: str) -> HostEntry:
        parsed = self._parse()
        for p in parsed:
            if p.entry and not p.entry.disabled and hostname in p.entry.hostnames:
                if len(p.entry.hostnames) == 1:
                    return self.remove(hostname)
                else:
                    p.entry.hostnames.remove(hostname)
                    p.dirty = True
                    self._write_parsed(parsed)
                    return p.entry

        raise KeyError(f"no active entry found for hostname: {hostname}")

    def add_hostname(self, ip: str, hostname: str) -> HostEntry:
        if not self._validate_ip(ip):
            raise ValueError(f"invalid IP address: {ip}")

        existing = self.get(hostname)
        if existing:
            raise KeyError(f"hostname '{hostname}' already exists for IP {existing.ip}")

        parsed = self._parse()
        for p in parsed:
            if p.entry and not p.entry.disabled and p.entry.ip == ip:
                p.entry.hostnames.append(hostname)
                p.dirty = True
                self._write_parsed(parsed)
                return p.entry

        return self.add(ip, hostname)

    def exists(self, hostname: str | list[str], include_disabled: bool = False) -> bool:
        for p in self._parse():
            if p.entry and self.entry_equal(p.entry, hostname, include_disabled):
                return True

        return False

    def entry_equal(self, entry: HostEntry, hostname: str | list[str], include_disabled: bool = False) -> bool:
        if isinstance(hostname, str):
            return (include_disabled or not entry.disabled) and hostname in entry.hostnames
        else:
            return (include_disabled or not entry.disabled) and Counter(hostname) == Counter(entry.hostnames)

    def disable(self, hostname: str | list[str]) -> HostEntry:
        parsed = self._parse()
        for p in parsed:
            if p.entry and self.entry_equal(p.entry, hostname, include_disabled=True):
                p.entry.disabled = True
                p.dirty = True
                self._write_parsed(parsed)
                return p.entry

        raise KeyError(f"no active entry found for hostname: {hostname}")

    def enable(self, hostname: str | list[str]) -> HostEntry:
        parsed = self._parse()
        for p in parsed:
            if p.entry and self.entry_equal(p.entry, hostname, include_disabled=True):
                p.entry.disabled = False
                p.dirty = True
                self._write_parsed(parsed)
                return p.entry

        raise KeyError(f"no disabled entry found for hostname: {hostname}")

    def comment_line(self, line: ParsedLine) -> ParsedLine:
        if not line.entry:
            raise ValueError("entry is None")

        commented = deepcopy(line)
        assert commented.entry
        commented.entry.disabled = True
        commented.dirty = True

        return commented

    def split_hostname(self, ip: str | None, hostname: str, include_disabled: bool = False) -> None:
        parsed = self._parse()
        new: list[ParsedLine] = []
        any_changed = False
        for p in parsed:
            if p.entry and self.entry_equal(p.entry, hostname, include_disabled):
                any_changed = True
                new.extend(self._split_hostname(p, ip, hostname))
            else:
                new.append(p)

        if any_changed:
            self._write_parsed(new)

    def _split_hostname(self, line: ParsedLine, ip: str | None, hostname: str) -> list[ParsedLine]:
        """if an ip contains multiple hostname, this will split 'hostname' into its own line"""
        if not line.entry:
            raise ValueError("entry is None")

        new_hosts = [x for x in line.entry.hostnames if x != hostname]
        if new_hosts:
            line.entry.hostnames = new_hosts
            line.dirty = True
            return [line, ParsedLine(raw="", entry=HostEntry(ip if ip else line.entry.ip, [hostname]), dirty=True)]
        else:
            return [line]

    def replace(self, ip: str, hostname: str | list[str], keep_original: bool = False) -> None:
        parsed = self._parse()
        new: list[ParsedLine] = []
        any_changed = False
        for p in parsed:
            if isinstance(hostname, str):
                if p.entry and not p.entry.disabled and hostname in p.entry.hostnames:
                    if len(p.entry.hostnames) > 1:
                        if keep_original:
                            new.append(self.comment_line(p))

                        new.extend(self._split_hostname(p, ip, hostname))
                        any_changed = True
                    else:
                        if keep_original:
                            new.append(self.comment_line(p))

                        p.entry.ip = ip
                        p.dirty = True
                        new.append(p)
                        any_changed = True
                else:
                    new.append(p)
            else:
                if p.entry and not p.entry.disabled and Counter(hostname) == Counter(p.entry.hostnames):
                    if keep_original:
                        new.append(self.comment_line(p))

                    p.entry.ip = ip
                    p.dirty = True
                    new.append(p)
                    any_changed = True
                else:
                    new.append(p)

        if any_changed:
            self._write_parsed(new)

    def backup(self) -> Path:
        dst = self.hosts_path.with_suffix(self.hosts_path.suffix + ".bak")
        shutil.copy2(self.hosts_path, dst)

        return dst

    def restore(self) -> Path:
        dst = self.hosts_path.with_suffix(self.hosts_path.suffix + ".bak")
        if not dst.exists():
            raise FileNotFoundError("no backup found")

        shutil.copy2(dst, self.hosts_path)
        return dst
