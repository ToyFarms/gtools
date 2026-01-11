import ast
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import cast


class GotoResolver(ast.NodeTransformer):
    def __init__(self) -> None:
        self.labels: set[str] = set()
        self.label_blocks: dict[str, list[ast.stmt]] = {}
        self.in_function = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        has_goto = self._contains_goto_or_label(node)

        if not has_goto:
            return node

        self.labels = set()
        self.label_blocks = {}
        self.in_function = True

        self._collect_all_labels(node.body)
        self._extract_label_blocks(node.body)

        transformed_body = self._create_state_machine(node.body)

        new_func = ast.FunctionDef(
            name=node.name, args=node.args, body=transformed_body, decorator_list=node.decorator_list, returns=node.returns, lineno=node.lineno, col_offset=node.col_offset
        )

        self.in_function = False
        return ast.copy_location(new_func, node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        has_goto = self._contains_goto_or_label(node)
        if not has_goto:
            return node

        self.labels = set()
        self.label_blocks = {}
        self.in_function = True

        self._collect_all_labels(node.body)
        self._extract_label_blocks(node.body)
        transformed_body = self._create_state_machine(node.body)

        new_func = ast.AsyncFunctionDef(
            name=node.name, args=node.args, body=transformed_body, decorator_list=node.decorator_list, returns=node.returns, lineno=node.lineno, col_offset=node.col_offset
        )

        self.in_function = False
        return ast.copy_location(new_func, node)

    # def visit_Module(self, node: ast.Module) -> ast.Module:
    #     non_fn = [node for node in node.body if not isinstance(node, ast.FunctionDef)]

    #     non_fn_mod = ast.Module(body=non_fn)
    #     has_goto = self._contains_goto_or_label(non_fn_mod)
    #     if not has_goto:
    #         return node

    #     self._collect_all_labels(node.body)
    #     self._extract_label_blocks(node.body)
    #     transformed_body = self._create_state_machine(node.body)
    #     node.body = transformed_body
    #     return node

    def _contains_goto_or_label(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                if isinstance(child.value, ast.Call):
                    if isinstance(child.value.func, ast.Name):
                        if child.value.func.id in ("LABEL", "goto"):
                            return True
        return False

    def _collect_all_labels(self, stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            is_label, label_name = self._is_label_def(stmt)
            if is_label and label_name:
                self.labels.add(label_name)

            if isinstance(stmt, (ast.If, ast.While, ast.For)):
                self._collect_all_labels(stmt.body)
                self._collect_all_labels(stmt.orelse)
            elif isinstance(stmt, ast.With):
                self._collect_all_labels(stmt.body)
            elif isinstance(stmt, ast.Try):
                self._collect_all_labels(stmt.body)
                self._collect_all_labels(stmt.orelse)
                self._collect_all_labels(stmt.finalbody)
                for handler in stmt.handlers:
                    self._collect_all_labels(handler.body)
            elif isinstance(stmt, ast.Match):
                for case in stmt.cases:
                    self._collect_all_labels(case.body)

    def _extract_label_blocks(self, stmts: list[ast.stmt], continuation: list[ast.stmt] | None = None) -> None:
        if continuation is None:
            continuation = []

        for i, stmt in enumerate(stmts):
            is_label, label_name = self._is_label_def(stmt)

            if is_label and label_name:
                label_code = stmts[i + 1 :] + continuation
                self.label_blocks[label_name] = label_code

            if isinstance(stmt, ast.If):
                after_if = stmts[i + 1 :] + continuation
                self._extract_label_blocks(stmt.body, after_if)
                self._extract_label_blocks(stmt.orelse, after_if)
            elif isinstance(stmt, (ast.While, ast.For)):
                after_loop = stmts[i + 1 :] + continuation
                self._extract_label_blocks(stmt.body, [stmt] + after_loop)
                self._extract_label_blocks(stmt.orelse, after_loop)
            elif isinstance(stmt, ast.With):
                after_with = stmts[i + 1 :] + continuation
                self._extract_label_blocks(stmt.body, after_with)
            elif isinstance(stmt, ast.Try):
                after_try = stmts[i + 1 :] + continuation
                self._extract_label_blocks(stmt.body, after_try)
                self._extract_label_blocks(stmt.orelse, after_try)
                self._extract_label_blocks(stmt.finalbody, after_try)
                for handler in stmt.handlers:
                    self._extract_label_blocks(handler.body, after_try)
            elif isinstance(stmt, ast.Match):
                after_match = stmts[i + 1 :] + continuation
                for case in stmt.cases:
                    self._extract_label_blocks(case.body, after_match)

    def _is_label_def(self, stmt: ast.stmt) -> tuple[bool, str | None]:
        if isinstance(stmt, ast.Assign):
            if isinstance(stmt.value, ast.Call):
                if isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "LABEL":
                    if stmt.value.args and isinstance(stmt.value.args[0], ast.Constant):
                        return True, str(stmt.value.args[0].value)
        return False, None

    def _is_goto_call(self, stmt: ast.stmt) -> tuple[bool, str | None]:
        if isinstance(stmt, ast.Assign):
            if isinstance(stmt.value, ast.Call):
                if isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "goto":
                    if stmt.value.args and isinstance(stmt.value.args[0], ast.Constant):
                        return True, str(stmt.value.args[0].value)
        return False, None

    def _create_state_machine(self, body: list[ast.stmt]) -> list[ast.stmt]:
        label_init = ast.Assign(targets=[ast.Name(id="__goto_label", ctx=ast.Store())], value=ast.Constant(value="start"), lineno=1, col_offset=0)

        cases = []

        start_body = self._transform_statements(body)
        start_body.append(ast.Break(lineno=1, col_offset=0))
        cases.append(("start", start_body))

        for label_name in sorted(self.labels):
            if label_name in self.label_blocks:
                label_body = self._transform_statements(self.label_blocks[label_name])
                label_body.append(ast.Break(lineno=1, col_offset=0))
                cases.append((label_name, label_body))

        if_chain = None
        root_if = None

        for label, case_body in cases:
            condition = ast.Compare(left=ast.Name(id="__goto_label", ctx=ast.Load()), ops=[ast.Eq()], comparators=[ast.Constant(value=label)], lineno=1, col_offset=0)

            if if_chain is None:
                if_chain = ast.If(test=condition, body=case_body, orelse=[], lineno=1, col_offset=0)
                root_if = if_chain
            else:
                new_if = ast.If(test=condition, body=case_body, orelse=[], lineno=1, col_offset=0)
                if_chain.orelse = [new_if]
                if_chain = new_if

        if if_chain is not None:
            if_chain.orelse = [ast.Break(lineno=1, col_offset=0)]

        while_loop = ast.While(test=ast.Constant(value=True), body=[root_if] if root_if else [ast.Break(lineno=1, col_offset=0)], orelse=[], lineno=1, col_offset=0)

        return [label_init, while_loop]

    def _transform_statements(self, stmts: list[ast.stmt]) -> list[ast.stmt]:
        result = []

        for stmt in stmts:
            is_label, _ = self._is_label_def(stmt)
            if is_label:
                continue

            is_goto, target = self._is_goto_call(stmt)
            if is_goto and target in self.labels:
                result.extend(
                    [
                        ast.Assign(targets=[ast.Name(id="__goto_label", ctx=ast.Store())], value=ast.Constant(value=target), lineno=stmt.lineno, col_offset=stmt.col_offset),
                        ast.Continue(lineno=stmt.lineno, col_offset=stmt.col_offset),
                    ]
                )
                continue

            transformed = self._transform_compound(stmt)
            result.append(transformed)

        return result

    def _transform_compound(self, stmt: ast.stmt) -> ast.stmt:
        if isinstance(stmt, ast.If):
            stmt.body = self._transform_statements(stmt.body)
            stmt.orelse = self._transform_statements(stmt.orelse)
        elif isinstance(stmt, ast.While):
            stmt.body = self._transform_statements(stmt.body)
            stmt.orelse = self._transform_statements(stmt.orelse)
        elif isinstance(stmt, ast.For):
            stmt.body = self._transform_statements(stmt.body)
            stmt.orelse = self._transform_statements(stmt.orelse)
        elif isinstance(stmt, ast.With):
            stmt.body = self._transform_statements(stmt.body)
        elif isinstance(stmt, ast.Try):
            stmt.body = self._transform_statements(stmt.body)
            stmt.orelse = self._transform_statements(stmt.orelse)
            stmt.finalbody = self._transform_statements(stmt.finalbody)
            for handler in stmt.handlers:
                handler.body = self._transform_statements(handler.body)

        return stmt


def to_snake_case(name: str) -> str:
    if not name:
        return name

    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
    s3 = re.sub("[^0-9a-zA-Z_]+", "_", s2)

    snake = s3.lower()
    if not snake:
        return name.lower()

    return snake


def to_pascal_case(name: str) -> str:
    if not name:
        return name

    parts = re.split("[^0-9a-zA-Z]+|_", name)
    parts = [p for p in parts if p]
    if not parts:
        return name

    return "".join(p[0].upper() + p[1:] if len(p) > 1 else p.upper() for p in parts)


class BlockType(Enum):
    NORMAL = "normal"
    CONDITIONAL = "conditional"
    LOOP = "loop"
    EXCEPTION = "exception"


@dataclass
class BasicBlock:
    id: int
    statements: list[ast.stmt] = field(default_factory=list)
    successors: list[int] = field(default_factory=list)
    predecessors: list[int] = field(default_factory=list)
    block_type: BlockType = BlockType.NORMAL
    is_entry: bool = False
    is_exit: bool = False
    terminates: bool = False

    def add_successor(self, block_id: int) -> None:
        if block_id not in self.successors:
            self.successors.append(block_id)

    def add_predecessor(self, block_id: int) -> None:
        if block_id not in self.predecessors:
            self.predecessors.append(block_id)


class ControlFlowGraph:
    def __init__(self) -> None:
        self.blocks: dict[int, BasicBlock] = {}
        self.next_block_id = 0
        self.entry_block_id: int | None = None
        self.exit_block_id: int | None = None

    def create_block(self, block_type: BlockType = BlockType.NORMAL) -> int:
        block_id = self.next_block_id
        self.next_block_id += 1
        self.blocks[block_id] = BasicBlock(id=block_id, block_type=block_type)
        return block_id

    def add_edge(self, from_id: int | None, to_id: int | None) -> None:
        if from_id in self.blocks and to_id in self.blocks:
            self.blocks[from_id].add_successor(to_id)
            self.blocks[to_id].add_predecessor(from_id)

    def get_reachable_blocks(self) -> set[int]:
        if self.entry_block_id is None:
            return set()

        reachable = set()
        stack = [self.entry_block_id]

        while stack:
            block_id = stack.pop()
            if block_id in reachable:
                continue

            reachable.add(block_id)

            if block_id in self.blocks:
                for successor_id in self.blocks[block_id].successors:
                    if successor_id not in reachable:
                        stack.append(successor_id)

        return reachable

    def get_unreachable_statements(self) -> set[ast.stmt]:
        reachable = self.get_reachable_blocks()
        unreachable_stmts = set()

        for block_id, block in self.blocks.items():
            if block_id not in reachable:
                unreachable_stmts.update(block.statements)

        return unreachable_stmts


class CFGBuilder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.cfg = ControlFlowGraph()
        self.current_block: int | None = None
        self.break_targets: list[int] = []
        self.continue_targets: list[int] = []
        self.loop_exit_blocks: list[int] = []

    def build(self, statements: list[ast.stmt]) -> ControlFlowGraph:
        if not statements:
            return self.cfg

        entry_id = self.cfg.create_block()
        self.cfg.entry_block_id = entry_id
        self.cfg.blocks[entry_id].is_entry = True
        self.current_block = entry_id

        self._process_statements(statements)

        exit_id = self.cfg.create_block()
        self.cfg.exit_block_id = exit_id
        self.cfg.blocks[exit_id].is_exit = True

        if self.current_block is not None and not self.cfg.blocks[self.current_block].terminates:
            self.cfg.add_edge(self.current_block, exit_id)

        return self.cfg

    def _process_statements(self, statements: list[ast.stmt]) -> None:
        for stmt in statements:
            if self.current_block is None:
                unreachable_id = self.cfg.create_block()
                self.current_block = unreachable_id

            self.visit(stmt)

            if self._is_terminator(stmt):
                self.cfg.blocks[self.current_block].terminates = True
                self.current_block = None

    def _is_terminator(self, node: ast.stmt) -> bool:
        return isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue))

    def _add_statement(self, stmt: ast.stmt) -> None:
        if self.current_block is not None:
            self.cfg.blocks[self.current_block].statements.append(stmt)

    def visit_If(self, node: ast.If) -> None:
        self._add_statement(node)

        if isinstance(node.test, ast.Constant) and isinstance(node.test.value, bool):
            if node.test.value:
                self._process_statements(node.body)
            else:
                self._process_statements(node.orelse)
            return

        if_block = self.current_block

        then_entry = self.cfg.create_block(BlockType.CONDITIONAL)
        else_entry = self.cfg.create_block(BlockType.CONDITIONAL) if node.orelse else None
        merge_block = self.cfg.create_block()

        self.cfg.add_edge(if_block, then_entry)
        self.current_block = then_entry
        self._process_statements(node.body)
        if self.current_block is not None:
            self.cfg.add_edge(self.current_block, merge_block)

        if node.orelse:
            assert else_entry
            self.cfg.add_edge(if_block, else_entry)
            self.current_block = else_entry
            self._process_statements(node.orelse)
            if self.current_block is not None:
                self.cfg.add_edge(self.current_block, merge_block)
        else:
            self.cfg.add_edge(if_block, merge_block)

        self.current_block = merge_block

    def visit_While(self, node: ast.While) -> None:
        self._add_statement(node)

        if isinstance(node.test, ast.Constant) and node.test.value is False:
            self._process_statements(node.orelse)
            return

        entry_block = self.current_block

        loop_header = self.cfg.create_block(BlockType.LOOP)
        loop_body = self.cfg.create_block(BlockType.LOOP)
        loop_exit = self.cfg.create_block()

        self.cfg.add_edge(entry_block, loop_header)
        self.cfg.add_edge(loop_header, loop_body)
        self.cfg.add_edge(loop_header, loop_exit)

        self.break_targets.append(loop_exit)
        self.continue_targets.append(loop_header)
        self.loop_exit_blocks.append(loop_exit)

        self.current_block = loop_body
        self._process_statements(node.body)
        if self.current_block is not None:
            self.cfg.add_edge(self.current_block, loop_header)

        self.break_targets.pop()
        self.continue_targets.pop()
        self.loop_exit_blocks.pop()

        self.current_block = loop_exit
        self._process_statements(node.orelse)

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self._add_statement(node)

        entry_block = self.current_block

        loop_header = self.cfg.create_block(BlockType.LOOP)
        loop_body = self.cfg.create_block(BlockType.LOOP)
        loop_exit = self.cfg.create_block()

        assert entry_block
        self.cfg.add_edge(entry_block, loop_header)
        self.cfg.add_edge(loop_header, loop_body)
        self.cfg.add_edge(loop_header, loop_exit)

        self.break_targets.append(loop_exit)
        self.continue_targets.append(loop_header)
        self.loop_exit_blocks.append(loop_exit)

        self.current_block = loop_body
        self._process_statements(node.body)
        if self.current_block is not None:
            self.cfg.add_edge(self.current_block, loop_header)

        self.break_targets.pop()
        self.continue_targets.pop()
        self.loop_exit_blocks.pop()

        self.current_block = loop_exit
        self._process_statements(node.orelse)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        self._add_statement(node)

        entry_block = self.current_block

        try_block = self.cfg.create_block(BlockType.EXCEPTION)
        except_merge = self.cfg.create_block(BlockType.EXCEPTION)
        else_block = self.cfg.create_block(BlockType.EXCEPTION) if node.orelse else None
        final_block = self.cfg.create_block(BlockType.EXCEPTION) if node.finalbody else None
        exit_block = self.cfg.create_block()

        assert entry_block
        self.cfg.add_edge(entry_block, try_block)
        self.current_block = try_block
        self._process_statements(node.body)

        if self.current_block is not None:
            if else_block:
                self.cfg.add_edge(self.current_block, else_block)
            elif final_block:
                self.cfg.add_edge(self.current_block, final_block)
            else:
                self.cfg.add_edge(self.current_block, exit_block)

        for handler in node.handlers:
            handler_block = self.cfg.create_block(BlockType.EXCEPTION)
            self.cfg.add_edge(try_block, handler_block)
            self.current_block = handler_block
            self._process_statements(handler.body)
            if self.current_block is not None:
                self.cfg.add_edge(self.current_block, except_merge)

        if final_block:
            self.cfg.add_edge(except_merge, final_block)
        else:
            self.cfg.add_edge(except_merge, exit_block)

        if else_block:
            self.current_block = else_block
            self._process_statements(node.orelse)
            if self.current_block is not None:
                if final_block:
                    self.cfg.add_edge(self.current_block, final_block)
                else:
                    self.cfg.add_edge(self.current_block, exit_block)

        if final_block:
            self.current_block = final_block
            self._process_statements(node.finalbody)
            if self.current_block is not None:
                self.cfg.add_edge(self.current_block, exit_block)

        self.current_block = exit_block

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.visit_Try(node)

    def visit_With(self, node: ast.With) -> None:
        self._add_statement(node)
        self._process_statements(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._add_statement(node)
        self._process_statements(node.body)

    def visit_Match(self, node: ast.Match) -> None:
        self._add_statement(node)

        entry_block = self.current_block
        merge_block = self.cfg.create_block()

        for case in node.cases:
            case_block = self.cfg.create_block()
            assert entry_block
            self.cfg.add_edge(entry_block, case_block)
            self.current_block = case_block
            self._process_statements(case.body)
            if self.current_block is not None:
                self.cfg.add_edge(self.current_block, merge_block)

        self.current_block = merge_block

    def visit_Return(self, node: ast.Return) -> None:
        self._add_statement(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self._add_statement(node)

    def visit_Break(self, node: ast.Break) -> None:
        self._add_statement(node)
        if self.break_targets and self.current_block is not None:
            self.cfg.add_edge(self.current_block, self.break_targets[-1])

    def visit_Continue(self, node: ast.Continue) -> None:
        self._add_statement(node)
        if self.continue_targets and self.current_block is not None:
            self.cfg.add_edge(self.current_block, self.continue_targets[-1])

    def generic_visit(self, node) -> None:
        if isinstance(node, ast.stmt):
            self._add_statement(node)


class DeadCodeEliminator(ast.NodeTransformer):

    def __init__(self) -> None:
        self.unreachable_stmts: set[ast.stmt] = set()

    def _analyze_block(self, statements: list[ast.stmt]) -> set[ast.stmt]:
        if not statements:
            return set()

        builder = CFGBuilder()
        cfg = builder.build(statements)
        return cfg.get_unreachable_statements()

    def _filter_statements(self, statements: list[ast.stmt]) -> list[ast.stmt]:
        unreachable = self._analyze_block(statements)

        filtered = [s for s in statements if s not in unreachable]

        if not filtered and statements:
            filtered = [ast.Pass()]

        return cast(list[ast.stmt], filtered)

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        return node

    def visit_If(self, node: ast.If) -> ast.AST | None:
        self.generic_visit(node)

        if isinstance(node.test, ast.Constant) and isinstance(node.test.value, bool):
            if node.test.value:
                return cast(ast.AST, node.body if len(node.body) != 1 else node.body[0])
            else:
                if node.orelse:
                    return cast(ast.AST, node.orelse if len(node.orelse) != 1 else node.orelse[0])
                else:
                    return ast.Pass()

        node.body = self._filter_statements(node.body)
        node.orelse = self._filter_statements(node.orelse)
        return node

    def visit_While(self, node: ast.While) -> ast.AST | None:
        self.generic_visit(node)

        if isinstance(node.test, ast.Constant) and node.test.value is False:
            if node.orelse:
                return cast(ast.AST, node.orelse if len(node.orelse) != 1 else node.orelse[0])
            else:
                return ast.Pass()

        node.body = self._filter_statements(node.body)
        node.orelse = self._filter_statements(node.orelse)
        return node

    def visit_For(self, node: ast.For) -> ast.For:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        node.orelse = self._filter_statements(node.orelse)
        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AsyncFor:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        node.orelse = self._filter_statements(node.orelse)
        return node

    def visit_Try(self, node: ast.Try) -> ast.Try:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        node.orelse = self._filter_statements(node.orelse)
        node.finalbody = self._filter_statements(node.finalbody)
        for handler in node.handlers:
            handler.body = self._filter_statements(handler.body)
        return node

    def visit_TryStar(self, node: ast.TryStar) -> ast.TryStar:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        node.orelse = self._filter_statements(node.orelse)
        node.finalbody = self._filter_statements(node.finalbody)
        for handler in node.handlers:
            handler.body = self._filter_statements(handler.body)
        return node

    def visit_With(self, node: ast.With) -> ast.With:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        return node

    def visit_AsyncWith(self, node: ast.AsyncWith) -> ast.AsyncWith:
        self.generic_visit(node)
        node.body = self._filter_statements(node.body)
        return node

    def visit_Match(self, node: ast.Match) -> ast.Match:
        self.generic_visit(node)
        for case in node.cases:
            case.body = self._filter_statements(case.body)
        return node


class NormalizeIdentifiers(ast.NodeTransformer):
    def __init__(self) -> None:
        super().__init__()
        self.scope_stack: list[dict[str, str]] = [{}]
        self.class_attr_stack: list[dict[str, str] | None] = [None]

    def _push_scope(self, class_attr_map: dict[str, str] | None = None) -> None:
        self.scope_stack.append({})
        self.class_attr_stack.append(class_attr_map)

    def _pop_scope(self) -> None:
        self.scope_stack.pop()
        self.class_attr_stack.pop()

    def _current_scope_map(self) -> dict[str, str]:
        return self.scope_stack[-1]

    def _lookup_name(self, name: str) -> str | None:
        for scope in reversed(self.scope_stack):
            if name in scope:
                return scope[name]

        return None

    def _current_class_attr_map(self) -> dict[str, str] | None:
        return self.class_attr_stack[-1]

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self._push_scope(class_attr_map=None)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        old_name = node.name
        new_name = to_pascal_case(old_name)
        if new_name != old_name:
            self._current_scope_map()[old_name] = new_name
            node.name = new_name

        class_attr_map: dict[str, str] = {}
        self._push_scope(class_attr_map=class_attr_map)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        old_name = node.name
        new_name = to_snake_case(old_name)
        if new_name != old_name:
            self._current_scope_map()[old_name] = new_name
            node.name = new_name

        self._push_scope(class_attr_map=None)
        self._rename_args(node.args)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        old_name = node.name
        new_name = to_snake_case(old_name)

        if new_name != old_name:
            self._current_scope_map()[old_name] = new_name
            node.name = new_name

        self._push_scope(class_attr_map=None)
        self._rename_args(node.args)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def _rename_args(self, args: ast.arguments) -> None:
        for a in args.posonlyargs + args.args + ([] if args.vararg is None else [args.vararg]) + args.kwonlyargs + ([] if args.kwarg is None else [args.kwarg]):
            if isinstance(a, ast.arg):
                old = a.arg
                new = to_snake_case(old)
                if new != old:
                    self._current_scope_map()[old] = new
                    a.arg = new

    def visit_Lambda(self, node: ast.Lambda) -> ast.Lambda:
        self._push_scope(class_attr_map=None)
        self._rename_args(node.args)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def visit_Call(self, node: ast.Call) -> ast.Call:
        name = cast(ast.Name, node.func).id
        node.func = ast.Name(to_snake_case(name))
        self.generic_visit(node)

        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
        self.generic_visit(node)

        for t in node.targets:
            self._handle_assignment_target(t)

        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        self.generic_visit(node)
        self._handle_assignment_target(node.target)

        return node

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AugAssign:
        self.generic_visit(node)
        self._handle_assignment_target(node.target)

        return node

    def visit_NamedExpr(self, node: ast.NamedExpr) -> ast.NamedExpr:
        self.generic_visit(node)
        self._handle_assignment_target(node.target)

        return node

    def _handle_assignment_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
            old = target.id
            new = to_snake_case(old)
            if new != old:
                self._current_scope_map()[old] = new
                target.id = new
        elif isinstance(target, ast.Attribute):
            if isinstance(target.value, ast.Name) and target.value.id == "self":
                old_attr = target.attr
                new_attr = to_snake_case(old_attr)
                if new_attr != old_attr:
                    if (x := self._current_class_attr_map()) is not None:
                        x[old_attr] = new_attr
                    target.attr = new_attr
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._handle_assignment_target(elt)
        elif isinstance(target, ast.Starred):
            self._handle_assignment_target(target.value)

    def visit_For(self, node: ast.For) -> ast.For:
        self.generic_visit(node)
        self._handle_assignment_target(node.target)

        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AsyncFor:
        self.generic_visit(node)
        self._handle_assignment_target(node.target)

        return node

    def visit_With(self, node: ast.With) -> ast.With:
        self.generic_visit(node)
        for item in node.items:
            if item.optional_vars is not None:
                self._handle_assignment_target(item.optional_vars)

        return node

    def visit_AsyncWith(self, node: ast.AsyncWith) -> ast.AsyncWith:
        self.generic_visit(node)
        for item in node.items:
            if item.optional_vars is not None:
                self._handle_assignment_target(item.optional_vars)

        return node

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.ExceptHandler:
        self.generic_visit(node)
        if node.name is not None:
            old = node.name
            new = to_snake_case(old)
            if new != old:
                self._current_scope_map()[old] = new
                node.name = new

        return node

    def visit_comprehension(self, node: ast.comprehension) -> ast.comprehension:
        self.generic_visit(node)
        self._handle_assignment_target(node.target)

        return node

    def visit_ListComp(self, node: ast.ListComp) -> ast.ListComp:
        self._push_scope(class_attr_map=None)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def visit_SetComp(self, node: ast.SetComp) -> ast.SetComp:
        self._push_scope(class_attr_map=None)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def visit_DictComp(self, node: ast.DictComp) -> ast.DictComp:
        self._push_scope(class_attr_map=None)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> ast.GeneratorExp:
        self._push_scope(class_attr_map=None)
        self.generic_visit(node)
        self._pop_scope()

        return node

    def visit_Global(self, node: ast.Global) -> ast.Global:
        return node

    def visit_Nonlocal(self, node: ast.Nonlocal) -> ast.Nonlocal:
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        mapped = self._lookup_name(node.id)
        if mapped is not None:
            return ast.copy_location(ast.Name(id=mapped, ctx=node.ctx), node)

        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            for class_map in reversed(self.class_attr_stack):
                if class_map is None:
                    continue
                if node.attr in class_map:
                    node.attr = class_map[node.attr]
                    break

        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        return node

    def visit_Import(self, node: ast.Import) -> ast.Import:
        for alias in node.names:
            if alias.asname is not None:
                old = alias.asname
                new = to_snake_case(old)
                if new != old:
                    self._current_scope_map()[old] = new
                    alias.asname = new
            else:
                old = alias.name.split(".")[0]
                new = to_snake_case(old)
                if new != old:
                    self._current_scope_map()[old] = new

        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        for alias in node.names:
            if alias.name == "*":
                continue
            if alias.asname is not None:
                old = alias.asname
                new = to_snake_case(old)
                if new != old:
                    self._current_scope_map()[old] = new
                    alias.asname = new
            else:
                old = alias.name
                new = to_snake_case(old)
                if new != old:
                    self._current_scope_map()[old] = new

        return node

    def visit_MatchAs(self, node: ast.MatchAs) -> ast.MatchAs:
        self.generic_visit(node)
        if node.name is not None:
            old = node.name
            new = to_snake_case(old)
            if new != old:
                self._current_scope_map()[old] = new
                node.name = new

        return node

    def visit_MatchStar(self, node: ast.MatchStar) -> ast.MatchStar:
        self.generic_visit(node)
        if node.name is not None:
            old = node.name
            new = to_snake_case(old)
            if new != old:
                self._current_scope_map()[old] = new
                node.name = new

        return node

    def visit_MatchMapping(self, node: ast.MatchMapping) -> ast.MatchMapping:
        self.generic_visit(node)
        if node.rest is not None:
            old = node.rest
            new = to_snake_case(old)
            if new != old:
                self._current_scope_map()[old] = new
                node.rest = new

        return node

    def visit_Match(self, node: ast.Match) -> ast.Match:
        self.generic_visit(node)

        return node

    def visit_TypeAlias(self, node: ast.TypeAlias) -> ast.TypeAlias:
        old_name = node.name.id if isinstance(node.name, ast.Name) else None

        self.generic_visit(node)

        if old_name is not None:
            new_name = to_pascal_case(old_name)
            if new_name != old_name and isinstance(node.name, ast.Name):
                self._current_scope_map()[old_name] = new_name
                node.name.id = new_name

        return node

    def visit_TypeVar(self, node: ast.expr) -> ast.expr:
        self.generic_visit(node)

        return node


class RemoveTypeAnnotations(ast.NodeTransformer):
    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        node.returns = None
        node.type_comment = None

        self._strip_args_annotations(node.args)
        self.generic_visit(node)

        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        node.returns = None
        node.type_comment = None
        self._strip_args_annotations(node.args)
        self.generic_visit(node)

        return node

    def _strip_args_annotations(self, args: ast.arguments) -> None:
        for a in args.posonlyargs + args.args + args.kwonlyargs:
            if isinstance(a, ast.arg):
                a.annotation = None
                a.type_comment = None
        if args.vararg:
            args.vararg.annotation = None
        if args.kwarg:
            args.kwarg.annotation = None

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        self.generic_visit(node)
        if node.value is None:
            return None

        new_assign = ast.Assign(targets=[node.target], value=node.value)

        return ast.copy_location(new_assign, node)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.annotation = None
        node.type_comment = None

        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        return cast(ast.Attribute, self.generic_visit(node))

    def visit_Assign(self, node: ast.Assign) -> ast.Assign:
        node.type_comment = None
        return cast(ast.Assign, self.generic_visit(node))
