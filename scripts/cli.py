#!/usr/bin/env -S uv run --script
import importlib
import pkgutil
from traceback import print_exc
import click

import scripts


@click.group()
def cli() -> None:
    pass


def _discover_commands() -> None:
    exclude = {"__init__", "cli", "utils"}
    scripts_path = scripts.__path__

    for finder, name, ispkg in pkgutil.iter_modules(scripts_path, scripts.__name__ + "."):
        module_name = name.split(".")[-1]

        if module_name in exclude or ispkg:
            continue

        try:
            module = importlib.import_module(name)
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue

                attr = getattr(module, attr_name)

                if isinstance(attr, click.Command) and not isinstance(attr, click.Group):
                    command_name = attr_name.replace("_", "-")
                    cli.add_command(attr, name=command_name)
        except Exception:
            print(f"MODULE: \x1b[31m{module_name}\x1b[0m", "=" * 50)
            print_exc()
            print("=" * 50)


_discover_commands()


if __name__ == "__main__":
    cli()
