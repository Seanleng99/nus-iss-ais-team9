import pytest
from language_fixtures import language_case

from ui.currency_markdown import currency_safe_markdown


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A S$2 snack becomes S$2.10, a 5% rise.", r"A S\$2 snack becomes S\$2.10, a 5% rise."),
        ("$100 grows to $104 and then $108.16.", r"\$100 grows to \$104 and then \$108.16."),
        ("$2 + $2.10", r"\$2 + \$2.10"),
        (
            language_case(
                "currency_markdown.test_currency_is_literal_without_breaking_math_code_or_links"
            ),
            language_case(
                "currency_markdown.test_currency_is_literal_without_breaking_math_code_or_links_2"
            ),
        ),
        ("Refund $-20; balance $ 100.", r"Refund \$-20; balance \$ 100."),
        (r"Already escaped \$100 and \$200.", r"Already escaped \$100 and \$200."),
        ("A $2 snack, `print('$100')`, now $3.", r"A \$2 snack, `print('$100')`, now \$3."),
        (
            "```python\nprice = '$100'\n```\nCost $200.",
            "```python\nprice = '$100'\n```\nCost \\$200.",
        ),
        (
            "[A $2 example](https://example.com/$123) costs $3.",
            r"[A \$2 example](https://example.com/$123) costs \$3.",
        ),
        (
            "Math $2 + 2 = 4$ and $P(1+r)^n$; price $100.",
            r"Math $2 + 2 = 4$ and $P(1+r)^n$; price \$100.",
        ),
        (
            r"Math $2^{n}$ and $\frac{2}{3}$; $$2 + 3 = 5$$.",
            r"Math $2^{n}$ and $\frac{2}{3}$; $$2 + 3 = 5$$.",
        ),
        ("SGD 5000; ordinary **bold** and *italic*.", "SGD 5000; ordinary **bold** and *italic*."),
    ],
)
def test_currency_is_literal_without_breaking_math_code_or_links(text, expected):
    assert currency_safe_markdown(text) == expected
    assert currency_safe_markdown(expected) == expected
