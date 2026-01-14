import ast
from collections import deque
from dataclasses import dataclass
import itertools
import os
import re
from typing import Any, cast
from pycparser.c_lexer import CLexer

DEBUG = "DEBUG" in os.environ


def type_default_param(type_str: str) -> tuple[str | None, Any | None]:
    if not type_str or not isinstance(type_str, str):
        return None, None

    s = type_str.strip()

    is_pointer = "*" in s
    if is_pointer:
        s = s.replace("*", " ")

    if "[" in s or "]" in s:
        return None, None
    if re.search(r"\b(struct|union|enum)\b", s, flags=re.IGNORECASE):
        return None, None
    if "(" in s or ")" in s:
        return None, None

    tokens = s.split()
    type_words = {
        "const",
        "volatile",
        "register",
        "restrict",
        "static",
        "extern",
        "inline",
        "signed",
        "unsigned",
        "short",
        "long",
        "int",
        "integer",
        "char",
        "float",
        "double",
        "bool",
        "_bool",
        "_bool_t",
        "wchar_t",
        "void",
        "size_t",
        "ssize_t",
        "intptr_t",
        "uintptr_t",
        "ptrdiff_t",
        "off_t",
        "mode_t",
        "pid_t",
        "time_t",
        "in_addr_t",
        "uid_t",
        "gid_t",
        "complex",
        "_complex",
    }
    if len(tokens) > 1 and re.match(r"^[A-Za-z_]\w*$", tokens[-1]) and tokens[-1].lower() not in type_words:
        tokens = tokens[:-1]
        s = " ".join(tokens)

    lower = s.lower()

    qualifiers_pattern = r"\b(const|volatile|register|restrict|static|extern|inline|signed|unsigned)\b"
    s_clean = re.sub(qualifiers_pattern, "", lower).strip()
    s_clean = re.sub(r"\s+", " ", s_clean).strip()

    s_norm = s_clean.replace("long long", "long long")
    s_norm = s_norm.replace("signed char", "signed char")

    int_type_patterns = [
        r"^(?:int|integer)$",
        r"^(?:short|short int|short signed|short signed int)$",
        r"^(?:long|long int|long signed|long signed int)$",
        r"^(?:long long|long long int|long long signed|long long signed int)$",
        r"^(?:u?int\d+_t)$",
        r"^__u?int\d+$",
        r"^__int\d+$",
        r"^(?:size_t|ssize_t|intptr_t|uintptr_t|ptrdiff_t|off_t|mode_t|pid_t|time_t|in_addr_t|uid_t|gid_t)$",
        r"^(?:unsigned|signed)$",
    ]
    for pat in int_type_patterns:
        if re.match(pat, s_norm):
            hint = "int"
            default = 0
            if is_pointer:
                return f"{hint} | None", None
            return hint, default

    if s_norm == "char":
        if is_pointer:
            return f"str", ""
        return "int", 0

    if s_norm in ("signed char", "unsigned char"):
        hint = "int"
        default = 0
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if s_norm in ("wchar_t",):
        hint = "str"
        default = ""
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if re.match(r"^(?:float|double|long double|longdouble)$", s_norm):
        hint = "float"
        default = 0.0
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if s_norm in ("_bool", "bool", "_bool_t"):
        hint = "bool | int"
        default = False
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if re.search(r"\bcomplex\b", s_norm) or re.search(r"_complex", s_norm):
        hint = "complex"
        default = 0 + 0j
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if s_norm == "void":
        if is_pointer:
            return "Any | None", None
        return None, None

    common_int_aliases = {"int8_t", "int16_t", "int32_t", "int64_t", "uint8_t", "uint16_t", "uint32_t", "uint64_t", "intptr_t", "uintptr_t", "size_t", "ssize_t"}
    if s_norm in common_int_aliases:
        hint = "int"
        default = 0
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if "int" in s_norm and re.match(r"^[a-z0-9_ ]*int[a-z0-9_ ]*$", s_norm):
        hint = "int"
        default = 0
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if "float" in s_norm or "double" in s_norm:
        hint = "float"
        default = 0.0
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if "char" in s_norm and "[" not in s and "*" not in type_str:
        hint = "str"
        default = ""
        if is_pointer:
            return f"{hint} | None", None
        return hint, default

    if is_pointer:
        return f"{s.strip()} | None", None

    return None, None


@dataclass
class Token:
    type: str
    value: Any
    lineno: int
    lexpos: int


@dataclass
class Skip:
    skip: bool = False


OP_DEF = {
    "LPAREN": (160, 159, "postfix_call"),
    "LBRACKET": (160, 159, "postfix_index"),
    "PERIOD": (160, 160, "postfix_member"),
    "ARROW": (160, 160, "postfix_member"),
    "PLUSPLUS": (160, 0, "postfix_inc"),
    "MINUSMINUS": (160, 0, "postfix_dec"),
    "COMMA": (130, 0, "comma"),
    "TIMES": (120, 120, "binary_left"),
    "DIVIDE": (120, 120, "binary_left"),
    "MOD": (120, 120, "binary_left"),
    "PLUS": (110, 110, "binary_left"),
    "MINUS": (110, 110, "binary_left"),
    "LSHIFT": (100, 100, "binary_left"),
    "RSHIFT": (100, 100, "binary_left"),
    "LT": (90, 90, "binary_left"),
    "LE": (90, 90, "binary_left"),
    "GT": (90, 90, "binary_left"),
    "GE": (90, 90, "binary_left"),
    "EQ": (80, 80, "binary_left"),
    "NE": (80, 80, "binary_left"),
    "AND": (70, 70, "binary_left"),
    "AMP": (70, 70, "binary_left"),
    "CARET": (60, 60, "binary_left"),
    "PIPE": (50, 50, "binary_left"),
    "LAND": (40, 40, "binary_left"),
    "LOR": (30, 30, "binary_left"),
    "CONDOP": (20, 19, "ternary"),
    "COLON": (19, 0, "ternary_colon"),
    "EQUALS": (10, 9, "assign"),
    "PLUSEQUAL": (10, 9, "assign"),
    "MINUSEQUAL": (10, 9, "assign"),
    "TIMESEQUAL": (10, 9, "assign"),
    "DIVEQUAL": (10, 9, "assign"),
    "MODEQUAL": (10, 9, "assign"),
    "LSHIFTEQUAL": (10, 9, "assign"),
    "RSHIFTEQUAL": (10, 9, "assign"),
    "ANDEQUAL": (10, 9, "assign"),
    "XOREQUAL": (10, 9, "assign"),
    "OREQUAL": (10, 9, "assign"),
    "CASE": (0, -1, "case"),
}


@dataclass
class Setting:
    preserve_cast: bool = True
    ref: bool = True


class CommaTransformer(ast.NodeTransformer):
    def flatten_comma(self, node: ast.AST) -> list[ast.AST]:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "comma":
            elts: list[ast.AST] = []
            for arg in node.args:
                elts.extend(self.flatten_comma(arg))

            return elts

        return [node]

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "comma":
            elements = []
            for a in node.args:
                elements.extend(self.flatten_comma(a))

            tuple_node = ast.Tuple(elts=elements, ctx=ast.Load())

            lambda_node = ast.Lambda(
                args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                body=ast.Subscript(value=tuple_node, slice=ast.Constant(value=-1), ctx=ast.Load()),
            )

            call_node = ast.Call(func=lambda_node, args=[], keywords=[])

            return ast.copy_location(call_node, node)
        return node


class CParser:
    match_i = itertools.count()
    match_q = deque[int]()

    def __init__(self, tokens: list[Token], code: str | None = None, setting: Setting | None = None) -> None:
        self._tokens = tokens
        self._code = code
        self.i = 0
        self.s = setting if setting else Setting()

    def next(self) -> Token:
        if self.i > len(self._tokens) - 1:
            raise IndexError("out of bound read")

        i = self.i
        self.i += 1
        if DEBUG:
            print(f"NEXT: {self._tokens[i]}")
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

    def next_if(self, type: str) -> Token | None:
        if self.peek().type == type:
            return self.next()

    def has_next(self) -> bool:
        return len(self._tokens) - (self.i + 1) > 0

    def read_inbetween(self, opening: str, closing: str) -> list[Token]:
        stack = int(self.next().type == opening)
        acc: list[Token] = []
        while stack > 0:
            if self.peek().type == opening:
                stack += 1
            elif self.peek().type == closing:
                stack -= 1

            if stack == 0:
                if self.has_next():
                    self.next()
                break

            acc.append(self.next())

        return acc

    def read_scope(self) -> list[Token]:
        return self.read_inbetween("LBRACE", "RBRACE")

    def parse_declarator(self):
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
        saved = self.i
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
        while self.peek().type in TYPE_TOKS | {"ID", "TIMES"}:
            type_tokens.append(self.next())

        *type_tokens, var_name = type_tokens

        if len(type_tokens) >= 1 and self.has_next() and self.peek().type == "LPAREN":
            self.i = saved
            return self.parse_fundef()

        # foo.
        if self.peek().type in ("DOT", "ARROW"):
            self.next()
            self.i = saved
            left = self.parse_expr(stop_at="assign")
            right = self.parse_expr()
            if self.peek().type == "SEMI":
                self.next()
            return ast.Assign([left], right)

        types = "".join(x.value for x in type_tokens)

        # int x[]
        if self.peek().type == "LBRACKET":
            self.expect_and_next("LBRACKET")
            subscript = self.parse_expr()
            types = types + f"[{ast.unparse(subscript)}]"
            self.expect_and_next("RBRACKET")

        type, default_value = type_default_param(types)
        type = ast.Name(type, ast.Load()) if type else ast.Constant(types) if types else None
        # int x;
        if self.peek().type == "SEMI":
            self.expect_and_next("SEMI")
            if type:
                return ast.AnnAssign(ast.Name(var_name.value, ast.Store()), annotation=type, value=ast.Constant(default_value), simple=1)
            else:
                return ast.Assign([ast.Name(var_name.value, ast.Store())], value=ast.Constant(default_value))

        value = None
        # int x = ...
        if self.peek().type == "EQUALS":
            self.next()
            value = self.parse_expr()
        elif self.get_op_info(self.peek().type)[2] == "assign":  # int x |= (aug assign)
            self.i -= 1
            return ast.Expr(self.parse_expr())
        else:  # int x;
            self.expect_and_next("SEMI")

        if type:
            return ast.AnnAssign(ast.Name(var_name.value, ast.Store()), type, value, simple=1)
        elif value:
            return ast.Assign([ast.Name(var_name.value, ast.Store())], value=value)
        raise ValueError(f"failed parsing value in assigmnent: {types}")

    def parse_block_stmt(self) -> list[ast.stmt]:
        body = []
        while self.has_next():
            if self.peek().type == "SEMI" or self.peek(-1).type == "SEMI":
                break

            body.append(self.parse_stmt())
        self.next_if("SEMI")

        return body

    def parse_if(self) -> ast.stmt:
        self.expect_and_next("IF")
        cond = self.parse_expr(context={"eat_comma": True, "mandatory_paren": True})

        if self.peek().type == "LBRACE":
            body = self.parse_body()
        else:
            body = self.parse_block_stmt()

        orelse: list[ast.stmt] = []
        if self.peek().type == "ELSE":
            self.next()
            if self.peek().type == "LBRACE":
                orelse = self.parse_body()
            else:
                orelse = self.parse_block_stmt()

        return ast.If(test=cond, body=body, orelse=orelse)

    def parse_return(self) -> ast.stmt:
        self.expect_and_next("RETURN")

        retval = None
        if self.peek().type != "SEMI":
            retval = self.parse_expr()

        self.expect_and_next("SEMI")

        return ast.Return(value=retval)

    def parse_fundef(self) -> ast.stmt:
        retypes: list[Token] = []
        while self.has_next():
            retypes.append(self.next())
            if self.peek().type == "LPAREN":
                break

        args: list[ast.arg] = []
        self.expect_and_next("LPAREN")
        while True:
            if self.peek().type == "RPAREN":
                self.next()
                break

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

            id_tok, pointer_level, array_dims = self.parse_declarator()
            mods = ""
            if pointer_level > 0 or array_dims:
                mods = "*" * pointer_level if pointer_level else "".join(ast.unparse(x) for x in array_dims if x)
            types = "_".join(x.value for x in type_tokens) + mods
            type, _ = type_default_param(types)
            annotation = ast.Name(type) if type else ast.Constant(types)

            args.append(ast.arg(id_tok.value, annotation))

            if self.peek().type == "RPAREN":
                self.next()
                break

            self.expect_and_next("COMMA")

        *retypes, name = retypes
        fn = ast.FunctionDef(name.value, ast.arguments(args), [], returns=ast.Constant("_".join(x.value for x in retypes)))

        fn.body = self.parse_body()
        return fn

    def get_op_info(self, token_type: str) -> tuple[int, int, str]:
        return OP_DEF.get(token_type, (-1, -1, "none"))

    def parse_expr(self, min_bp: int = 0, stop_at: str | None = None, context: dict | None = None) -> ast.expr:
        context = context if context else {}
        tok = self.next()
        left = self.nud(tok, context)
        if DEBUG:
            print(f"nud: \x1b[33m{ast.unparse(left)} [next={tok}]\x1b[0m")

        while self.has_next():
            look = self.peek()
            lbp, rbp, kind = self.get_op_info(look.type)
            if DEBUG:
                print("expr: ", look.type, lbp, rbp, kind)

            if stop_at and kind == stop_at:
                self.next()
                return left

            if kind == "comma" and not context.get("eat_comma"):
                break
            if kind in ("ternary_colon",):
                break

            if lbp <= min_bp or kind == "none":
                break

            op_tok = self.next()
            left = self.led(op_tok, left, rbp, context)
            if DEBUG:
                print(f"led: \x1b[34m{ast.unparse(left)} [next={op_tok}]\x1b[0m")

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

    def is_valid_typename(self, token: Token) -> bool:
        return token.type in ("TIMES", "AND", "ID", "UNSIGNED", "SIGNED", "INT", "CHAR", "FLOAT", "DOUBLE", "VOID", "TYPE_NAME", "STRUCT", "UNION", "ENUM", "CONST", "VOLATILE")

    def is_cast(self, context: dict) -> bool:
        saved = self.i
        if not context.get("mandatory_paren"):
            self.i -= 1
        inbetween = self.read_inbetween("LPAREN", "RPAREN")
        if not inbetween:
            self.i = saved
            return False

        is_cast = self.peek().type not in (
            "LBRACE",
            "EQUALS",
            "PLUSEQUAL",
            "MINUSEQUAL",
            "TIMESEQUAL",
            "TIMESEQUAL",
            "DIVEQUAL",
            "MODEQUAL",
            "LSHIFTEQUAL",
            "RSHIFTEQUAL",
            "ANDEQUAL",
            "XOREQUAL",
            "OREQUAL",
            "PERIOD",
            "COMMA",
            "LSHIFT",
            "RSHIFT",
            "LT",
            "LE",
            "GT",
            "GE",
            "EQ",
            "NE",
        ) and all(self.is_valid_typename(x) for x in inbetween)
        self.i = saved
        return is_cast

    def is_tuple(self, context: dict) -> bool:
        if self.is_cast(context):
            return False

        saved = self.i
        if not context.get("mandatory_paren"):
            self.i -= 1
        inbetween = self.read_inbetween("LPAREN", "RPAREN")
        if not inbetween:
            self.i = saved
            return False
        self.i = saved

        return "COMMA" in (x.type for x in inbetween)

    def nud(self, tok: Token, context: dict) -> ast.expr:
        t = tok.type
        v = tok.value

        if t == "LPAREN":
            # handle cast
            if self.is_cast(context):
                self.i -= 1
                types = self.read_inbetween("LPAREN", "RPAREN")
                right = self.parse_expr(130, context=context)
                if self.s.preserve_cast:
                    return ast.Call(func=ast.Name(id="cast", ctx=ast.Load()), args=[ast.Constant("".join(x.value for x in types)), right])
                else:
                    return right
            elif self.is_tuple(context):
                exprs = []
                while True:
                    exprs.append(self.parse_expr())
                    if self.peek().type == "RPAREN":
                        self.next()
                        break
                    self.expect_and_next("COMMA")
                return ast.Subscript(ast.Tuple(exprs), ast.Constant(-1))
            else:
                # normal grouping
                expr = self.parse_expr(context=context)
                self.expect_and_next("RPAREN")
                return expr

        if t == "ID":
            return ast.Name(str(v))
        if t in ("INT_CONST_DEC", "INT_CONST_HEX", "INT_CONST_OCT"):
            return ast.Constant(int(v, 0))
        if t == "FLOAT_CONST":
            return ast.Constant(float(v))
        if t == "STRING_LITERAL":
            return ast.Constant(str(v).strip('"'))
        if t == "CHAR_CONST":
            return ast.Constant(str(v).strip("'"))
        if t == "CASE":
            right = cast(ast.pattern, self.parse_expr(context=context))
            return cast(ast.expr, ast.match_case(pattern=right, body=[]))
        if t == "LBRACE":
            right = self.parse_expr(context=context)
            self.expect_and_next("SEMI")
            self.expect_and_next("RBRACE")
            return right
        if t == "PERIOD":
            name = self.next()
            self.expect_and_next("EQUALS")
            right = self.parse_expr(context=context)
            return ast.Call(ast.Name("init"), [ast.Name(name.value), right])

        # unary
        if t in ("PLUS", "MINUS", "LNOT", "TILDE", "TIMES", "AMP", "INCREMENT", "DECREMENT", "SIZEOF", "AND"):
            right = self.parse_expr(130, context=context)
            op_map = {
                "PLUS": ast.UAdd(),
                "MINUS": ast.USub(),
                "LNOT": ast.Not(),
                "TILDE": ast.Invert(),
                "TIMES": "deref",
                "AND": "ref",
                "INCREMENT": "inc",
                "DECREMENT": "dec",
                "SIZEOF": "sizeof",
            }
            op = op_map.get(t)
            if isinstance(op, ast.unaryop):
                return ast.UnaryOp(op=op, operand=right)
            elif isinstance(op, str):
                if op in ("ref", "deref") and not self.s.ref:
                    return right
                return ast.Call(ast.Name(op), args=[right])

        assert False, f"nud unhandled token: {tok}"

    def led(self, op_tok: Token, left: ast.expr, rbp: int, context: dict) -> ast.expr:
        t = op_tok.type
        v = op_tok.value

        # handle funcall
        if t == "LPAREN":
            args: list[ast.expr] = []
            if self.peek().type != "RPAREN":
                while True:
                    args.append(self.parse_expr(context=context))
                    if self.peek().type == "COMMA":
                        self.next()
                        continue
                    break
            self.expect_and_next("RPAREN")
            return ast.Call(left, args)

        if t == "LBRACKET":
            idx = self.parse_expr(0, context=context)
            self.expect_and_next("RBRACKET")
            return ast.Subscript(left, idx)

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
                "EQ": ast.Eq,
                "EQ": ast.Eq,
                "NE": ast.NotEq,
            }

            if t == "LAND":
                right = self.parse_expr(rbp, context=context)
                return ast.BoolOp(op=ast.And(), values=[left, right])
            if t == "LOR":
                right = self.parse_expr(rbp, context=context)
                return ast.BoolOp(op=ast.Or(), values=[left, right])

            if t in cmp_map:
                right = self.parse_expr(rbp, context=context)
                cmp_op = cmp_map[t]()
                return ast.Compare(left=left, ops=[cmp_op], comparators=[right])

            if t in binop_map:
                right = self.parse_expr(rbp, context=context)
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
                right = self.parse_expr(rbp, context=context)
                return ast.BinOp(left=left, op=fallback_symbol_to_ast[op_sym](), right=right)

            right = self.parse_expr(rbp, context=context)
            func_name = f"op_{t.lower()}"
            return ast.Call(func=ast.Name(id=func_name, ctx=ast.Load()), args=[left, right], keywords=[])

        if kind == "assign":
            assign_aug_map: dict[str, type[ast.operator]] = {
                "PLUSEQUAL": ast.Add,
                "MINUSEQUAL": ast.Sub,
                "TIMESEQUAL": ast.Mult,
                "DIVEQUAL": ast.Div,
                "MODEQUAL": ast.Mod,
                "LSHIFTEQUAL": ast.LShift,
                "RSHIFTEQUAL": ast.RShift,
                "ANDEQUAL": ast.BitAnd,
                "XOREQUAL": ast.BitXor,
                "OREQUAL": ast.BitOr,
            }

            if t == "ASSIGN":
                right = self.parse_expr(rbp, context=context)
                return ast.Assign([ast.Name(ast.unparse(left))], right)  # pyright: ignore[reportReturnType]

            if t in assign_aug_map:
                right = self.parse_expr(rbp, context=context)
                return ast.AugAssign(ast.Name(ast.unparse(left)), assign_aug_map[t](), right)  # pyright: ignore[reportReturnType]

            right = self.parse_expr(rbp, context=context)
            return ast.NamedExpr(cast(ast.Name, left), right)

        if kind == "ternary":
            true_expr = self.parse_expr(context=context)
            self.expect_and_next("COLON")
            false_expr = self.parse_expr(rbp, context=context)
            return ast.IfExp(test=left, body=true_expr, orelse=false_expr)

        if kind == "comma" and context:
            right = self.parse_expr(rbp, context=context)
            return ast.Call(func=ast.Name(id="comma", ctx=ast.Load()), args=[left, right], keywords=[])

        if kind == "postfix_member":
            right = self.parse_expr(rbp)
            return ast.Attribute(left, ast.unparse(right))

        assert False, f"unhandled led: op={op_tok}, left={ast.dump(left)}"

    def parse_body(self) -> list[ast.stmt]:
        if self.peek().type == "SEMI":
            return [ast.Pass()]

        self.expect("LBRACE")
        body_tokens = self.read_scope()
        if not body_tokens:
            return [ast.Pass()]
        sub = CParser(body_tokens, self._code, self.s)
        return sub.parse().body

    def parse_stmt(self, skip: Skip | None = None) -> ast.stmt:
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
            case "SEMI":
                if skip:
                    skip.skip = True
                self.next()
                return ast.Pass()
            case "INT" | "VOID" | "FLOAT" | "DOUBLE" | "CHAR" | "STRUCT" | "UNION" | "ENUM" | "CONST" | "VOLATILE" | "SIGNED" | "UNSIGNED":
                return self.parse_variable_decl()

            case "ID":
                if self.peek(1).type == "COLON":
                    # label_1:
                    label = self.next()
                    self.expect_and_next("COLON")
                    return ast.Assign(
                        targets=[ast.Name("_", ast.Store())],
                        value=ast.Call(func=ast.Name("LABEL", ast.Load()), args=[ast.Constant(label.value)], keywords=[]),
                    )
                elif self.peek(1).type in ("EQUALS", "DOT", "ARROW"):  # x = | x. | x->
                    return self.parse_variable_decl()
                elif self.peek(1).type == "LPAREN":  # x()
                    # fn = self.next()
                    # self.expect_and_next("LPAREN")
                    # args = []
                    # while self.peek().type != "RPAREN":
                    #     args.append(self.parse_expr())

                    return ast.Expr(self.parse_expr())
                else:
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
                    value=ast.Call(func=ast.Name("goto", ast.Store()), args=[ast.Constant(label.value)], keywords=[]),
                )
            case "LBRACE":
                return ast.With(items=[], body=self.parse_body())
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
                    body = self.parse_body()
                else:
                    body = self.parse_block_stmt()
                return ast.While(test=cond, body=body, orelse=[])
            case "DO":
                self.expect_and_next("DO")
                if self.peek().type == "LBRACE":
                    body = self.parse_body()
                else:
                    body = self.parse_block_stmt()
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
                    body = self.parse_body()
                else:
                    body = self.parse_block_stmt()
                loop_body = list(body)
                if post_expr is not None:
                    loop_body.append(ast.Expr(value=post_expr))
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
                    CParser.match_q.appendleft(next(CParser.match_i))
                    parsed_cases = self.parse_body()

                    out = []
                    buffer: list[ast.pattern] = []
                    for case_node in parsed_cases:
                        case_node = cast(ast.match_case, case_node)
                        if not case_node.body:
                            buffer.append(case_node.pattern)
                            continue

                        if buffer and case_node.guard is None:
                            buffer.append(case_node.pattern)
                            out.append(ast.match_case(ast.MatchOr(buffer.copy()) if len(buffer) > 1 else buffer[0], case_node.guard, case_node.body))
                            buffer.clear()
                        else:
                            for p in buffer:
                                out.append(ast.match_case(p, body=[ast.Pass()]))
                            out.append(case_node)
                            buffer.clear()

                    for p in buffer:
                        out.append(ast.match_case(p, body=[ast.Pass()]))

                    parsed_cases = out
                    switch_temp_name = f"__switch_on{CParser.match_q[0]}"
                    matched_name = f"__matched{CParser.match_q[0]}"
                    matched_any_name = f"_switch_matched_any{CParser.match_q[0]}"

                    assign_switch = ast.Assign(
                        targets=[ast.Name(id=switch_temp_name, ctx=ast.Store())],
                        value=switch_expr,
                    )

                    init_matched_any = ast.Assign(
                        targets=[ast.Name(id=matched_any_name, ctx=ast.Store())],
                        value=ast.Constant(False),
                    )
                    init_matched = ast.Assign(
                        targets=[ast.Name(id=matched_name, ctx=ast.Store())],
                        value=ast.Constant(False),
                    )

                    while_body: list[ast.stmt] = []
                    for case_node in parsed_cases:
                        if not isinstance(case_node, ast.match_case):
                            while_body.append(case_node if isinstance(case_node, ast.stmt) else ast.Expr(case_node))
                            continue

                        pattern = case_node.pattern

                        is_default = isinstance(pattern, ast.MatchAs) and getattr(pattern, "name", None) is None

                        switch_val_load = ast.Name(id=switch_temp_name, ctx=ast.Load())
                        matched_load = ast.Name(id=matched_name, ctx=ast.Load())
                        matched_any_load = ast.Name(id=matched_any_name, ctx=ast.Load())

                        if not is_default:
                            if isinstance(pattern, ast.MatchOr):
                                comparisons: list[ast.expr] = [
                                    ast.Compare(
                                        left=switch_val_load,
                                        ops=[ast.Eq()],
                                        comparators=[cast(ast.expr, value)],
                                    )
                                    for value in pattern.patterns
                                ]
                                compare = ast.BoolOp(ast.Or(), comparisons)
                            else:
                                compare = ast.Compare(left=switch_val_load, ops=[ast.Eq()], comparators=[cast(ast.expr, pattern)])
                            test = ast.BoolOp(op=ast.Or(), values=[matched_load, compare])

                            set_matched_any_cond = ast.BoolOp(
                                op=ast.And(),
                                values=[
                                    ast.UnaryOp(op=ast.Not(), operand=matched_load),
                                    compare,
                                ],
                            )
                            set_matched_any = ast.Assign(
                                targets=[ast.Name(id=matched_any_name, ctx=ast.Store())],
                                value=ast.Constant(True),
                            )

                            prologue: list[ast.stmt] = [
                                ast.If(test=set_matched_any_cond, body=[set_matched_any], orelse=[]),
                                ast.Assign(targets=[ast.Name(id=matched_name, ctx=ast.Store())], value=ast.Constant(True)),
                            ]
                        else:
                            test = ast.BoolOp(
                                op=ast.Or(),
                                values=[matched_load, ast.UnaryOp(op=ast.Not(), operand=matched_any_load)],
                            )
                            prologue = [
                                ast.Assign(targets=[ast.Name(id=matched_name, ctx=ast.Store())], value=ast.Constant(True)),
                            ]

                        if_block = ast.If(test=test, body=prologue + list(case_node.body), orelse=[])
                        while_body.append(if_block)

                    while_body = [assign_switch, init_matched_any, init_matched] + while_body
                    while_node = ast.While(test=ast.Constant(True), body=while_body + [ast.Break()], orelse=[])

                    self.match_q.popleft()
                    return while_node
                else:
                    raise ValueError("malformed switch: expected block")
            case "CASE":
                cond = cast(ast.match_case, self.parse_expr())
                self.expect_and_next("COLON")
                if self.peek().type == "LBRACE":
                    cond.body = self.parse_body()
                else:
                    while self.has_next():
                        if self.peek().type in ("CASE", "DEFAULT"):
                            break
                        skip = Skip()
                        stmt = self.parse_stmt(skip)
                        if not skip.skip:
                            cond.body.append(stmt)
                return cast(ast.stmt, cond)
            case "DEFAULT":
                self.expect_and_next("DEFAULT")
                self.expect_and_next("COLON")
                cond = ast.match_case(ast.MatchAs(None), body=[])
                if self.peek().type == "LBRACE":
                    cond.body = self.parse_body()
                else:
                    while self.has_next():
                        if self.peek().type in ("CASE", "DEFAULT"):
                            break
                        stmt = self.parse_stmt()
                        if not isinstance(stmt, ast.Break):
                            cond.body.append(stmt)

                return cast(ast.stmt, cond)

        if DEBUG:
            print(f"FALLBACK: {self.peek()}")

        buf = []
        while self.has_next() and self.peek().type != "SEMI":
            buf.append(self.next())

        cons = " ".join(x.value for x in buf)
        return ast.Expr(ast.Constant(cons))

    def parse(self) -> ast.Module:
        body: list[ast.stmt] = []
        while self.has_next():
            skip = Skip()
            stmt = self.parse_stmt(skip)
            if not skip.skip:
                body.append(stmt)

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


def ctopy(c: str, setting: Setting | None = None) -> str:
    c = preprocess(c)
    lex = CLexer(error_func=lambda *a, **k: None, on_lbrace_func=lambda: None, on_rbrace_func=lambda: None, type_lookup_func=lambda typ: False)
    lex.build()
    lex.input(c)

    tokens = []
    while tok := lex.token():
        tokens.append(tok)

    parser = CParser(tokens, c, setting)
    module = ast.fix_missing_locations(parser.parse())

    code = ast.unparse(module)
    if "PYOUT" in os.environ:
        print(code)

    return code


def ctopy_ast(c: str, setting: Setting | None = None) -> ast.Module:
    c = preprocess(c)
    lex = CLexer(error_func=lambda *a, **k: None, on_lbrace_func=lambda: None, on_rbrace_func=lambda: None, type_lookup_func=lambda typ: False)
    lex.build()
    lex.input(c)

    tokens = []
    while tok := lex.token():
        tokens.append(tok)

    parser = CParser(tokens, c, setting)
    module = ast.fix_missing_locations(parser.parse())

    if "PYOUT" in os.environ:
        print(ast.unparse(module))

    return module
