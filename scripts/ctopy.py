import ast
from pathlib import Path
import click

from gtools.core.c_parser import ctopy_ast
from gtools.core.transformer import GotoResolver


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
