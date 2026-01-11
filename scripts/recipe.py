from collections import defaultdict
from functools import cache
from pprint import pprint
import click
from gtools.core.growtopia.items_dat import Item, item_database


@click.command()
@click.argument("id", type=int)
@click.option("-n", default=1, type=int, help="number of items")
def recipe(id: int, n: int) -> None:
    class SpliceNode:
        def __init__(self, item: Item):
            self.item = item
            self.left: SpliceNode | None = None
            self.right: SpliceNode | None = None

    def print_crafting_tree(
        node: SpliceNode | None,
        prefix: str = "",
        is_left: bool = True,
        depth: int = 1,
    ):
        if node is None:
            return

        item = node.item
        name = item.name.decode().removesuffix(" Seed")
        name_len = len(name)

        connector = ""
        if prefix:
            connector = "└─ " if is_left else "├─ "

        print(f"{prefix}{connector} ({depth}) {name}")

        spacer = " " * (name_len // 2 - 1)
        next_prefix = prefix + ("│  " if not is_left else "   ") + spacer

        if node.right:
            print_crafting_tree(
                node.right,
                next_prefix,
                is_left=False,
                depth=depth + 1,
            )

        if node.left:
            print_crafting_tree(
                node.left,
                next_prefix,
                is_left=True,
                depth=depth + 1,
            )

    @cache
    def build_crafting_tree(item_id: int) -> SpliceNode:
        item = item_database.get(item_id)
        node = SpliceNode(item)
        left_id, right_id = item.ingredients

        if left_id != 0:
            node.left = build_crafting_tree(left_id)

        if right_id != 0:
            node.right = build_crafting_tree(right_id)

        return node

    @cache
    def count_nodes(node: SpliceNode | None) -> int:
        if node is None:
            return 0
        return 1 + count_nodes(node.left) + count_nodes(node.right)

    mats_by_layer: dict[int, dict[bytes, int]] = defaultdict(lambda: defaultdict(int))

    @cache
    def calc_cost(node: SpliceNode | None, depth: int = 1) -> None:
        if node is None:
            return

        mats_by_layer[depth][node.item.name] += 1
        calc_cost(node.left, depth + 1)
        calc_cost(node.right, depth + 1)

    tree = build_crafting_tree(id)

    def walk(node: SpliceNode, raw_mats: defaultdict[bytes, int], steps: defaultdict[bytes, int]) -> None:
        if node.left is None and node.right is None:
            raw_mats[node.item.name] += 1

        walk(node.left, raw_mats, steps) if node.left else None
        walk(node.right, raw_mats, steps) if node.right else None

        steps[node.item.name] += 1

    tree = build_crafting_tree(id)

    raw_mats = defaultdict(int)
    steps = defaultdict(int)
    walk(tree, raw_mats, steps)

    print("-" * 50, "fun fact", "-" * 50)
    print()
    most_nodes = sorted(
        [(f"({i}) {item_database.get(i).name.decode()}", count_nodes(build_crafting_tree(i))) for i in range(len(item_database.items()))],
        key=lambda x: x[1],
        reverse=True,
    )[:20]
    print("most amount of nodes (splice step)")
    pprint(most_nodes)
    print()

    @cache
    def count_raw_mats(node: SpliceNode) -> int:
        raw_mats = defaultdict(int)
        no = defaultdict(int)
        walk(node, raw_mats, no)

        return len(raw_mats)

    most_raw_mats = sorted(
        [(f"({i}) {item_database.get(i).name.decode()}", count_raw_mats(build_crafting_tree(i))) for i in range(len(item_database.items()))],
        key=lambda x: x[1],
        reverse=True,
    )[:20]
    print("most raw material")
    pprint(most_raw_mats)
    print()
    print("-" * 50, "fun fact", "-" * 50)

    print_crafting_tree(tree)
    print(f"\nraw materials (for {n} {tree.item.name.decode()}, assuming 1:1 ratio):")
    for name, count in raw_mats.items():
        print(f"  {name.decode().removesuffix(' Seed'):20} ({count * n:_})")

    print("\nsteps:")
    max_len = 0
    step_lines = []
    for i, (name, count) in enumerate(filter(lambda x: x[0] not in raw_mats, steps.items()), 1):
        item = item_database.get_by_name(name)
        left_id, right_id = item.ingredients
        left = item_database.get(left_id).name.decode().removesuffix(" Seed") if left_id else ""
        right = item_database.get(right_id).name.decode().removesuffix(" Seed") if right_id else ""
        ing = f"{i:>3}) {left} + {right}" if left or right else "(no ingredients)"
        step_lines.append((ing, name.decode().removesuffix(" Seed"), count))
        max_len = max(max_len, len(ing))

    for i, (ing, out, count) in enumerate(step_lines):
        if i % 2 == 0:
            print(f"  {ing.ljust(max_len)}   {out} ({count * n:_})")
        else:
            print(f"  {ing.ljust(max_len, '.')}...{out} ({count * n:_})")
