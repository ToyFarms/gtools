import dataclasses
import enum as enum_module
import hashlib
import datetime
import json
import sys
from pathlib import Path
from typing import Any

import click

try:
    from rich.console import Console, Group as RenderGroup  # pyright: ignore[reportMissingImports]
    from rich.table import Table  # pyright: ignore[reportMissingImports]
    from rich.panel import Panel  # pyright: ignore[reportMissingImports]
    from rich.text import Text  # pyright: ignore[reportMissingImports]
    from rich.rule import Rule  # pyright: ignore[reportMissingImports]
    from rich.padding import Padding  # pyright: ignore[reportMissingImports]
    from rich import box  # pyright: ignore[reportMissingImports]

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from gtools import setting
from gtools.core.growtopia.items_dat import Item, ItemDatabase

FIELD_DESCRIPTIONS: dict[str, str] = {
    "id": "ID",
    "flags": "Flags",
    "item_type": "Type",
    "material": "Material",
    "name": "Name",
    "texture_file": "Texture",
    "texture_file_hash": "Tex Hash",
    "visual_effect": "Visual FX",
    "cooking_time": "Cook Time",
    "tex_coord_x": "Tex X",
    "tex_coord_y": "Tex Y",
    "texture_type": "Tex Type",
    "unk7": "Unk7",
    "collision_type": "Collision",
    "health": "Health",
    "restore_time": "Restore",
    "clothing_type": "Clothing",
    "rarity": "Rarity",
    "max_amount": "Max Stack",
    "extra_file": "Extra File",
    "extra_file_hash": "Extra Hash",
    "frame_interval_ms": "Frame ms",
    "pet_name": "Pet Name",
    "pet_prefix": "Pet Prefix",
    "pet_suffix": "Pet Suffix",
    "pet_ability": "Pet Ability",
    "seed_base": "Seed Base",
    "seed_overlay": "Seed Overlay",
    "tree_base": "Tree Base",
    "tree_leaves": "Tree Leaves",
    "seed_color": "Seed Color",
    "seed_overlay_color": "Overlay Color",
    "ingredient_": "Ingredient",
    "grow_time": "Grow Time",
    "fx_flags": "FX Flags",
    "animating_coordinates": "Anim Coords",
    "animating_texture_files": "Anim Textures",
    "animating_coordinates_2": "Anim Coords 2",
    "unk1": "Unk1",
    "unk2": "Unk2",
    "flags2": "Flags2",
    "cybot_related": "Cybot",
    "tile_range": "Tile Range",
    "vault_capacity": "Vault Cap",
    "punch_options": "Punch Opts",
    "masked_body_len": "Mask Len",
    "body_render_mask": "Body Mask",
    "light_range": "Light Range",
    "unk5": "Unk5",
    "can_sit": "Can Sit",
    "player_offset_x": "Ply Off X",
    "player_offset_y": "Ply Off Y",
    "chair_texture_x": "Chair Tex X",
    "chair_texture_y": "Chair Tex Y",
    "chair_leg_offset_x": "Leg Off X",
    "chair_leg_offset_y": "Leg Off Y",
    "chair_texture_file": "Chair Tex",
    "renderer_data_file": "Renderer",
    "unk6": "Unk6",
    "renderer_data_file_hash": "Rndr Hash",
    "has_alt_tile": "Alt Tile",
    "alt_index_offset": "Alt Offset",
    "alt_unk1": "Alt Unk1",
    "alt_unk2": "Alt Unk2",
    "alt_unk3": "Alt Unk3",
    "player_transform_related": "Transform",
    "info": "Info",
    "ingredients": "Ingredients",
    "unk9": "Unk9",
    "hit_fx": "Hit FX",
    "hit_duration_ms": "Hit Duration",
}


def _fmt(v: Any) -> str:
    if isinstance(v, enum_module.Enum):
        name = v.name
        return name if name is not None else str(v)
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return repr(v)
    if isinstance(v, tuple):
        return f"({', '.join(_fmt(x) for x in v)})"
    return str(v)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_date(path: Path) -> str:
    dt = datetime.datetime.fromtimestamp(path.stat().st_mtime)
    return dt.strftime("%B %d, %Y  %H:%M")


def _item_diff(new: Item, old: Item) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for f in dataclasses.fields(new):
        if f.name in ("id", "texture_file_hash", "extra_file_hash", "renderer_data_file_hash"):
            continue
        nv = getattr(new, f.name)
        ov = getattr(old, f.name)
        if nv != ov:
            out.append((f.name, _fmt(ov), _fmt(nv)))
    return out


@dataclasses.dataclass
class DiffResult:
    same_schema: bool
    new_version: int
    old_version: int
    added: list[Item]
    removed: list[Item]
    modified: list[tuple[Item, Item, list[tuple[str, str, str]]]]
    new_path: Path | None = None
    old_path: Path | None = None

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified)


def compute_diff(
    new: ItemDatabase,
    old: ItemDatabase,
    new_path: Path | None = None,
    old_path: Path | None = None,
) -> DiffResult:
    new_ids = set(new.items)
    old_ids = set(old.items)

    added = [new.items[i] for i in sorted(new_ids - old_ids)]
    removed = [old.items[i] for i in sorted(old_ids - new_ids)]
    modified: list[tuple[Item, Item, list]] = []

    for item_id in sorted(new_ids & old_ids):
        changes = _item_diff(new.items[item_id], old.items[item_id])
        if changes:
            modified.append((new.items[item_id], old.items[item_id], changes))

    return DiffResult(
        same_schema=new.version == old.version,
        new_version=new.version,
        old_version=old.version,
        added=added,
        removed=removed,
        modified=modified,
        new_path=new_path,
        old_path=old_path,
    )


def _item_to_dict(item: Item) -> dict:
    return {f.name: _fmt(getattr(item, f.name)) for f in dataclasses.fields(item)}


def diff_result_to_dict(result: DiffResult) -> dict:
    return {
        "old_version": result.old_version,
        "new_version": result.new_version,
        "same_schema": result.same_schema,
        "old_path": str(result.old_path) if result.old_path else None,
        "new_path": str(result.new_path) if result.new_path else None,
        "old_date": _file_date(result.old_path) if result.old_path else None,
        "new_date": _file_date(result.new_path) if result.new_path else None,
        "summary": {
            "added": len(result.added),
            "removed": len(result.removed),
            "modified": len(result.modified),
            "total": result.total_changes,
        },
        "added": [_item_to_dict(item) for item in result.added],
        "removed": [_item_to_dict(item) for item in result.removed],
        "modified": [
            {
                "id": new_item.id,
                "name": _fmt(new_item.name),
                "changes": [
                    {
                        "field": fn,
                        "before": ov,
                        "after": nv,
                    }
                    for fn, ov, nv in changes
                ],
            }
            for new_item, _old_item, changes in result.modified
        ],
    }


def render_json(results: list[DiffResult], *, consecutive: bool) -> None:
    if consecutive:
        payload: Any = [diff_result_to_dict(r) for r in results]
    else:
        payload = diff_result_to_dict(results[0])

    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _build_diff_table(rows: list[tuple[str, str, str]], max_cell: int = 60) -> "Table":
    t = Table(
        box=box.SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
        header_style="bold bright_black",
        show_header=True,
    )
    t.add_column("", style="bold", no_wrap=True, min_width=7)
    for field_name, _ov, _nv in rows:
        label = FIELD_DESCRIPTIONS.get(field_name, field_name)
        t.add_column(
            Text(label, style="bold cyan"),
            overflow="fold",
            min_width=12,
            max_width=44,
        )

    before_cells: list[Any] = [Text("Before", style="dim red")]
    after_cells: list[Any] = [Text("After", style="dim green")]
    for _fn, old_val, new_val in rows:
        before_cells.append(Text(old_val[:max_cell], style="red"))
        after_cells.append(Text(new_val[:max_cell], style="green"))

    t.add_row(*before_cells)
    t.add_row(*after_cells)

    return t


def render_rich(result: DiffResult, console: "Console") -> None:
    console.print()

    title = Text()
    title.append("ITEM DATABASE DIFF  ", style="bold white")
    title.append(f"v{result.old_version}", style="dim white")
    title.append(" -> ", style="dim")
    title.append(f"v{result.new_version}", style="bold white")
    title.append("  ")

    meta_lines: list[Text] = []
    for label, path in (("OLD", result.old_path), ("NEW", result.new_path)):
        if path:
            line = Text()
            line.append(f"  {label}  ", style="bold dim")
            line.append(_file_date(path), style="white")
            line.append("  sha256: ", style="dim")
            line.append(_sha256(path), style="dim cyan")
            meta_lines.append(line)

    header_content = (
        Text.assemble(
            title,
            *(Text("\n") + ml for ml in meta_lines),
        )
        if meta_lines
        else title
    )

    console.print(Panel(header_content, border_style="bright_black", padding=(0, 2)))
    console.print()

    def _card(label: str, count: int, color: str, sub: str = "") -> Panel:
        t = Text(justify="center")
        t.append(f"{count}\n", style=f"bold {color}")
        t.append(label, style=f"dim {color}")
        if sub:
            t.append(f"\n{sub}", style="dim white")
        return Panel(t, border_style=color, padding=(0, 2), expand=True)

    cards_grid = Table.grid(expand=True)
    for _ in range(4):
        cards_grid.add_column(ratio=1)
    cards_grid.add_row(
        _card("ADDED", len(result.added), "green", f"+{len(result.added)} items"),
        _card("REMOVED", len(result.removed), "red", f"-{len(result.removed)} items"),
        _card("MODIFIED", len(result.modified), "yellow", f"~{len(result.modified)} items"),
        _card("TOTAL", result.total_changes, "white", "total changes"),
    )
    console.print(cards_grid)
    console.print()

    if result.added:
        console.print(Rule(f"[bold green]  ADDED  ({len(result.added)})[/]", style="green"))
        console.print()
        t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style="bold bright_black")
        t.add_column("ID", style="dim", min_width=6, no_wrap=True)
        t.add_column("Name", style="bold green", min_width=30)
        t.add_column("Type", style="cyan", min_width=20)
        t.add_column("Rarity", justify="right", style="yellow")
        t.add_column("Flags", style="dim", overflow="fold")
        for item in result.added:
            name = _fmt(item.name) or "—"
            flags_str = _fmt(item.flags)
            t.add_row(
                str(item.id),
                name,
                _fmt(item.item_type),
                str(item.rarity),
                flags_str if flags_str != "NONE" else "—",
            )
        console.print(Padding(t, (0, 2)))
        console.print()

    if result.removed:
        console.print(Rule(f"[bold red]  REMOVED  ({len(result.removed)})[/]", style="red"))
        console.print()
        t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style="bold bright_black")
        t.add_column("ID", style="dim", min_width=6, no_wrap=True)
        t.add_column("Name", style="bold red", min_width=30)
        t.add_column("Type", style="cyan", min_width=20)
        t.add_column("Rarity", justify="right", style="yellow")
        for item in result.removed:
            t.add_row(
                str(item.id),
                _fmt(item.name) or "—",
                _fmt(item.item_type),
                str(item.rarity),
            )
        console.print(Padding(t, (0, 2)))
        console.print()

    if result.modified:
        console.print(Rule(f"[bold yellow]  MODIFIED  ({len(result.modified)})[/]", style="yellow"))
        console.print()
        for new_item, _old_item, changes in result.modified:
            name = _fmt(new_item.name) or f"Item #{new_item.id}"
            header = Text()
            header.append(f"#{new_item.id} ", style="dim")
            header.append(name, style="bold white")
            n = len(changes)
            header.append(f"  [{n} change{'s' if n != 1 else ''}]", style="dim yellow")
            tbl = _build_diff_table(changes)
            console.print(
                Panel(
                    RenderGroup(Padding(tbl, (0, 1))),
                    title=header,
                    title_align="left",
                    border_style="yellow",
                    padding=(0, 1),
                )
            )
        console.print()

    if result.total_changes == 0:
        console.print("[bold green]  No differences found.[/]")
    console.print()


def render_timeline_summary_rich(results: list[DiffResult], console: "Console") -> None:
    if not results:
        return

    console.print()
    console.print(Rule("[bold white]  DATABASE TIMELINE SUMMARY  [/]", style="bright_black"))
    console.print()

    t = Table(
        box=box.SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
        header_style="bold bright_black",
    )
    t.add_column("Transition", style="cyan", min_width=14, no_wrap=True)
    t.add_column("Date (new)", style="white", min_width=22, no_wrap=True)
    t.add_column("Added", justify="right", style="green", min_width=7)
    t.add_column("Removed", justify="right", style="red", min_width=8)
    t.add_column("Modified", justify="right", style="yellow", min_width=9)
    t.add_column("Total", justify="right", style="white", min_width=6)
    t.add_column("Schema", style="dim", min_width=8)

    grand_added = grand_removed = grand_modified = 0
    for r in results:
        date_str = _file_date(r.new_path) if r.new_path else "—"
        schema_cell = Text("same", style="dim cyan") if r.same_schema else Text("upgrade", style="bold yellow")
        t.add_row(
            f"v{r.old_version} -> v{r.new_version}",
            date_str,
            str(len(r.added)),
            str(len(r.removed)),
            str(len(r.modified)),
            str(r.total_changes),
            schema_cell,
        )
        grand_added += len(r.added)
        grand_removed += len(r.removed)
        grand_modified += len(r.modified)

    grand_total = grand_added + grand_removed + grand_modified
    t.add_section()
    t.add_row(
        Text("TOTAL", style="bold white"),
        Text("", style=""),
        Text(str(grand_added), style="bold green"),
        Text(str(grand_removed), style="bold red"),
        Text(str(grand_modified), style="bold yellow"),
        Text(str(grand_total), style="bold white"),
        Text("", style=""),
    )

    console.print(Padding(t, (0, 2)))
    console.print()


class A:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    WHITE = "\x1b[97m"
    CYAN = "\x1b[96m"
    GREEN = "\x1b[92m"
    YELLOW = "\x1b[93m"
    RED = "\x1b[91m"
    GREY = "\x1b[90m"

    @staticmethod
    def c(*codes: str, text: str) -> str:
        return "".join(codes) + text + A.RESET


def _ansi_rule(label: str = "", color: str = "", width: int = 72) -> str:
    if label:
        colored_label = A.c(A.BOLD, color, text=f"  {label}  ") if color else f"  {label}  "
        pad = max(0, width - len(label) - 4)
        return A.c(A.GREY, text="──") + colored_label + A.c(A.GREY, text="─" * pad)
    return A.c(A.GREY, text="─" * width)


def render_ansi(result: DiffResult) -> None:
    W = 72

    print()
    ver_line = (
        A.c(A.BOLD, A.WHITE, text="ITEM DATABASE DIFF  ")
        + A.c(A.GREY, text=f"v{result.old_version}")
        + A.c(A.GREY, text=" -> ")
        + A.c(A.BOLD, A.WHITE, text=f"v{result.new_version}")
    )
    print(_ansi_rule(width=W))
    print(f"  {ver_line}")
    for label, path in (("OLD", result.old_path), ("NEW", result.new_path)):
        if path:
            print(f"  {A.c(A.BOLD, A.GREY, text=label)}  " + A.c(A.WHITE, text=_file_date(path)) + A.c(A.GREY, text="  sha256: ") + A.c(A.CYAN, A.DIM, text=_sha256(path)))
    print(_ansi_rule(width=W))

    print()
    summary = (
        A.c(A.BOLD, A.GREEN, text=f"+{len(result.added)}")
        + A.c(A.GREY, text=" added   ")
        + A.c(A.BOLD, A.RED, text=f"-{len(result.removed)}")
        + A.c(A.GREY, text=" removed   ")
        + A.c(A.BOLD, A.YELLOW, text=f"~{len(result.modified)}")
        + A.c(A.GREY, text=" modified   ")
        + A.c(A.BOLD, A.WHITE, text=str(result.total_changes))
        + A.c(A.GREY, text=" total")
    )
    print(f"  {summary}")
    print()

    if result.added:
        print(_ansi_rule(f"ADDED ({len(result.added)})", A.GREEN, W))
        print()
        print(A.c(A.GREY, text=f"  {'ID':>6}  ") + A.c(A.BOLD, A.GREY, text=f"{'Name':<40}  {'Type':<24}  {'Rarity':>6}"))
        print(A.c(A.GREY, text="  " + "─" * (W - 2)))
        for item in result.added:
            print(
                A.c(A.GREY, text=f"  {item.id:>6}  ")
                + A.c(A.BOLD, A.GREEN, text=f"{_fmt(item.name):<40}")
                + "  "
                + A.c(A.CYAN, text=f"{_fmt(item.item_type):<24}")
                + "  "
                + A.c(A.YELLOW, text=f"{item.rarity:>6}")
            )
        print()

    if result.removed:
        print(_ansi_rule(f"REMOVED ({len(result.removed)})", A.RED, W))
        print()
        print(A.c(A.GREY, text=f"  {'ID':>6}  ") + A.c(A.BOLD, A.GREY, text=f"{'Name':<40}  {'Type':<24}  {'Rarity':>6}"))
        print(A.c(A.GREY, text="  " + "─" * (W - 2)))
        for item in result.removed:
            print(
                A.c(A.GREY, text=f"  {item.id:>6}  ")
                + A.c(A.BOLD, A.RED, text=f"{_fmt(item.name):<40}")
                + "  "
                + A.c(A.CYAN, text=f"{_fmt(item.item_type):<24}")
                + "  "
                + A.c(A.YELLOW, text=f"{item.rarity:>6}")
            )
        print()

    if result.modified:
        print(_ansi_rule(f"MODIFIED ({len(result.modified)})", A.YELLOW, W))
        print()
        for new_item, _old_item, changes in result.modified:
            name = _fmt(new_item.name) or f"Item #{new_item.id}"
            n = len(changes)
            print(f"  {A.c(A.GREY, text=f'#{new_item.id} ')}" + A.c(A.BOLD, A.WHITE, text=name) + A.c(A.DIM, A.YELLOW, text=f"  [{n} change{'s' if n != 1 else ''}]"))

            labels = [FIELD_DESCRIPTIONS.get(fn, fn) for fn, _ov, _nv in changes]
            old_vals = [ov[:28] for _, ov, _ in changes]
            new_vals = [nv[:28] for _, _, nv in changes]
            col_w = [max(len(lb), len(ov), len(nv)) + 2 for lb, ov, nv in zip(labels, old_vals, new_vals)]

            def _row(cells: list[str], color: str) -> str:
                return "    " + "  ".join(A.c(color, text=c.ljust(w)) for c, w in zip(cells, col_w))

            print("    " + "  ".join(A.c(A.BOLD, A.CYAN, text=lb.ljust(w)) for lb, w in zip(labels, col_w)))
            print(_row(old_vals, A.RED))
            print(_row(new_vals, A.GREEN))
            print()

    if result.total_changes == 0:
        print(A.c(A.BOLD, A.GREEN, text="  ✓  No differences found."))
    print()


def render_timeline_summary_ansi(results: list[DiffResult]) -> None:
    if not results:
        return
    W = 72
    COL = (16, 30, 5, 6, 7, 6, 10)

    print()
    print(_ansi_rule("DATABASE TIMELINE SUMMARY", A.WHITE, W))
    print()

    hdr_cells = ["Transition", "Date (new)", "Add", "Rem", "Mod", "Tot", "Schema"]
    hdr_colors = [A.CYAN, A.WHITE, A.GREEN, A.RED, A.YELLOW, A.WHITE, A.GREY]
    print("  " + "  ".join(A.c(A.BOLD, col, text=(cell.ljust(w) if i < 2 else cell.rjust(w))) for i, (cell, col, w) in enumerate(zip(hdr_cells, hdr_colors, COL))))
    print(A.c(A.GREY, text="  " + "─" * (W - 2)))

    grand_added = grand_removed = grand_modified = 0
    for r in results:
        date_str = _file_date(r.new_path) if r.new_path else "—"
        transition = f"v{r.old_version} -> v{r.new_version}"
        schema_str = A.c(A.BOLD, A.YELLOW, text="upgrade") if not r.same_schema else A.c(A.DIM, A.CYAN, text="same")
        print(
            "  "
            + A.c(A.CYAN, text=transition.ljust(COL[0]))
            + "  "
            + A.c(A.WHITE, text=date_str.ljust(COL[1]))
            + "  "
            + A.c(A.GREEN, text=str(len(r.added)).rjust(COL[2]))
            + "  "
            + A.c(A.RED, text=str(len(r.removed)).rjust(COL[3]))
            + "  "
            + A.c(A.YELLOW, text=str(len(r.modified)).rjust(COL[4]))
            + "  "
            + A.c(A.WHITE, text=str(r.total_changes).rjust(COL[5]))
            + "  "
            + schema_str
        )
        grand_added += len(r.added)
        grand_removed += len(r.removed)
        grand_modified += len(r.modified)

    grand_total = grand_added + grand_removed + grand_modified
    print(A.c(A.GREY, text="  " + "─" * (W - 2)))
    print(
        "  "
        + A.c(A.BOLD, A.WHITE, text="TOTAL".ljust(COL[0]))
        + "  "
        + " " * COL[1]
        + "  "
        + A.c(A.BOLD, A.GREEN, text=str(grand_added).rjust(COL[2]))
        + "  "
        + A.c(A.BOLD, A.RED, text=str(grand_removed).rjust(COL[3]))
        + "  "
        + A.c(A.BOLD, A.YELLOW, text=str(grand_modified).rjust(COL[4]))
        + "  "
        + A.c(A.BOLD, A.WHITE, text=str(grand_total).rjust(COL[5]))
    )
    print()


def render_plain(result: DiffResult) -> None:
    W = 72

    def rule(label: str = "") -> None:
        pad = max(0, W - len(label) - 4)
        print(f"── {label} {'─' * pad}" if label else "─" * W)

    print()
    rule(f"ITEM DATABASE DIFF  v{result.old_version} -> v{result.new_version}")
    print(f"  Added: {len(result.added)}   Removed: {len(result.removed)}   Modified: {len(result.modified)}")

    for label, path in (("OLD", result.old_path), ("NEW", result.new_path)):
        if path:
            print(f"  {label}  {_file_date(path)}  sha256: {_sha256(path)}")

    rule()

    if result.added:
        print(f"\n[+] ADDED ({len(result.added)})\n")
        for item in result.added:
            print(f"  #{item.id:>6}  {_fmt(item.name):<40}  {_fmt(item.item_type)}")

    if result.removed:
        print(f"\n[-] REMOVED ({len(result.removed)})\n")
        for item in result.removed:
            print(f"  #{item.id:>6}  {_fmt(item.name):<40}  {_fmt(item.item_type)}")

    if result.modified:
        print(f"\n[~] MODIFIED ({len(result.modified)})\n")
        for new_item, _, changes in result.modified:
            print(f"  #{new_item.id:>6}  {_fmt(new_item.name):<40}  ({len(changes)} changes)")
            if changes:
                labels = [f"{FIELD_DESCRIPTIONS.get(fn, fn)}" for fn, _ov, _nv in changes]
                old_vals = [ov[:28] for _, ov, _ in changes]
                new_vals = [nv[:28] for _, _, nv in changes]
                col_w = [max(len(l), len(o), len(n)) + 2 for l, o, n in zip(labels, old_vals, new_vals)]

                def _pad_row(cells: list[str]) -> str:
                    return "  " + "  ".join(c.ljust(w) for c, w in zip(cells, col_w))

                print(_pad_row(labels))
                print(_pad_row(old_vals))
                print(_pad_row(new_vals))
                print()
    print()


def render_timeline_summary_plain(results: list[DiffResult]) -> None:
    if not results:
        return
    W = 72
    print("\n" + "─" * W)
    print("  DATABASE TIMELINE SUMMARY")
    print("─" * W)
    header = f"  {'Transition':<16}  {'Date (new)':<22}  {'Add':>4}  {'Rem':>4}  {'Mod':>5}  {'Tot':>5}"
    print(header)
    print("  " + "─" * (len(header) - 2))
    grand_added = grand_removed = grand_modified = 0
    for r in results:
        date_str = _file_date(r.new_path) if r.new_path else "—"
        transition = f"v{r.old_version} -> v{r.new_version}"
        print(
            f"  {transition:<16}  {date_str:<22}  "
            f"{len(r.added):>4}  {len(r.removed):>4}  {len(r.modified):>5}  {r.total_changes:>5}"
            f"{'  (schema)' if not r.same_schema else ''}"
        )
        grand_added += len(r.added)
        grand_removed += len(r.removed)
        grand_modified += len(r.modified)
    grand_total = grand_added + grand_removed + grand_modified
    print("  " + "─" * (len(header) - 2))
    print(f"  {'TOTAL':<16}  {'':22}  " f"{grand_added:>4}  {grand_removed:>4}  {grand_modified:>5}  {grand_total:>5}")
    print()


def _get_all_item_database() -> list[Path]:
    store = setting.appdir / "item_database"
    dats = sorted(store.glob("**/*.dat"), reverse=True)
    return dats


def _render(result: DiffResult, no_color: bool) -> None:
    if HAS_RICH and not no_color:
        render_rich(result, Console(highlight=False))
    elif not no_color:
        render_ansi(result)
    else:
        render_plain(result)


def _render_separator(use_rich: bool, use_ansi: bool, console: "Console | None") -> None:
    if use_rich and console:
        console.print(Rule(style="bright_black"))
    elif use_ansi:
        print("\n" + A.c(A.GREY, text="═" * 72) + "\n")
    else:
        print("\n" + "═" * 72 + "\n")


def _render_timeline(results: list[DiffResult], use_rich: bool, use_ansi: bool, console: "Console | None") -> None:
    if use_rich and console:
        render_timeline_summary_rich(results, console)
    elif use_ansi:
        render_timeline_summary_ansi(results)
    else:
        render_timeline_summary_plain(results)


@click.command
@click.argument("old_dat", required=False, metavar="OLD.DAT", type=click.Path(exists=True))
@click.argument("new_dat", required=False, metavar="NEW.DAT", type=click.Path(exists=True))
@click.option("--no-color", is_flag=True, default=False, help="Disable color / rich output.")
@click.option("--all", "use_all", is_flag=True, default=False, help="Use all archived .dat files (overrides -n).")
@click.option(
    "--consecutive",
    is_flag=True,
    default=False,
    help=(
        "Diff each consecutive pair in the selected range instead of a single "
        "cumulative diff between the oldest and newest."
    ),
)
@click.option(
    "-n",
    "count",
    default=2,
    show_default=True,
    metavar="N",
    help=(
        "Number of latest archives to include. "
        "Default 2 diffs the latest against its predecessor. "
        "Ignored when --all is set."
    ),
)
@click.option("--json", "output_json", is_flag=True, default=False, help="Output structured JSON (suppresses all other output).")
def mine(
    old_dat: Path | None,
    new_dat: Path | None,
    no_color: bool,
    use_all: bool,
    consecutive: bool,
    count: int,
    output_json: bool,
) -> None:
    use_rich = HAS_RICH and not no_color and not output_json
    use_ansi = not use_rich and not no_color and not output_json
    console = Console(highlight=False) if use_rich else None

    if old_dat and new_dat:
        new_path = Path(new_dat)
        old_path = Path(old_dat)
        new_db = ItemDatabase.load(new_path)
        old_db = ItemDatabase.load(old_path)
        result = compute_diff(new_db, old_db, new_path=new_path, old_path=old_path)
        if output_json:
            render_json([result], consecutive=False)
        else:
            _render(result, no_color=no_color)
        return

    dats = _get_all_item_database()

    if use_all:
        selected = dats
    else:
        if count < 2:
            print("error: -n must be at least 2", file=sys.stderr)
            sys.exit(1)
        selected = dats[:count]

    if len(selected) < 2:
        needed = "at least two archived .dat files"
        print(f"need {needed}", file=sys.stderr)
        sys.exit(1)

    if not consecutive:
        newest, oldest = selected[0], selected[-1]
        if not output_json:
            print(f"comparing:\n  NEW: {newest}\n  OLD: {oldest}\n", file=sys.stderr)
        new_db = ItemDatabase.load(newest)
        old_db = ItemDatabase.load(oldest)
        result = compute_diff(new_db, old_db, new_path=newest, old_path=oldest)
        if output_json:
            render_json([result], consecutive=False)
        else:
            _render(result, no_color=no_color)
        return

    pairs = list(reversed(list(zip(selected, selected[1:]))))
    if not output_json:
        print(
            f"found {len(selected)} archives -> running {len(pairs)} diff(s)  (oldest -> newest).\n",
            file=sys.stderr,
        )

    all_results: list[DiffResult] = []
    for i, (newer, older) in enumerate(pairs, 1):
        if not output_json:
            print(f"[{i}/{len(pairs)}]  {older.name}  ->  {newer.name}", file=sys.stderr)

        new_db = ItemDatabase.load(newer)
        old_db = ItemDatabase.load(older)
        result = compute_diff(new_db, old_db, new_path=newer, old_path=older)
        all_results.append(result)

        if not output_json:
            if use_rich and console:
                render_rich(result, console)
            elif use_ansi:
                render_ansi(result)
            else:
                render_plain(result)

            if i < len(pairs):
                _render_separator(use_rich, use_ansi, console)

    if output_json:
        render_json(all_results, consecutive=True)
    else:
        _render_timeline(all_results, use_rich, use_ansi, console)
