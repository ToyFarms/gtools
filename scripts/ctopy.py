import ast
from pathlib import Path
import click

from gtools.core.c_parser import Setting, ctopy_ast
from gtools.core.transformer import DeadCodeEliminator, GotoResolver, NormalizeIdentifiers, RemoveTypeAnnotations


@click.command()
@click.argument("code")
def ctopy(code: str) -> None:
    try:
        if Path(code).exists():
            code = Path(code).read_text()
    except:
        pass

    code = code.replace("\\n", "\n")
    tree = ctopy_ast(code)

    tree = GotoResolver().visit(tree)
    ast.fix_missing_locations(tree)
    code = ast.unparse(tree)
    print(code)


@click.command()
@click.argument("code")
def ctopy2(code: str) -> None:
    try:
        if Path(code).exists():
            code = Path(code).read_text()
    except:
        pass

    code = code.replace("\\n", "\n")
    s = Setting(preserve_cast=False)
    tree = ctopy_ast(code, s)

    passes: list[type[ast.NodeTransformer]] = [GotoResolver, DeadCodeEliminator, NormalizeIdentifiers, RemoveTypeAnnotations]
    for pass_ in passes:
        tree = pass_().visit(tree)
        ast.fix_missing_locations(tree)

    code = ast.unparse(tree)
    print(code)
