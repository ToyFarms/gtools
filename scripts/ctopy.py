import ast
from pathlib import Path
import re
import click

from gtools.core.c_parser import Setting, ctopy_ast
from gtools.core.transformer import DeadCodeEliminator, GotoResolver, NormalizeIdentifiers, RemoveTypeAnnotations


def raw(code: str, s: Setting | None = None) -> ast.Module:
    try:
        if Path(code).exists():
            code = Path(code).read_text()
    except:
        pass

    code = code.replace("\\n", "\n")
    return ast.fix_missing_locations(ctopy_ast(code, s))


def clean(code: str, s: Setting | None = None) -> ast.Module:
    if s is None:
        s = Setting(preserve_cast=False, ref=False)
    tree = raw(code, s)
    passes: list[type[ast.NodeTransformer]] = [GotoResolver, DeadCodeEliminator, NormalizeIdentifiers]
    for pass_ in passes:
        tree = pass_().visit(tree)
        ast.fix_missing_locations(tree)

    return tree


@click.command()
@click.argument("code")
def ctopy_raw(code: str) -> None:
    code = ast.unparse(raw(code))
    print(code)


@click.command()
@click.argument("code")
def ctopy(code: str) -> None:
    code = ast.unparse(clean(code))
    print(code)


@click.command()
@click.argument("code")
def ctopy1(code: str) -> None:
    code = ast.unparse(clean(code))
    code = re.sub(r"get_foreground_or_background_id\(([^)]*)\)", r"\1.front", code)
    code = re.sub(r"GLUED", r"TileFlags.GLUED", code)
    code = re.sub(r"world_view", r"world", code)
    code = re.sub(r"world.tilesBegin\[([^\]]*)\]", r"world.get_tile(\1)", code)
    code = re.sub(r"is_tile_steam_type\(([^)]*)\)", r"item_database.get(\1.front).is_steam()", code)
    code = re.sub(r"GUILD_FLAG_SHIELD_DIVISION", r"GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE", code)

    print(code)


@click.command()
@click.argument("code")
def ctopy2(code: str) -> None:
    tree = clean(code)
    code = ast.unparse(tree)
    code = re.sub(r"get_foreground_or_background_id\(([^)]*)\)", r"\1.front", code)
    code = re.sub(r"GLUED", r"TileFlags.GLUED", code)
    code = re.sub(r"world_view", r"world", code)
    code = re.sub(r"world.tilesBegin\[([^\]]*)\]", r"world.get_tile(\1)", code)
    code = re.sub(r"is_tile_steam_type\(([^)]*)\)", r"item_database.get(\1.front).is_steam()", code)
    code = re.sub(r"GUILD_FLAG_SHIELD_DIVISION", r"GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE", code)
    code = re.sub(r"tile\.tileX", r"tile.pos.x", code)
    code = re.sub(r"tile\.tileY", r"tile.pos.y", code)

    print(code)

@click.command()
@click.argument("code")
def ctopy8(code: str) -> None:
    tree = clean(code)
    code = ast.unparse(tree)
    code = re.sub(r"get_foreground_or_background_id\(([^)]*)\)", r"\1.front", code)
    code = re.sub(r"get_fg_or_bg\(([^)]*)\)", r"\1.front", code)
    code = re.sub(r"getForegroundOrBackgroundId\(([^)]*)\)", r"\1.front", code)
    code = re.sub(r"GLUED", r"TileFlags.GLUED", code)
    code = re.sub(r"FLIPPED_X", r"TileFlags.FLIPPED_X", code)
    code = re.sub(r"world_view", r"world", code)
    code = re.sub(r"tilesBegin\[([^\]]*)\]", r"get_tile(\1)", code)
    code = re.sub(r"is_tile_steam_type\(([^)]*)\)", r"item_database.get(\1.front).is_steam()", code)
    code = re.sub(r"GUILD_FLAG_SHIELD_DIVISION", r"GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE", code)
    code = re.sub(r"tile\.tileX", r"tile.pos.x", code)
    code = re.sub(r"tile\.tileY", r"tile.pos.y", code)
    code = re.sub(r"tile\.x", r"tile.pos.x", code)
    code = re.sub(r"tile\.y", r"tile.pos.y", code)
    code = re.sub(r"tileX", r"tile_x", code)
    code = re.sub(r"tileY", r"tile_y", code)
    code = re.sub(r"textureType", r"texture_type", code)
    code = re.sub(r"fgTileConnectivityState", r"fg_tex_index", code)
    code = re.sub(r"bgTileConnectivityState", r"bg_tex_index", code)
    code = re.sub(r"get_item_manager\(\)", r"item_database", code)
    code = re.sub(r"item_database.itemsBegin\[([^\]]*)\]", r"item_database.get(\1)", code)
    code = re.sub(r"maybe_get_item_by_id\(.*, ([^)]*)\)", r"item_database.get(\1)", code)
    code = re.sub(r"'ItemID' = None", r"int = 0", code)
    code = re.sub(r"a1\.tile_([xy])", r"a1.pos.\1", code)
    code = re.sub(r"WorldView \| None", r"World", code)
    code = re.sub(r"Tile \| None", r"Tile", code)
    code = re.sub(r"'__int64___fastcall'", r"int", code)
    code = re.sub(r"'bool___fastcall'", r"bool", code)
    code = re.sub(r"'ItemID'", r"int", code)

    print(code)
