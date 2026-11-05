"""A small, safe maths language for animation formulas, e.g. "50 - 4.9*t^2".

The model's formulas are parsed by this recursive-descent parser over a strict whitelist (numbers, t, x, pi, e,
+ - * / ^, parentheses and a fixed set of functions) and compiled to Python closures. Nothing is ever passed to
eval or exec, and there are no names, attributes or calls outside the whitelist. Any maths error, overflow or
non-finite result evaluates to None, which the renderer treats as "hide this object this frame".
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

MAX_FORMULA_LENGTH = 160
MAX_NESTING_DEPTH = 32
MAX_ABSOLUTE_RESULT = 1e9

TOKEN_PATTERN = re.compile(
    r"\s*(?:(?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|(?P<name>[a-z_][a-z_0-9]*)|(?P<operator>[-+*/^(),]))"
)

Evaluator = Callable[[float, float], float]


def _round_half_up(value: float) -> float:
    return math.floor(value + 0.5)


# name -> (minimum arguments, maximum arguments, implementation)
FUNCTIONS: dict[str, tuple[int, int, Callable[..., float]]] = {
    "sin": (1, 1, math.sin),
    "cos": (1, 1, math.cos),
    "tan": (1, 1, math.tan),
    "asin": (1, 1, math.asin),
    "acos": (1, 1, math.acos),
    "atan": (1, 1, math.atan),
    "sqrt": (1, 1, math.sqrt),
    "abs": (1, 1, abs),
    "exp": (1, 1, math.exp),
    "log": (1, 1, math.log),
    "floor": (1, 1, math.floor),
    "ceil": (1, 1, math.ceil),
    "round": (1, 1, _round_half_up),
    "min": (1, 8, min),
    "max": (1, 8, max),
    "clamp": (3, 3, lambda value, low, high: max(low, min(high, value))),
    "lerp": (3, 3, lambda start, end, amount: start + (end - start) * amount),
    "step": (2, 2, lambda edge, value: 1.0 if value >= edge else 0.0),
    "mod": (2, 2, lambda dividend, divisor: dividend % divisor),
}
CONSTANTS = {"pi": math.pi, "e": math.e}


class _ParseError(ValueError):
    pass


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        if text[position:].strip() == "":
            break
        match = TOKEN_PATTERN.match(text, position)
        if match is None or match.end() == position:
            raise _ParseError(f"unexpected character at {position}")
        kind = match.lastgroup
        assert kind is not None
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._index = 0
        self._depth = 0

    def parse(self) -> Evaluator:
        if not self._tokens:
            raise _ParseError("empty formula")
        evaluator = self._expression()
        if self._index != len(self._tokens):
            raise _ParseError("unexpected trailing input")
        return evaluator

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _take(self) -> tuple[str, str]:
        token = self._peek()
        if token is None:
            raise _ParseError("unexpected end of formula")
        self._index += 1
        return token

    def _expect(self, operator: str) -> None:
        if self._take() != ("operator", operator):
            raise _ParseError(f"expected {operator!r}")

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > MAX_NESTING_DEPTH:
            raise _ParseError("formula nested too deeply")

    def _expression(self) -> Evaluator:
        self._enter()
        result = self._term()
        while self._peek() in (("operator", "+"), ("operator", "-")):
            operator = self._take()[1]
            right = self._term()
            left = result
            result = (
                (lambda a, b: lambda t, x: a(t, x) + b(t, x))(left, right)
                if operator == "+"
                else (lambda a, b: lambda t, x: a(t, x) - b(t, x))(left, right)
            )
        self._depth -= 1
        return result

    def _term(self) -> Evaluator:
        result = self._unary()
        while self._peek() in (("operator", "*"), ("operator", "/")):
            operator = self._take()[1]
            right = self._unary()
            left = result
            result = (
                (lambda a, b: lambda t, x: a(t, x) * b(t, x))(left, right)
                if operator == "*"
                else (lambda a, b: lambda t, x: a(t, x) / b(t, x))(left, right)
            )
        return result

    def _unary(self) -> Evaluator:
        token = self._peek()
        if token in (("operator", "-"), ("operator", "+")):
            self._take()
            self._enter()
            operand = self._unary()
            self._depth -= 1
            return operand if token[1] == "+" else (lambda a: lambda t, x: -a(t, x))(operand)
        return self._power()

    def _power(self) -> Evaluator:
        base = self._atom()
        if self._peek() == ("operator", "^"):
            self._take()
            self._enter()
            exponent = self._unary()  # right-associative; allows 2^-1
            self._depth -= 1
            return (lambda a, b: lambda t, x: a(t, x) ** b(t, x))(base, exponent)
        return base

    def _atom(self) -> Evaluator:
        kind, value = self._take()
        if kind == "number":
            constant = float(value)
            return lambda t, x: constant
        if kind == "name":
            if value == "t":
                return lambda t, x: t
            if value == "x":
                return lambda t, x: x
            if value in CONSTANTS:
                constant = CONSTANTS[value]
                return lambda t, x: constant
            if value in FUNCTIONS and self._peek() == ("operator", "("):
                return self._call(value)
            raise _ParseError(f"unknown name {value!r}")
        if (kind, value) == ("operator", "("):
            inner = self._expression()
            self._expect(")")
            return inner
        raise _ParseError(f"unexpected {value!r}")

    def _call(self, name: str) -> Evaluator:
        minimum, maximum, implementation = FUNCTIONS[name]
        self._expect("(")
        arguments: list[Evaluator] = []
        if self._peek() != ("operator", ")"):
            arguments.append(self._expression())
            while self._peek() == ("operator", ","):
                self._take()
                arguments.append(self._expression())
        self._expect(")")
        if not minimum <= len(arguments) <= maximum:
            raise _ParseError(f"{name} takes {minimum}..{maximum} arguments")
        frozen_arguments = tuple(arguments)
        return lambda t, x: implementation(*(argument(t, x) for argument in frozen_arguments))


class Formula:
    def __init__(self, source: str, evaluator: Evaluator) -> None:
        self.source = source
        self._evaluator = evaluator

    def evaluate(self, t: float, x: float = 0.0) -> float | None:
        try:
            value = float(self._evaluator(t, x))
        except (ArithmeticError, ValueError, TypeError):
            return None
        if not math.isfinite(value) or abs(value) > MAX_ABSOLUTE_RESULT:
            return None
        return value


def compile_formula(text: str) -> Formula | None:
    """Compile a formula, or return None if it is empty, too long, too deep, malformed or not whitelisted."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_FORMULA_LENGTH:
        return None
    try:
        return Formula(text, _Parser(_tokenize(text)).parse())
    except (_ParseError, RecursionError):
        return None
