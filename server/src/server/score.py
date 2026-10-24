from server.models import (
    CheckKind,
    CheckStatus,
    Evaluation,
    Fit,
    FitCheck,
    Match,
    MatchCheck,
    Product,
    ScoreCheck,
)

# The score rules from docs/api-contract.md: what each check takes off a score of 100
POINTS: dict[CheckKind, dict[CheckStatus, int]] = {
    "match": {"pass": 0, "warn": -10, "fail": -40},
    "compatibility": {"pass": 0, "warn": -10, "fail": -40},
    "budget": {"pass": 0, "warn": -10, "fail": -20},
    "reviews": {"pass": 0, "warn": -5, "fail": -15},
}
MATCH_STATUS: dict[Match, CheckStatus] = {"matches": "pass", "unconfirmed": "warn", "mismatch": "fail"}
FIT_STATUS: dict[Fit, CheckStatus] = {"fits": "pass", "unconfirmed": "warn", "conflict": "fail"}
# Up to this share over the part's budget is a warning, more is a fail
BUDGET_TOLERANCE = 0.25
GOOD_STARS = 4.0
OK_STARS = 3.5


def scored(kind: CheckKind, status: CheckStatus, parts: list[str], reason: str) -> ScoreCheck:
    return ScoreCheck(kind=kind, status=status, parts=parts, reason=reason, points=POINTS[kind][status])


def match_check(category: str, match: MatchCheck) -> ScoreCheck:
    return scored("match", MATCH_STATUS[match.result], [category], match.reason)


def compatibility_check(fit: FitCheck) -> ScoreCheck:
    return scored("compatibility", FIT_STATUS[fit.result], fit.parts, fit.reason)


def budget_check(category: str, price: float, max_price: float) -> ScoreCheck:
    # "$180" rather than "$180.00", the way the plan states budgets
    shown = f"{max_price:,.0f}" if max_price.is_integer() else f"{max_price:,.2f}"
    budget = f"this part's ${shown} budget"
    over = round(price - max_price, 2)
    if over > 0:
        status: CheckStatus = "fail" if over > max_price * BUDGET_TOLERANCE else "warn"
        return scored("budget", status, [category], f"${over:,.2f} over {budget}.")
    if over == 0:
        return scored("budget", "pass", [category], f"Right at {budget}.")
    return scored("budget", "pass", [category], f"${-over:,.2f} under {budget}.")


def reviews_check(category: str, stars: float | None) -> ScoreCheck:
    if stars is None:
        return scored("reviews", "warn", [category], "No customer rating yet.")
    status: CheckStatus = "pass" if stars >= GOOD_STARS else "warn" if stars >= OK_STARS else "fail"
    return scored("reviews", status, [category], f"Rated {stars:g} out of 5.")


def score_product(
    category: str,
    product: Product,
    match: MatchCheck | None,
    fits: list[FitCheck],
    max_price: float | None = None,
) -> Evaluation:
    """Score a product in code from Claude's verdicts, so the same checks always give the same score.

    match is Claude's verdict on whether the product is what the part and the request call
    for. fits are its checks of the product against the setup, empty when nothing in the
    setup depends on it. Without max_price, the price isn't scored.
    """
    checks = [match_check(category, match)] if match else []
    checks += [compatibility_check(fit) for fit in fits]
    if max_price is not None:
        checks.append(budget_check(category, product.price, max_price))
    checks.append(reviews_check(category, product.stars))
    return Evaluation(score=max(0, 100 + sum(check.points for check in checks)), checks=checks)
