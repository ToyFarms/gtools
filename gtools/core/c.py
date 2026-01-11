class IdentifierRegistry:
    def __init__(self) -> None:
        self._used: dict[str, int] = {}

    def dedup(self, identifier: str) -> str:
        if identifier not in self._used:
            self._used[identifier] = 1
            return identifier

        counter = 2
        while True:
            candidate = f"{identifier}_{counter}"
            if candidate not in self._used:
                self._used[candidate] = 1
                return candidate
            counter += 1

    def reset(self):
        self._used.clear()


C_KEYWORDS = {
    "auto",
    "break",
    "case",
    "char",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extern",
    "float",
    "for",
    "goto",
    "if",
    "inline",
    "int",
    "long",
    "register",
    "restrict",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "struct",
    "switch",
    "typedef",
    "union",
    "unsigned",
    "void",
    "volatile",
    "while",
    "_Bool",
    "_Complex",
    "_Imaginary",
    "_Alignas",
    "_Alignof",
    "_Atomic",
    "_Generic",
    "_Noreturn",
    "_Static_assert",
    "_Thread_local",
}
SPECIAL_CHAR_MAP = {
    "(": "_open_",
    ")": "_close_",
    "[": "_lbrack_",
    "]": "_rbrack_",
    "{": "_lbrace_",
    "}": "_rbrace_",
    "<": "_lt_",
    ">": "_gt_",
    "!": "_not_",
    "@": "_at_",
    "#": "_hash_",
    "$": "_dollar_",
    "%": "_percent_",
    "^": "_caret_",
    "&": "_and_",
    "*": "_star_",
    "-": "_",
    "+": "_plus_",
    "=": "_eq_",
    "|": "_pipe_",
    "\\": "_bslash_",
    "/": "_slash_",
    "?": "_question_",
    ".": "_dot_",
    ",": "_comma_",
    ":": "_colon_",
    ";": "_semicolon_",
    "~": "_tilde_",
    "`": "_backtick_",
    "'": "_",
    '"': "_",
    " ": "_",
    "\t": "_",
    "\n": "_",
    "\r": "_",
}


def to_c_ident(s: str, registry: IdentifierRegistry | None = None) -> str:
    if not s:
        raise ValueError("cannot be empty")

    result = []
    for char in s:
        if char.isalnum() or char == "_":
            result.append(char)
        elif char in SPECIAL_CHAR_MAP:
            result.append(SPECIAL_CHAR_MAP[char])
        else:
            result.append("_")

    base = "".join(result)
    while "__" in base:
        base = base.replace("__", "_")

    base = base.strip("_")
    if not base:
        base = "empty"

    if base[0].isdigit():
        base = "_" + base

    if base.lower() in C_KEYWORDS:
        base = base + "_"

    if registry is None:
        return base

    return registry.dedup(base)
