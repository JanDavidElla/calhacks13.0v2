import pytest

from server.models import CheckStatus, Fit, FitCheck, Product, ScoreCheck
from server.score import budget_check, compatibility_check, reviews_check, score_product

# The examples in docs/api-contract.md
I5 = Product(
    asin="B0CPU00001",
    title="Intel Core i5-13600K Desktop Processor 14 cores LGA 1700",
    price=219.99,
    url="https://www.amazon.com/dp/B0CPU00001",
    stars=4.7,
)
RYZEN = Product(
    asin="B0CPU00002",
    title="AMD Ryzen 5 7600 6-Core AM5 Desktop Processor",
    price=169.0,
    url="https://www.amazon.com/dp/B0CPU00002",
    stars=4.8,
)
SOCKET_CONFLICT = FitCheck(
    parts=["CPU", "Motherboard"],
    result="conflict",
    reason="The i5-13600K uses the LGA 1700 socket, but the MSI B650 Tomahawk is an AMD AM5 board, "
    "so the CPU can't be installed.",
)


def fit(result: Fit) -> FitCheck:
    return FitCheck(parts=["CPU", "Motherboard"], result=result, reason="Socket check.")


def test_score_matches_the_contract_evaluate_example() -> None:
    evaluation = score_product("CPU", I5, [SOCKET_CONFLICT], max_price=180)

    assert evaluation.score == 50
    assert evaluation.checks == [
        ScoreCheck(kind="compatibility", status="fail", parts=["CPU", "Motherboard"],
                   reason=SOCKET_CONFLICT.reason, points=-40),
        ScoreCheck(kind="budget", status="warn", parts=["CPU"],
                   reason="$39.99 over this part's $180 budget.", points=-10),
        ScoreCheck(kind="reviews", status="pass", parts=["CPU"], reason="Rated 4.7 out of 5.", points=0),
    ]


def test_score_matches_the_contract_alternatives_example() -> None:
    fits = FitCheck(parts=["CPU", "Motherboard"], result="fits",
                    reason="The Ryzen 5 7600 is an AM5 CPU, so it fits the MSI B650 Tomahawk.")

    evaluation = score_product("CPU", RYZEN, [fits], max_price=180)

    assert evaluation.score == 100
    assert [(c.kind, c.status, c.reason) for c in evaluation.checks] == [
        ("compatibility", "pass", fits.reason),
        ("budget", "pass", "$11.00 under this part's $180 budget."),
        ("reviews", "pass", "Rated 4.8 out of 5."),
    ]


@pytest.mark.parametrize(
    ("result", "status", "points"),
    [("fits", "pass", 0), ("unconfirmed", "warn", -10), ("conflict", "fail", -40)],
)
def test_compatibility_check_scores_claudes_verdict(result: Fit, status: CheckStatus, points: int) -> None:
    check = compatibility_check(fit(result))

    assert (check.kind, check.status, check.points) == ("compatibility", status, points)
    assert (check.parts, check.reason) == (["CPU", "Motherboard"], "Socket check.")


@pytest.mark.parametrize(
    ("price", "max_price", "status", "points", "reason"),
    [
        (150, 180, "pass", 0, "$30.00 under this part's $180 budget."),
        (180, 180, "pass", 0, "Right at this part's $180 budget."),
        (180.01, 180, "warn", -10, "$0.01 over this part's $180 budget."),
        (225, 180, "warn", -10, "$45.00 over this part's $180 budget."),  # exactly 25% over
        (225.01, 180, "fail", -20, "$45.01 over this part's $180 budget."),
        (1550, 1199.99, "fail", -20, "$350.01 over this part's $1,199.99 budget."),
    ],
)
def test_budget_check_allows_up_to_25_percent_over_as_a_warning(
    price: float, max_price: float, status: CheckStatus, points: int, reason: str
) -> None:
    check = budget_check("CPU", price, max_price)

    assert (check.kind, check.status, check.points, check.reason) == ("budget", status, points, reason)
    assert check.parts == ["CPU"]


@pytest.mark.parametrize(
    ("stars", "status", "points", "reason"),
    [
        (4.0, "pass", 0, "Rated 4 out of 5."),
        (3.9, "warn", -5, "Rated 3.9 out of 5."),
        (3.5, "warn", -5, "Rated 3.5 out of 5."),
        (3.4, "fail", -15, "Rated 3.4 out of 5."),
        (None, "warn", -5, "No customer rating yet."),
    ],
)
def test_reviews_check_uses_the_star_rating(
    stars: float | None, status: CheckStatus, points: int, reason: str
) -> None:
    check = reviews_check("CPU", stars)

    assert (check.kind, check.status, check.points, check.reason) == ("reviews", status, points, reason)
    assert check.parts == ["CPU"]


def test_score_skips_the_budget_check_without_a_max_price() -> None:
    evaluation = score_product("CPU", I5, [])

    assert [c.kind for c in evaluation.checks] == ["reviews"]
    assert evaluation.score == 100


def test_score_with_nothing_to_check_against_has_no_compatibility_checks() -> None:
    evaluation = score_product("String lights", RYZEN.model_copy(update={"stars": None}), [], max_price=200)

    assert [c.kind for c in evaluation.checks] == ["budget", "reviews"]
    assert evaluation.score == 95


def test_score_never_goes_below_zero() -> None:
    bad = I5.model_copy(update={"price": 500, "stars": 2.1})

    evaluation = score_product("CPU", bad, [fit("conflict")] * 3, max_price=180)

    assert sum(c.points for c in evaluation.checks) == -155
    assert evaluation.score == 0
