"""Strict, provider-independent schemas for clinical draft output."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Template = Literal["SOAP", "ABC", "FREE"]
MeasureUnit = Literal["percentage", "seconds", "minutes", "count", "scale"]
PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceQuote(StrictModel):
    quote: str = Field(min_length=1, max_length=1000)

    @field_validator("quote")
    @classmethod
    def reject_blank_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Evidence quote cannot be blank")
        return value


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    evidence: tuple[EvidenceQuote, ...] = Field(min_length=1, max_length=10)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Claim text cannot be blank")
        return value


class Measure(StrictModel):
    value: PositiveDecimal
    unit: MeasureUnit
    is_approximate: bool = False
    original_expression: str = Field(min_length=1, max_length=200)
    goal_id: str | None = None
    evidence: tuple[EvidenceQuote, ...] = Field(min_length=1, max_length=10)


class SOAPContent(StrictModel):
    kind: Literal["SOAP"] = "SOAP"
    subjective: tuple[Claim, ...] = ()
    objective: tuple[Claim, ...] = ()
    assessment: tuple[Claim, ...] = ()
    plan: tuple[Claim, ...] = ()
    parent_summary: tuple[Claim, ...] = ()
    measures: tuple[Measure, ...] = ()


class ABCEpisode(StrictModel):
    antecedent: Claim
    behavior: Claim
    consequence: Claim
    hypothesized_function: Claim | None = None


class ABCContent(StrictModel):
    kind: Literal["ABC"] = "ABC"
    episodes: tuple[ABCEpisode, ...] = ()
    parent_summary: tuple[Claim, ...] = ()
    measures: tuple[Measure, ...] = ()


class FreeSection(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    claims: tuple[Claim, ...] = ()


class FreeContent(StrictModel):
    kind: Literal["FREE"] = "FREE"
    sections: tuple[FreeSection, ...] = ()
    parent_summary: tuple[Claim, ...] = ()
    measures: tuple[Measure, ...] = ()


Content = Annotated[
    SOAPContent | ABCContent | FreeContent,
    Field(discriminator="kind"),
]


class StructuredDraft(StrictModel):
    patient_id: str = Field(min_length=1, max_length=36)
    session_date: date
    template: Template
    content: Content

    @model_validator(mode="after")
    def content_matches_template(self) -> "StructuredDraft":
        expected: dict[str, type[StrictModel]] = {
            "SOAP": SOAPContent,
            "ABC": ABCContent,
            "FREE": FreeContent,
        }
        content_type = expected[self.template]
        if not isinstance(self.content, content_type):
            raise ValueError(f"{self.template} template requires {content_type.__name__}")
        return self

    @classmethod
    def from_json(cls, payload: str | bytes) -> "StructuredDraft":
        return cls.model_validate_json(payload, strict=True)
