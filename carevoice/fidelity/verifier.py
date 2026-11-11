"""Conservative source-evidence verification for clinical draft claims."""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from carevoice.structure.schemas import (
    ABCContent,
    ABCEpisode,
    Claim,
    FreeContent,
    Measure,
    SOAPContent,
    StructuredDraft,
)

IssueCode = Literal[
    "missing_transcript",
    "missing_evidence",
    "evidence_not_found",
    "numeric_claim_not_grounded",
    "measure_value_not_grounded",
    "measure_unit_not_grounded",
    "measure_expression_not_grounded",
]


@dataclass(frozen=True)
class FidelityIssue:
    code: IssueCode
    path: str


@dataclass(frozen=True)
class FidelityReport:
    grounded: bool
    claims_checked: int
    measures_checked: int
    issues: tuple[FidelityIssue, ...]


_WORD_PATTERN = re.compile(r"\d+(?:[.,]\d+)?|[^\W\d_]+", re.UNICODE)
_NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?", re.UNICODE)
_UNIT_PATTERNS: dict[str, re.Pattern[str]] = {
    "percentage": re.compile(r"%|\bpor\s+cento\b|\bpercentual\b", re.IGNORECASE),
    "seconds": re.compile(r"\bsegundos?\b|\bsecs?\b", re.IGNORECASE),
    "minutes": re.compile(r"\bminutos?\b|\bmins?\b", re.IGNORECASE),
    "count": re.compile(r"\bvez(?:es)?\b|\bocorr[eê]ncias?\b|\bcontagem\b", re.IGNORECASE),
    "scale": re.compile(r"\bescalas?\b|\bpontos?\b", re.IGNORECASE),
}


def verify_draft_fidelity(draft: StructuredDraft, transcript: str) -> FidelityReport:
    """Require each asserted claim and measure to point to a matching source quote.

    This verifies textual provenance, not semantic entailment; clinician review remains required.
    """
    issues: list[FidelityIssue] = []
    claims = tuple(_iter_claims(draft.content))
    measures = tuple(_iter_measures(draft.content))
    if not transcript.strip() and (claims or measures):
        issues.append(FidelityIssue(code="missing_transcript", path="transcript"))
        return FidelityReport(
            grounded=False,
            claims_checked=len(claims),
            measures_checked=len(measures),
            issues=tuple(issues),
        )

    for path, claim in claims:
        evidence_text = _validate_evidence(path, claim, transcript, issues)
        if evidence_text:
            claim_numbers = _numbers(claim.text)
            source_numbers = _numbers(evidence_text)
            if not claim_numbers.issubset(source_numbers):
                issues.append(FidelityIssue(code="numeric_claim_not_grounded", path=path))

    for path, measure in measures:
        evidence_text = _validate_measure_evidence(path, measure, transcript, issues)
        if evidence_text:
            normalized_value = _normalize_number(measure.value)
            if normalized_value not in _numbers(evidence_text):
                issues.append(FidelityIssue(code="measure_value_not_grounded", path=path))
            if not _UNIT_PATTERNS[measure.unit].search(evidence_text):
                issues.append(FidelityIssue(code="measure_unit_not_grounded", path=path))
            if not _contains_quote(measure.original_expression, evidence_text):
                issues.append(
                    FidelityIssue(code="measure_expression_not_grounded", path=path)
                )

    return FidelityReport(
        grounded=not issues,
        claims_checked=len(claims),
        measures_checked=len(measures),
        issues=tuple(issues),
    )


def _validate_evidence(
    path: str,
    claim: Claim,
    transcript: str,
    issues: list[FidelityIssue],
) -> str:
    if not claim.evidence:
        issues.append(FidelityIssue(code="missing_evidence", path=path))
        return ""
    valid_quotes = _verified_quotes(
        path,
        (item.quote for item in claim.evidence),
        transcript,
        issues,
    )
    return " ".join(valid_quotes)


def _validate_measure_evidence(
    path: str,
    measure: Measure,
    transcript: str,
    issues: list[FidelityIssue],
) -> str:
    if not measure.evidence:
        issues.append(FidelityIssue(code="missing_evidence", path=path))
        return ""
    valid_quotes = _verified_quotes(
        path,
        (item.quote for item in measure.evidence),
        transcript,
        issues,
    )
    return " ".join(valid_quotes)


def _verified_quotes(
    path: str,
    quotes: Iterable[str],
    transcript: str,
    issues: list[FidelityIssue],
) -> list[str]:
    verified: list[str] = []
    for quote in quotes:
        if not _contains_quote(quote, transcript):
            issues.append(FidelityIssue(code="evidence_not_found", path=path))
        else:
            verified.append(quote)
    return verified


def _contains_quote(quote: str, source: str) -> bool:
    quote_tokens = _tokens(quote)
    source_tokens = _tokens(source)
    if not quote_tokens or len(quote_tokens) > len(source_tokens):
        return False
    window_length = len(quote_tokens)
    return any(
        source_tokens[index : index + window_length] == quote_tokens
        for index in range(len(source_tokens) - window_length + 1)
    )


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(token.replace(",", ".") for token in _WORD_PATTERN.findall(normalized))


def _numbers(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value)
    return {_normalize_number(match.group()) for match in _NUMBER_PATTERN.finditer(normalized)}


def _normalize_number(value: Decimal | str) -> str:
    decimal_value = Decimal(str(value).replace(",", "."))
    return format(decimal_value.normalize(), "f")


def _iter_claims(
    content: SOAPContent | ABCContent | FreeContent,
) -> list[tuple[str, Claim]]:
    result: list[tuple[str, Claim]] = []
    match content:
        case SOAPContent():
            for field_name in ("subjective", "objective", "assessment", "plan", "parent_summary"):
                result.extend(
                    (f"content.{field_name}[{index}]", claim)
                    for index, claim in enumerate(getattr(content, field_name))
                )
        case ABCContent():
            for index, episode in enumerate(content.episodes):
                result.extend(_episode_claims(index, episode))
            result.extend(
                (f"content.parent_summary[{index}]", claim)
                for index, claim in enumerate(content.parent_summary)
            )
        case FreeContent():
            for section_index, section in enumerate(content.sections):
                result.extend(
                    (f"content.sections[{section_index}].claims[{claim_index}]", claim)
                    for claim_index, claim in enumerate(section.claims)
                )
            result.extend(
                (f"content.parent_summary[{index}]", claim)
                for index, claim in enumerate(content.parent_summary)
            )
    return result


def _episode_claims(index: int, episode: ABCEpisode) -> list[tuple[str, Claim]]:
    claims = [
        (f"content.episodes[{index}].antecedent", episode.antecedent),
        (f"content.episodes[{index}].behavior", episode.behavior),
        (f"content.episodes[{index}].consequence", episode.consequence),
    ]
    if episode.hypothesized_function is not None:
        claims.append(
            (f"content.episodes[{index}].hypothesized_function", episode.hypothesized_function)
        )
    return claims


def _iter_measures(
    content: SOAPContent | ABCContent | FreeContent,
) -> list[tuple[str, Measure]]:
    return [
        (f"content.measures[{index}]", measure)
        for index, measure in enumerate(content.measures)
    ]
