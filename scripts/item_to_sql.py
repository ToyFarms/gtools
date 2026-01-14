from dataclasses import fields, is_dataclass
from typing import Any, Type
import click
from zmq import Enum
from gtools.core.growtopia.items_dat import item_database
import sqlite3


def insert(
    conn: sqlite3.Connection,
    obj: Any,
    table_name: str | None = None,
    primary_key: str | None = None,
    create_table: bool = True,
) -> None:
    if not is_dataclass(obj):
        raise TypeError("obj must be a dataclass instance")

    table = table_name or obj.__class__.__name__  # pyright: ignore[reportAttributeAccessIssue]
    dc_fields = fields(obj)

    def sqlite_type(py_type: Type, value: Any) -> tuple[str, Type]:
        if isinstance(value, Enum):
            return "TEXT", lambda x: x.name  # pyright: ignore[reportReturnType]
        elif py_type is int:
            return "INTEGER", int
        elif py_type is float:
            return "REAL", float
        elif py_type is bool:
            return "INTEGER", int
        else:
            return "TEXT", str

    values = []
    if create_table:
        column_defs = []
        for f in dc_fields:
            col = f.name
            v = getattr(obj, f.name)
            col_type, val_type = sqlite_type(f.type, v)  # pyright: ignore[reportArgumentType]
            values.append(val_type(v))
            if primary_key == col:
                column_defs.append(f"{col} {col_type} PRIMARY KEY")
            else:
                column_defs.append(f"{col} {col_type}")

        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {", ".join(column_defs)}
        )
        """
        conn.execute(create_sql)

    columns = [f.name for f in dc_fields]

    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f"""
    INSERT INTO {table} ({", ".join(columns)})
    VALUES ({placeholders})
    """

    conn.execute(insert_sql, values)


@click.command()
def items_to_sql() -> None:
    with sqlite3.connect("items.db") as conn:
        items = item_database.items().items()
        for i, (_, item) in enumerate(items):
            insert(conn, item)
            print(f"\r{i} / {len(items)}", end="")
        conn.commit()
        print()
