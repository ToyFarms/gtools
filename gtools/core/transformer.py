import ast


class GotoResolver(ast.NodeTransformer):
    def __init__(self):
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

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self._collect_all_labels(node.body)
        self._extract_label_blocks(node.body)
        transformed_body = self._create_state_machine(node.body)
        node.body = transformed_body
        return node

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
