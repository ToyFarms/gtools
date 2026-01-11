import ast
from dataclasses import dataclass
import re
from typing import Any, cast
from pycparser.c_lexer import CLexer

DEBUG = 0


@dataclass
class Token:
    type: str
    value: Any
    lineno: int
    lexpos: int


# NOTE: the operation name is probably mostly wrong
OP_DEF = {
    "LPAREN": (160, 0, "postfix_call"),
    "LBRACKET": (160, 0, "postfix_index"),
    "DOT": (160, 0, "postfix_member"),
    "ARROW": (160, 0, "postfix_member"),
    "PLUSPLUS": (160, 0, "postfix_inc"),
    "MINUSMINUS": (160, 0, "postfix_dec"),
    "TIMES": (120, 119, "binary_left"),
    "DIVIDE": (120, 119, "binary_left"),
    "MOD": (120, 119, "binary_left"),
    "PLUS": (110, 109, "binary_left"),
    "MINUS": (110, 109, "binary_left"),
    "LSHIFT": (100, 99, "binary_left"),
    "RSHIFT": (100, 99, "binary_left"),
    "LT": (90, 89, "binary_left"),
    "LE": (90, 89, "binary_left"),
    "GT": (90, 89, "binary_left"),
    "GE": (90, 89, "binary_left"),
    "EQ": (80, 79, "binary_left"),
    "EQUALS": (80, 79, "binary_left"),
    "EQ": (80, 79, "binary_left"),
    "NE": (80, 79, "binary_left"),
    "AND": (70, 69, "binary_left"),
    "AMP": (70, 69, "binary_left"),
    "CARET": (60, 59, "binary_left"),
    "PIPE": (50, 49, "binary_left"),
    "LAND": (40, 39, "binary_left"),
    "LOR": (30, 29, "binary_left"),
    "CONDOP": (20, 19, "ternary"),
    "COLON": (19, 0, "ternary_colon"),
    "ASSIGN": (10, 9, "assign"),
    "PLUSEQUAL": (10, 9, "assign"),
    "MINUSEQUAL": (10, 9, "assign"),
    "TIMESEQUAL": (10, 9, "assign"),
    "DIVEQUAL": (10, 9, "assign"),
    "MODEQUAL": (10, 9, "assign"),
    "CASE": (0, -1, "case"),
    "COMMA": (0, -1, "comma"),
}


class CParser:
    def __init__(self, tokens: list[Token], code: str | None = None) -> None:
        self._tokens = tokens
        self._code = code
        self.i = 0

    def next(self) -> Token:
        if self.i > len(self._tokens) - 1:
            raise IndexError("out of bound read")

        i = self.i
        self.i += 1
        # print(f"NEXT: {self._tokens[i]}")
        return self._tokens[i]

    def peek(self, offset: int = 0) -> Token:
        i = self.i + offset
        if i > len(self._tokens) - 1:
            return Token("", None, -1, -1)

        return self._tokens[i]

    def expect(self, type: str) -> None:
        if self.peek().type != type:
            raise ValueError(f"type mismatch: expected {type} but got {self.peek().type}")

    def expect_and_next(self, type: str) -> Token:
        if self.peek().type != type:
            raise ValueError(f"type mismatch: expected {type} but got {self.peek().type}")

        return self.next()

    def has_next(self) -> bool:
        return len(self._tokens) - (self.i + 1) > 0

    def read_scope(self) -> list[Token]:
        brace = int(self.next().type == "LBRACE")
        acc: list[Token] = []
        while brace > 0:
            if self.peek().type == "LBRACE":
                brace += 1
            elif self.peek().type == "RBRACE":
                brace -= 1

            if brace == 0:
                if self.has_next():
                    self.next()
                break

            acc.append(self.next())

        return acc

    def _parse_declarator(self):
        pointer_level = 0
        while self.peek().type == "TIMES":
            self.next()
            pointer_level += 1

        id_tok = self.next()
        if id_tok.type != "ID":
            raise ValueError(f"expected identifier in declarator, got {id_tok.type}")

        array_dims: list[ast.expr | None] = []
        while self.peek().type == "LBRACKET":
            self.next()
            if self.peek().type == "RBRACKET":
                self.next()
                array_dims.append(None)
            else:
                dim_expr = self.parse_expr(0)
                array_dims.append(dim_expr)
                self.expect_and_next("RBRACKET")

        return id_tok, pointer_level, array_dims

    def _parse_brace_initializer(self) -> ast.expr:
        self.expect_and_next("LBRACE")
        elements: list[ast.expr] = []

        while True:
            if self.peek().type == "RBRACE":
                self.next()
                break

            if self.peek().type == "LBRACE":
                nested = self._parse_brace_initializer()
                elements.append(nested)
            else:
                elem = self.parse_expr(0)
                elements.append(elem)

            if self.peek().type == "COMMA":
                self.next()
                if self.peek().type == "RBRACE":
                    continue
                else:
                    continue
            elif self.peek().type == "RBRACE":
                continue
            else:
                raise ValueError(f"unexpected token in brace initializer: {self.peek().type}")

        return ast.List(elts=elements, ctx=ast.Load())

    def parse_variable_decl(self) -> ast.stmt:
        type_tokens: list[Token] = [self.next()]
        TYPE_TOKS = {
            "UNSIGNED",
            "SIGNED",
            "INT",
            "CHAR",
            "FLOAT",
            "DOUBLE",
            "VOID",
            "TYPE_NAME",
            "STRUCT",
            "UNION",
            "ENUM",
            "CONST",
            "VOLATILE",
            "LONG",
            "SHORT",
            "SIGNED",
            "UNSIGNED",
        }
        while self.peek().type in TYPE_TOKS:
            type_tokens.append(self.next())

        id_tok, pointer_level, array_dims = self._parse_declarator()
        var_name = id_tok.value

        initializer: ast.expr | None = None
        if self.peek().type in ("ASSIGN", "EQUALS"):
            self.next()
            if self.peek().type == "LBRACE":
                initializer = self._parse_brace_initializer()
            else:
                initializer = self.parse_expr(0)
        elif self.peek().type == "LBRACE":
            initializer = self._parse_brace_initializer()

        self.expect_and_next("SEMI")

        simple_scalar = pointer_level == 0 and len(array_dims) == 0

        if simple_scalar:
            if initializer is None:
                return ast.Assign(targets=[ast.Name(var_name, ast.Store())], value=ast.Constant(None))
            else:
                return ast.Assign(targets=[ast.Name(var_name, ast.Store())], value=initializer)

        type_str = " ".join(tok.type for tok in type_tokens)
        dims_elts: list[ast.expr] = []
        for d in array_dims:
            if d is None:
                dims_elts.append(ast.Constant(None))
            else:
                dims_elts.append(d)

        declare_args = [
            ast.Constant(type_str),
            ast.Constant(var_name),
            ast.Constant(pointer_level),
            ast.List(elts=dims_elts, ctx=ast.Load()),
            initializer if initializer is not None else ast.Constant(None),
        ]

        declare_call = ast.Call(func=ast.Name(id="declare", ctx=ast.Load()), args=declare_args, keywords=[])
        return ast.Assign(targets=[ast.Name(var_name, ast.Store())], value=declare_call)

    def parse_if(self) -> ast.stmt:
        self.expect_and_next("IF")
        self.expect_and_next("LPAREN")
        cond = self.parse_expr()
        self.expect_and_next("RPAREN")

        if self.peek().type == "LBRACE":
            body_tokens = self.read_scope()
            if not body_tokens:
                return ast.Pass()
            sub = CParser(body_tokens)
            body = sub.parse().body
        else:
            body = [self.parse_stmt()]

        orelse: list[ast.stmt] = []
        if self.peek().type == "ELSE":
            self.next()
            if self.peek().type == "LBRACE":
                body_tokens = self.read_scope()
                if not body_tokens:
                    return ast.Pass()
                sub = CParser(body_tokens)
                orelse = sub.parse().body
            else:
                orelse = [self.parse_stmt()]

        return ast.If(test=cond, body=body, orelse=orelse)

    def parse_return(self) -> ast.stmt:
        self.expect_and_next("RETURN")
        retval = self.parse_expr()
        self.expect_and_next("SEMI")

        return ast.Return(value=retval)

    def parse_funcall(self) -> ast.expr:
        ident = self.next()
        self.expect_and_next("LPAREN")
        args: list[ast.expr] = []
        self.parse_expr()
        while self.peek().type != "RPAREN":
            args.append(self.parse_expr())
            if self.peek().type == "COMMA":
                self.next()
        self.expect_and_next("SEMI")

        return ast.Call(ident.value, args)

    def get_op_info(self, token_type: str) -> tuple[int, int, str]:
        return OP_DEF.get(token_type, (-1, -1, "none"))

    def parse_expr(self, min_bp: int = 0) -> ast.expr:
        tok = self.next()
        left = self.nud(tok)
        if DEBUG:
            print("nud: ", ast.dump(left))

        while True:
            look = self.peek()
            lbp, rbp, kind = self.get_op_info(look.type)
            if DEBUG:
                print("expr: ", look.type, lbp, rbp, kind)

            if kind in ("ternary_colon", "comma"):
                break

            if lbp < min_bp or kind == "none":
                break

            op_tok = self.next()
            left = self.led(op_tok, left, rbp)

        return left

    def _lookahead_is_type_name(self, start_i: int) -> bool:
        i = start_i
        depth = 0
        saw_type_token = False
        TYPE_TOKS = {"UNSIGNED", "SIGNED", "INT", "CHAR", "FLOAT", "DOUBLE", "VOID", "TYPE_NAME", "STRUCT", "UNION", "ENUM", "CONST", "VOLATILE"}
        while i < len(self._tokens):
            tt = self._tokens[i].type
            if tt == "LPAREN":
                depth += 1
            elif tt == "RPAREN":
                if depth == 0:
                    break
                depth -= 1
                if depth < 0:
                    break
            else:
                if tt in TYPE_TOKS:
                    saw_type_token = True
                elif tt == "TIMES":
                    saw_type_token = True
            i += 1

        return saw_type_token

    def nud(self, tok: Token) -> ast.expr:
        t = tok.type
        v = tok.value

        if t == "LPAREN":
            if self._lookahead_is_type_name(self.i):
                depth = 1
                while depth > 0:
                    nxt = self.next()
                    if nxt.type == "LPAREN":
                        depth += 1
                    elif nxt.type == "RPAREN":
                        depth -= 1
                right = self.parse_expr(130)
                return ast.Call(func=ast.Name(id="cast", ctx=ast.Load()), args=[right])
            else:
                expr = self.parse_expr(0)
                self.expect_and_next("RPAREN")
                return expr

        if t == "ID":
            return ast.Name(str(v))
        if t in ("INT_CONST_DEC", "INT_CONST_HEX", "INT_CONST_OCT"):
            return ast.Constant(int(v, 0))
        if t == "FLOAT_CONST":
            return ast.Constant(float(v))
        if t == "STRING_LITERAL":
            return ast.Constant(str(v))
        if t == "CHAR_CONST":
            return ast.Constant(str(v))
        if t == "CASE":
            right = cast(ast.pattern, self.parse_expr(0))
            return cast(ast.expr, ast.match_case(pattern=right, body=[]))

        # unary
        if t in ("PLUS", "MINUS", "LNOT", "TILDE", "STAR", "AMP", "INCREMENT", "DECREMENT", "SIZEOF", "AND"):
            right = self.parse_expr(130)
            op_map = {
                "PLUS": ast.UAdd(),
                "MINUS": ast.USub(),
                "LNOT": ast.Not(),
                "TILDE": ast.Invert(),
                "STAR": "deref",
                "AND": "ref",
                "INCREMENT": "inc",
                "DECREMENT": "dec",
                "SIZEOF": "sizeof",
            }
            op = op_map.get(t)
            if isinstance(op, ast.unaryop):
                return ast.UnaryOp(op=op, operand=right)
            elif isinstance(op, str):
                return ast.Call(ast.Name(op), args=[right])

        assert False, f"unhandled token: {tok}"

    def led(self, op_tok: Token, left: ast.expr, rbp: int) -> ast.expr:
        t = op_tok.type
        v = op_tok.value

        if t == "LPAREN":
            args: list[ast.expr] = []
            if self.peek().type != "RPAREN":
                while True:
                    args.append(self.parse_expr(0))
                    if self.peek().type == "COMMA":
                        self.next()
                        continue
                    break
            self.expect_and_next("RPAREN")
            return ast.Call(left, args)

        if t == "LBRACKET":
            idx = self.parse_expr(0)
            self.expect_and_next("RBRACKET")
            return ast.Subscript(left, idx)

        if t in ("DOT", "ARROW"):
            fld = self.expect_and_next("ID")
            return ast.Attribute(left, fld.value)

        if t == "INCREMENT_POST":
            return ast.Call(ast.Name("postfix_inc"), args=[left])
        if t == "DECREMENT_POST":
            return ast.Call(ast.Name("postfix_dec"), args=[left])

        _, _, kind = self.get_op_info(t)
        if kind == "binary_left":
            binop_map = {
                "TIMES": ast.Mult,
                "DIVIDE": ast.Div,
                "MOD": ast.Mod,
                "PLUS": ast.Add,
                "MINUS": ast.Sub,
                "LSHIFT": ast.LShift,
                "RSHIFT": ast.RShift,
                "AND": ast.BitAnd,
                "CARET": ast.BitXor,
                "PIPE": ast.BitOr,
            }

            cmp_map = {
                "LT": ast.Lt,
                "LE": ast.LtE,
                "GT": ast.Gt,
                "GE": ast.GtE,
                "EQUALS": ast.Eq,
                "EQ": ast.Eq,
                "NE": ast.NotEq,
            }

            if t == "LAND":
                right = self.parse_expr(rbp)
                return ast.BoolOp(op=ast.And(), values=[left, right])
            if t == "LOR":
                right = self.parse_expr(rbp)
                return ast.BoolOp(op=ast.Or(), values=[left, right])

            if t in cmp_map:
                right = self.parse_expr(rbp)
                cmp_op = cmp_map[t]()
                return ast.Compare(left=left, ops=[cmp_op], comparators=[right])

            if t in binop_map:
                right = self.parse_expr(rbp)
                bin_op = binop_map[t]()
                return ast.BinOp(left=left, op=bin_op, right=right)

            fallback_symbol_to_ast = {
                "+": ast.Add,
                "-": ast.Sub,
                "*": ast.Mult,
                "/": ast.Div,
                "%": ast.Mod,
                "<<": ast.LShift,
                ">>": ast.RShift,
                "&": ast.BitAnd,
                "^": ast.BitXor,
                "|": ast.BitOr,
            }
            op_sym = v if v is not None else t
            if op_sym in fallback_symbol_to_ast:
                right = self.parse_expr(rbp)
                return ast.BinOp(left=left, op=fallback_symbol_to_ast[op_sym](), right=right)

            right = self.parse_expr(rbp)
            func_name = f"op_{t.lower()}"
            return ast.Call(func=ast.Name(id=func_name, ctx=ast.Load()), args=[left, right], keywords=[])

        if kind == "assign":
            assign_aug_map: dict[str, object] = {
                "PLUSEQ": ast.Add,
                "MINUSEQ": ast.Sub,
                "TIMESEQ": ast.Mult,
                "DIVEQ": ast.Div,
                "MODEQ": ast.Mod,
                "LSHIFTEQ": ast.LShift,
                "RSHIFTEQ": ast.RShift,
                "ANDEQ": ast.BitAnd,
                "XOREQ": ast.BitXor,
                "OREQ": ast.BitOr,
            }

            if t == "ASSIGN":
                right = self.parse_expr(rbp)
                return ast.Call(ast.Name("assign"), args=[left, right])

            if t in assign_aug_map:
                right = self.parse_expr(rbp)
                return ast.Call(ast.Name(t.lower()), args=[left, right])

            right = self.parse_expr(rbp)
            return ast.Call(
                func=ast.Name(id="assign_op", ctx=ast.Load()),
                args=[ast.Constant(value=t), left, right],
            )

        if kind == "ternary":
            true_expr = self.parse_expr(0)
            self.expect_and_next("COLON")
            false_expr = self.parse_expr(rbp)
            return ast.IfExp(test=left, body=true_expr, orelse=false_expr)

        if kind == "comma":
            right = self.parse_expr(rbp)
            return ast.Call(func=ast.Name(id="comma", ctx=ast.Load()), args=[left, right], keywords=[])

        assert False, f"unhandled led: op={op_tok}, left={ast.dump(left)}"

    def parse_stmt(self) -> ast.stmt:
        if DEBUG:
            print(
                "parse_stmt peek:",
                self.peek().type,
                self.peek().value,
                "[" + self._code[self.peek().lexpos : self.peek().lexpos + 200].replace("\n", "\\n") + "]" if self._code else "",
            )

        def looks_like_declaration() -> bool:
            if self.peek().type in {"INT", "VOID", "FLOAT", "DOUBLE", "CHAR", "STRUCT", "UNION", "ENUM", "TYPE_NAME", "CONST", "VOLATILE", "SIGNED", "UNSIGNED"}:
                return True
            return self._lookahead_is_type_name(self.i)

        tok_type = self.peek().type

        match tok_type:
            case "INT" | "VOID" | "FLOAT" | "DOUBLE" | "CHAR" | "STRUCT" | "UNION" | "ENUM" | "CONST" | "VOLATILE" | "SIGNED" | "UNSIGNED":
                return self.parse_variable_decl()

            case "ID":
                if self.peek(1).type == "COLON":
                    label = self.next()
                    self.expect_and_next("COLON")
                    return ast.Assign(
                        targets=[ast.Name("_", ast.Store())],
                        value=ast.Call(func=ast.Name("LABEL", ast.Load()), args=[ast.Constant(label.value)], keywords=[]),
                    )
                elif self.peek(1).type in ("EQUALS", "EQ"):
                    assign = cast(ast.Compare, self.parse_expr())
                    self.expect_and_next("SEMI")
                    return ast.Assign([assign.left], assign.comparators[0])

                if looks_like_declaration():
                    return self.parse_variable_decl()
            case "IF":
                return self.parse_if()
            case "RETURN":
                return self.parse_return()
            case "GOTO":
                self.expect_and_next("GOTO")
                label = self.next()
                self.expect_and_next("SEMI")
                return ast.Assign(
                    targets=[ast.Name("_", ast.Store())],
                    value=ast.Call(func=ast.Name("goto", ast.Load()), args=[ast.Constant(label.value)], keywords=[]),
                )
            case "LBRACE":
                body_tokens = self.read_scope()
                if not body_tokens:
                    return ast.Pass()
                sub = CParser(body_tokens)
                return ast.With(items=[], body=sub.parse().body)
            case "BREAK":
                self.next()
                self.expect_and_next("SEMI")
                return ast.Break()
            case "CONTINUE":
                self.next()
                self.expect_and_next("SEMI")
                return ast.Continue()
            case "WHILE":
                self.expect_and_next("WHILE")
                self.expect_and_next("LPAREN")
                cond = self.parse_expr()
                self.expect_and_next("RPAREN")
                if self.peek().type == "LBRACE":
                    body_tokens = self.read_scope()
                    if not body_tokens:
                        return ast.Pass()
                    sub = CParser(body_tokens)
                    body = sub.parse().body
                else:
                    body = [self.parse_stmt()]
                return ast.While(test=cond, body=body, orelse=[])
            case "DO":
                self.expect_and_next("DO")
                if self.peek().type == "LBRACE":
                    body_tokens = self.read_scope()
                    if not body_tokens:
                        return ast.Pass()
                    sub = CParser(body_tokens)
                    body = sub.parse().body
                else:
                    body = [self.parse_stmt()]
                self.expect_and_next("WHILE")
                self.expect_and_next("LPAREN")
                cond = self.parse_expr()
                self.expect_and_next("RPAREN")
                self.expect_and_next("SEMI")
                break_if = ast.If(test=ast.UnaryOp(op=ast.Not(), operand=cond), body=[ast.Break()], orelse=[])
                return ast.While(test=ast.Constant(True), body=body + [break_if], orelse=[])
            case "FOR":
                self.expect_and_next("FOR")
                self.expect_and_next("LPAREN")
                init_stmt = None
                if self.peek().type != "SEMI":
                    if looks_like_declaration():
                        init_stmt = self.parse_variable_decl()
                        if self.peek().type == "SEMI":
                            self.next()
                    else:
                        init_expr = self.parse_expr(0)
                        init_stmt = ast.Expr(value=init_expr)
                        self.expect_and_next("SEMI")
                else:
                    self.next()
                if self.peek().type != "SEMI":
                    cond_expr = self.parse_expr()
                else:
                    cond_expr = ast.Constant(True)
                self.expect_and_next("SEMI")
                if self.peek().type != "RPAREN":
                    post_expr = self.parse_expr()
                else:
                    post_expr = None
                self.expect_and_next("RPAREN")
                if self.peek().type == "LBRACE":
                    body_tokens = self.read_scope()
                    sub = CParser(body_tokens)
                    body = sub.parse().body
                else:
                    body = [self.parse_stmt()]
                loop_body = list(body)
                if post_expr is not None:
                    loop_body.append(ast.Expr(value=post_expr))
                if not loop_body:
                    loop_body.append(ast.Pass())
                while_node = ast.While(test=cond_expr if cond_expr is not None else ast.Constant(True), body=loop_body, orelse=[])
                if init_stmt is not None:
                    # TODO: return multiple statement
                    return ast.With(items=[], body=[init_stmt, while_node])
                return while_node
            case "SWITCH":
                self.expect_and_next("SWITCH")
                self.expect_and_next("LPAREN")
                switch_expr = self.parse_expr()
                self.expect_and_next("RPAREN")
                if self.peek().type == "LBRACE":
                    body_tokens = self.read_scope()
                    if not body_tokens:
                        return ast.Pass()
                    sub = CParser(body_tokens)
                    body = sub.parse().body
                    return ast.Match(switch_expr, cases=cast(list[ast.match_case], body))
                else:
                    raise ValueError("malformed switch: expected block")
            case "CASE":
                cond = cast(ast.match_case, self.parse_expr())
                self.expect_and_next("COLON")
                if self.peek().type == "LBRACE":
                    sub = CParser(self.read_scope())
                    cond.body = sub.parse().body
                else:
                    while self.has_next():
                        if self.peek().type in ("CASE", "DEFAULT"):
                            break
                        stmt = self.parse_stmt()
                        if not isinstance(stmt, ast.Break):
                            cond.body.append(stmt)
                return cast(ast.stmt, cond)
            case "DEFAULT":
                self.expect_and_next("DEFAULT")
                self.expect_and_next("COLON")
                cond = ast.match_case(ast.MatchAs(None), body=[])
                if self.peek().type == "LBRACE":
                    sub = CParser(self.read_scope())
                    cond.body = sub.parse().body
                else:
                    while self.has_next():
                        if self.peek().type in ("CASE", "DEFAULT"):
                            break
                        stmt = self.parse_stmt()
                        if not isinstance(stmt, ast.Break):
                            cond.body.append(stmt)

                return cast(ast.stmt, cond)

        expr = self.parse_expr(0)
        return ast.Expr(value=expr)

    def parse(self) -> ast.Module:
        body: list[ast.stmt] = []
        while self.i < len(self._tokens) - 1:
            body.append(self.parse_stmt())

        return ast.Module(body)


def preprocess(c: str) -> str:
    def strip_c_comments(code):
        regex = re.compile(
            r"""
            "(?:\\.|[^"\\])*" |
            '(?:\\.|[^'\\])*' |
            //.*?$            |
            /\*.*?\*/
            """,
            re.VERBOSE | re.DOTALL | re.MULTILINE,
        )

        def replacer(match):
            text = match.group(0)
            if text.startswith('"') or text.startswith("'"):
                return text
            return ""

        return regex.sub(replacer, code)

    c = strip_c_comments(c)
    return c


def ctopy(c: str) -> str:
    c = preprocess(c)
    lex = CLexer(error_func=lambda *a, **k: None, on_lbrace_func=lambda: None, on_rbrace_func=lambda: None, type_lookup_func=lambda typ: False)
    lex.build()
    lex.input(c)

    tokens = []
    while tok := lex.token():
        tokens.append(tok)

    parser = CParser(tokens, c)
    module = parser.parse()

    return ast.unparse(ast.fix_missing_locations(module))


def ctopy_ast(c: str) -> ast.Module:
    c = preprocess(c)
    lex = CLexer(error_func=lambda *a, **k: None, on_lbrace_func=lambda: None, on_rbrace_func=lambda: None, type_lookup_func=lambda typ: False)
    lex.build()
    lex.input(c)

    tokens = []
    while tok := lex.token():
        tokens.append(tok)

    parser = CParser(tokens, c)
    module = parser.parse()

    return ast.fix_missing_locations(module)

