from typing import Literal

from pydantic import BaseModel, Field

# Claude structured outputs: the Field descriptions are sent to Claude as instructions


class PartPlan(BaseModel):
    category: str = Field(description="Item type, e.g. 'Graphics card', 'Fern plant' or 'String lights'")
    search_query: str = Field(description="Amazon search terms for this item")
    max_price: float = Field(description="Budget for this item in USD")


class BuildPlan(BaseModel):
    rejection: str | None = Field(
        description="Why the request can't be fulfilled, or one question asking for what's "
        "missing to plan it well (a budget, or what to buy), written for the user; null if it "
        "can be planned"
    )
    budget: float = Field(
        description="Total budget in USD: the one the user stated, or a typical one for the request"
    )
    budget_estimated: bool = Field(description="True if the user didn't state a budget")
    parts: list[PartPlan]


class PartPick(BaseModel):
    category: str
    asin: str = Field(description="ASIN of the chosen product, copied from the candidates")
    reason: str = Field(description="One sentence on why this product was chosen")


class CompatibilityCheck(BaseModel):
    parts: list[str] = Field(description="Categories of the parts this check covers")
    compatible: bool = Field(description="False only for a definite conflict")
    reason: str = Field(
        description="One sentence on why they work together, the conflict, or which detail "
        "the listings don't confirm"
    )


class Compatibility(BaseModel):
    compatible: bool = Field(description="True if no check found a conflict")
    checks: list[CompatibilityCheck]


class BuildPicks(BaseModel):
    picks: list[PartPick]
    summary: str = Field(description="Two sentences describing the overall selection")
    compatibility: Compatibility


# Plain aliases, not `type`: a `type` alias becomes a $ref in the schema, which drops the
# field descriptions below that tell Claude what each value means
Match = Literal["matches", "unconfirmed", "mismatch"]
Fit = Literal["fits", "conflict", "unconfirmed"]
PartStatus = Literal["needed", "filled", "not_needed"]


class MatchCheck(BaseModel):
    """Claude's verdict on whether a product is what the part and the request call for."""

    result: Match = Field(
        description="matches: the right kind of product for the part, and it meets every need "
        "the request states; unconfirmed: the listing doesn't confirm a stated need; mismatch: "
        "the wrong kind of product (e.g. an accessory), or it clearly misses a stated need"
    )
    reason: str = Field(
        description="One short sentence, under 15 words, in plain words a shopper understands: "
        "what the product is, or the stated need that decides it. Don't mention needs the request "
        "doesn't state"
    )


class FitCheck(BaseModel):
    """Claude's verdict on one pair of parts; server.score turns it into a scored check."""

    parts: list[str] = Field(description="Categories of the two parts this check covers")
    result: Fit = Field(
        description="fits: they work together; conflict: a definite conflict; unconfirmed: "
        "the listings don't confirm a detail that decides whether they work together"
    )
    reason: str = Field(
        description="One short sentence, under 15 words, in plain words a shopper understands, "
        "saying what it means for them (e.g. 'The Intel i5-13600K won't fit this AMD board.'): "
        "why they work together, the conflict, or which detail the listings don't confirm"
    )


class Verdict(BaseModel):
    match: MatchCheck
    covers: list[str] = Field(
        description="Other parts of the plan this product also fills on its own (e.g. an all-in-one "
        "PC's built-in screen fills Monitor), copying their categories exactly; empty for most products"
    )
    checks: list[FitCheck] = Field(description="Compatibility checks against the setup")


class CandidateVerdict(BaseModel):
    asin: str = Field(description="ASIN of the candidate, copied exactly")
    match: MatchCheck
    checks: list[FitCheck] = Field(description="Compatibility checks against the setup")


class CandidateVerdicts(BaseModel):
    candidates: list[CandidateVerdict] = Field(description="One entry per candidate")


class OpenPart(BaseModel):
    """Claude's verdict on a part of the plan that nothing in the setup was bought for."""

    category: str = Field(description="The open part's category, copied exactly")
    status: PartStatus = Field(
        description="filled: a setup item already does this part's job, so the shopper can skip "
        "buying it (e.g. an iMac's built-in screen fills Monitor); not_needed: the setup's choices "
        "make it unnecessary or a poor fit (e.g. a graphics card for a Mac); needed: still to buy"
    )
    filled_by: str | None = Field(
        description="ASIN of the setup item that fills it or makes it unnecessary, copied exactly; "
        "null when needed"
    )
    reason: str = Field(
        description="One short sentence, under 15 words, in plain words a shopper understands "
        "(e.g. 'Your iMac has a built-in 24-inch screen.'); empty when needed"
    )


class Replan(BaseModel):
    parts: list[OpenPart] = Field(description="One entry per open part")


class SameItems(BaseModel):
    indexes: list[int] = Field(description="Indexes of the listings that are the exact same product")


# Amazon product data, from Apify search results or a product page the extension reads


class Product(BaseModel):
    asin: str
    title: str
    price: float
    url: str
    image: str | None = None
    stars: float | None = None
    # How many customers gave the star rating
    ratings_count: int | None = None
    # Bullet points and spec table text, from a product page or a search run with details
    details: str | None = None


# Other stores' prices, from Google Shopping through Bright Data


class Offer(BaseModel):
    store: str
    title: str
    price: float
    url: str  # Google Shopping's page for the listing, which links to the store


# API requests and responses


class PartChoice(BaseModel):
    category: str
    product: Product
    # In the Evaluate flow, the other plan parts this setup item fills, from /api/replan
    covers: list[str] = []


class BuildPart(PartChoice):
    reason: str


class BuildResponse(BaseModel):
    transcript: str
    budget: float
    total: float
    summary: str
    parts: list[BuildPart]
    compatibility: Compatibility


class CompatibilityRequest(BaseModel):
    # Accepts BuildResponse.parts as-is, so the frontend can resend a build after a swap
    parts: list[PartChoice]


# Evaluate flow (docs/api-contract.md): the client keeps the user's setup and sends it with
# every request, so the server stores nothing between requests


class PlannedPart(PartPlan):
    search_url: str  # Amazon search for this part, filtered to its budget


class PlanResponse(BaseModel):
    transcript: str
    budget: float
    budget_estimated: bool  # the request stated no budget, so Claude chose a typical one
    parts: list[PlannedPart]


type CheckKind = Literal["match", "compatibility", "budget", "reviews"]
type CheckStatus = Literal["pass", "warn", "fail"]


class ScoreCheck(BaseModel):
    kind: CheckKind
    status: CheckStatus
    parts: list[str]  # categories the check covers
    reason: str
    points: int  # 0 or negative: what this check took off the score


class Evaluation(BaseModel):
    score: int  # 0-100: starts at 100, plus every check's points
    checks: list[ScoreCheck]
    covers: list[str] = []  # other plan parts the product also fills, like an all-in-one PC's monitor


class EvaluateRequest(BaseModel):
    request: str | None = None  # the plan's transcript: its stated needs are part of the match check
    category: str
    product: Product
    setup: list[PartChoice] = []
    max_price: float | None = None  # this part's budget from the plan; price isn't scored without it
    # The plan's parts, so a product that fills several is scored against all their budgets
    parts: list[PartPlan] = []


class ReplanRequest(BaseModel):
    request: str | None = None  # the plan's transcript
    budget: float  # the plan's total budget
    parts: list[PartPlan]  # the plan's parts as first planned, so budgets are split from the originals
    setup: list[PartChoice]


class SkippedPart(BaseModel):
    category: str
    asin: str  # the setup item that fills the part or makes it unnecessary
    reason: str


class ReplanResponse(BaseModel):
    parts: list[PlannedPart]  # still to buy, each with its share of the budget that's left
    filled: list[SkippedPart]  # done by a setup item bought for another part, like an iMac's screen
    not_needed: list[SkippedPart]  # the setup's choices made it unnecessary
    remaining: float  # the plan's budget minus the setup's total; negative when over


class AlternativesRequest(PartPlan):
    request: str | None = None  # the plan's transcript: its stated needs are part of the match check
    setup: list[PartChoice] = []
    product: Product | None = None  # the product to beat; without it, returns the best options


class Alternative(Evaluation):
    product: Product
    price_difference: float | None  # vs. the product to beat; null when there isn't one


class AlternativesResponse(BaseModel):
    alternatives: list[Alternative]


class OtherStoresRequest(BaseModel):
    product: Product  # the Amazon product the shopper is viewing


class OtherStoresResponse(BaseModel):
    offers: list[Offer]  # the same product at other stores, cheapest first
