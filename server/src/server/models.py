from pydantic import BaseModel, Field

# Grok structured outputs: the Field descriptions are sent to Grok as instructions


class PartPlan(BaseModel):
    category: str = Field(description="Item type, e.g. 'Graphics card', 'Fern plant' or 'String lights'")
    search_query: str = Field(description="Amazon search terms for this item")
    max_price: float = Field(description="Budget for this item in USD")


class BuildPlan(BaseModel):
    rejection: str | None = Field(
        description="Why the request can't be fulfilled, written for the user; null if it can"
    )
    budget: float = Field(description="Total budget in USD stated by the user")
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


# Amazon product data from Apify


class Product(BaseModel):
    asin: str
    title: str
    price: float
    url: str
    image: str | None = None
    stars: float | None = None


# API requests and responses


class PartChoice(BaseModel):
    category: str
    product: Product


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
