"""Conservative patient candidate resolution without automatic fuzzy selection."""

import unicodedata
from dataclasses import dataclass
from typing import Literal

from carevoice.domain.identity import PatientRecord

ResolutionStatus = Literal["matched", "ambiguous", "not_found"]


@dataclass(frozen=True)
class PatientResolution:
    status: ResolutionStatus
    candidates: tuple[PatientRecord, ...]

    @property
    def patient(self) -> PatientRecord | None:
        if self.status != "matched":
            return None
        return self.candidates[0]


def resolve_patient_candidate(
    spoken_name: str,
    patients: tuple[PatientRecord, ...] | list[PatientRecord],
) -> PatientResolution:
    """Return one exact normalized candidate or ask the user to disambiguate."""
    normalized_name = _normalize_name(spoken_name)
    if not normalized_name:
        return PatientResolution(status="not_found", candidates=())
    matches = tuple(
        patient
        for patient in patients
        if normalized_name
        in {
            _normalize_name(patient.display_name),
            _normalize_name(patient.alias or ""),
        }
    )
    if not matches:
        return PatientResolution(status="not_found", candidates=())
    if len(matches) > 1:
        return PatientResolution(status="ambiguous", candidates=matches)
    return PatientResolution(status="matched", candidates=matches)


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character) and character.isalnum()
    )
