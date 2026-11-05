import math

import pytest

from clicky.expressions import MAX_FORMULA_LENGTH, compile_formula


def evaluate(text: str, t: float = 0.0, x: float = 0.0):
    formula = compile_formula(text)
    assert formula is not None, f"should compile: {text}"
    return formula.evaluate(t, x)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("10 - 4 - 3", 3),
        ("2 ^ 3 ^ 2", 512),  # right-associative
        ("-2 ^ 2", -4),  # unary minus binds looser than ^
        ("--3", 3),
        ("8 / 4 / 2", 1),
        ("3.5e2", 350),
        (".5 + 1.", 1.5),
        ("pi", math.pi),
        ("2*e", 2 * math.e),
    ],
)
def test_arithmetic_and_precedence(text, expected):
    assert evaluate(text) == pytest.approx(expected)


def test_variables_t_and_x():
    assert evaluate("50 - 4.9*t^2", t=2) == pytest.approx(30.4)
    assert evaluate("4.9*x^2 + t", t=1, x=2) == pytest.approx(20.6)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("sin(pi/2)", 1),
        ("cos(0)", 1),
        ("tan(0)", 0),
        ("asin(1)", math.pi / 2),
        ("acos(1)", 0),
        ("atan(1)", math.pi / 4),
        ("sqrt(16)", 4),
        ("abs(-3)", 3),
        ("exp(0)", 1),
        ("log(e)", 1),
        ("min(3, 1, 2)", 1),
        ("max(3, 1, 2)", 3),
        ("floor(2.7)", 2),
        ("ceil(2.1)", 3),
        ("round(2.5)", 3),
        ("clamp(5, 0, 2)", 2),
        ("lerp(0, 10, 0.25)", 2.5),
        ("step(1, 0.5)", 0),
        ("step(1, 2)", 1),
        ("mod(7, 3)", 1),
    ],
)
def test_functions(text, expected):
    assert evaluate(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os')",
        "os.system('x')",
        "t.real",
        "tt",
        "y + 1",
        "print(1)",
        "sin",
        "sin(1",
        "1 +",
        "(1))",
        "1 2",
        "",
        "   ",
        "min()",
        "clamp(1, 2)",
        "1 ; 2",
        "'a'",
        "x[0]",
        "lambda: 1",
    ],
)
def test_invalid_or_unsafe_formulas_do_not_compile(text):
    assert compile_formula(text) is None


def test_maths_errors_give_none_not_exceptions():
    assert evaluate("1 / t", t=0) is None
    assert evaluate("sqrt(-1)") is None
    assert evaluate("log(0)") is None
    assert evaluate("10 ^ 400") is None
    assert evaluate("mod(1, 0)") is None


def test_huge_results_are_rejected():
    assert evaluate("1e8 * 1e8") is None


def test_length_and_depth_guards():
    assert compile_formula("1+" * 100 + "1") is None  # longer than the limit
    assert len("1+" * 100 + "1") > MAX_FORMULA_LENGTH
    assert compile_formula("(" * 40 + "1" + ")" * 40) is None  # nested too deep
    assert compile_formula("(" * 10 + "1" + ")" * 10) is not None


def test_numbers_are_accepted_as_formulas():
    assert compile_formula("42").evaluate(0) == 42
