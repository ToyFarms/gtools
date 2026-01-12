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
    passes: list[type[ast.NodeTransformer]] = [GotoResolver, DeadCodeEliminator, NormalizeIdentifiers, RemoveTypeAnnotations]
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
    code = re.sub(r"GLUED", r"TileFlags.GLUED", code)
    code = re.sub(r"world_view", r"world", code)
    code = re.sub(r"world.tilesBegin\[([^\]]*)\]", r"world.get_tile(\1)", code)
    code = re.sub(r"is_tile_steam_type\(([^)]*)\)", r"item_database.get(\1.front).is_steam()", code)
    code = re.sub(r"GUILD_FLAG_SHIELD_DIVISION", r"GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE", code)
    code = re.sub(r"tile\.tileX", r"tile.pos.x", code)
    code = re.sub(r"tile\.tileY", r"tile.pos.y", code)
    code = re.sub(r"textureType", r"texture_type", code)
    code = re.sub(r"fgTileConnectivityState", r"fg_tex_index", code)
    code = re.sub(r"bgTileConnectivityState", r"bg_tex_index", code)
    code = re.sub(r"get_item_manager\(\)", r"item_database", code)
    code = re.sub(r"item_database.itemsBegin\[([^\]]*)\]", r"item_database.get(\1)", code)
    code = re.sub(r"maybe_get_item_by_id\(.*, ([^)]*)\)", r"item_database.get(\1)", code)


    print(code)
