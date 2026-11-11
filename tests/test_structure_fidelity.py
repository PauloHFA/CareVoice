from datetime import date

import pytest
from pydantic import ValidationError

from carevoice.domain.identity import PatientRecord
from carevoice.fidelity.verifier import verify_draft_fidelity
from carevoice.structure.patient_match import resolve_patient_candidate
from carevoice.structure.schemas import StructuredDraft


def _claim(text: str, *quotes: str) -> dict[str, object]:
    return {
        "text": text,
        "evidence": [{"quote": quote} for quote in quotes],
    }


def test_soap_draft_requires_template_fields_and_preserves_source_evidence() -> None:
    draft = StructuredDraft.model_validate(
        {
            "patient_id": "patient-123",
            "session_date": "2026-11-10",
            "template": "SOAP",
            "content": {
                "kind": "SOAP",
                "subjective": [_claim("Responsável relatou melhora.", "A mãe relatou melhora.")],
                "objective": [_claim("Acertou aproximadamente 80%.", "Quase 80% de acerto.")],
                "assessment": [],
                "plan": [],
                "parent_summary": [],
                "measures": [
                    {
                        "value": "80",
                        "unit": "percentage",
                        "is_approximate": True,
                        "original_expression": "Quase 80%",
                        "goal_id": None,
                        "evidence": [{"quote": "Quase 80% de acerto."}],
                    }
                ],
            },
        }
    )

    report = verify_draft_fidelity(
        draft,
        "A mãe relatou melhora. Quase 80% de acerto.",
    )

    assert draft.session_date == date(2026, 11, 10)
    assert report.grounded is True
    assert report.claims_checked == 2
    assert report.measures_checked == 1
    assert report.issues == ()


def test_abc_function_is_only_included_when_explicitly_present() -> None:
    draft = StructuredDraft.model_validate(
        {
            "patient_id": "patient-123",
            "session_date": "2026-11-10",
            "template": "ABC",
            "content": {
                "kind": "ABC",
                "episodes": [
                    {
                        "antecedent": _claim(
                            "Foi solicitado sentar.",
                            "Após a solicitação para sentar",
                        ),
                        "behavior": _claim("Levantou da cadeira.", "ele levantou da cadeira"),
                        "consequence": _claim(
                            "A atividade foi interrompida.",
                            "a atividade foi interrompida",
                        ),
                        "hypothesized_function": None,
                    }
                ]
            },
        }
    )

    report = verify_draft_fidelity(
        draft,
        "Após a solicitação para sentar, ele levantou da cadeira e a atividade foi interrompida.",
    )

    assert report.grounded is True
    assert report.claims_checked == 3


def test_evidence_quotes_may_be_separate_source_spans() -> None:
    draft = StructuredDraft.model_validate(
        {
            "patient_id": "patient-123",
            "session_date": "2026-11-10",
            "template": "FREE",
            "content": {
                "kind": "FREE",
                "sections": [
                    {
                        "title": "Observações",
                        "claims": [
                            {
                                "text": "Pareou cores e acertou 80%.",
                                "evidence": [
                                    {"quote": "Pareou cores."},
                                    {"quote": "Acertou 80%."},
                                ],
                            }
                        ],
                    }
                ]
            },
        }
    )

    report = verify_draft_fidelity(draft, "Pareou cores. Depois, acertou 80%.")

    assert report.grounded is True


@pytest.mark.parametrize(
    ("claim_text", "quote", "expected_issue"),
    [
        ("Obteve 90% de acerto.", "Obteve 80% de acerto.", "numeric_claim_not_grounded"),
        ("Concluiu a tarefa.", "O paciente descansou.", "evidence_not_found"),
    ],
)
def test_verifier_blocks_unsupported_claims(
    claim_text: str,
    quote: str,
    expected_issue: str,
) -> None:
    draft = StructuredDraft.model_validate(
        {
            "patient_id": "patient-123",
            "session_date": "2026-11-10",
            "template": "SOAP",
            "content": {
                "kind": "SOAP",
                "objective": [_claim(claim_text, quote)],
            },
        }
    )

    report = verify_draft_fidelity(draft, "Obteve 80% de acerto.")

    assert report.grounded is False
    assert expected_issue in {issue.code for issue in report.issues}


@pytest.mark.parametrize(
    ("value", "unit", "expression", "expected_issue"),
    [
        ("15", "minutes", "15 minutos", None),
        ("20", "minutes", "20 minutos", "measure_value_not_grounded"),
        ("15", "seconds", "15 minutos", "measure_unit_not_grounded"),
        ("15", "minutes", "aproximadamente 15 minutos", "measure_expression_not_grounded"),
    ],
)
def test_measures_require_supported_value_unit_and_original_expression(
    value: str,
    unit: str,
    expression: str,
    expected_issue: str | None,
) -> None:
    draft = StructuredDraft.model_validate(
        {
            "patient_id": "patient-123",
            "session_date": "2026-11-10",
            "template": "FREE",
            "content": {
                "kind": "FREE",
                "measures": [
                    {
                        "value": value,
                        "unit": unit,
                        "is_approximate": False,
                        "original_expression": expression,
                        "evidence": [{"quote": "Tolerou a atividade por 15 minutos."}],
                    }
                ]
            },
        }
    )

    report = verify_draft_fidelity(draft, "Tolerou a atividade por 15 minutos.")

    if expected_issue is None:
        assert report.grounded is True
    else:
        assert report.grounded is False
        assert expected_issue in {issue.code for issue in report.issues}


def test_schema_rejects_mismatched_templates_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="SOAP template requires"):
        StructuredDraft.model_validate(
            {
                "patient_id": "patient-123",
                "session_date": "2026-11-10",
                "template": "SOAP",
                "content": {"kind": "ABC", "episodes": []},
            }
        )
    with pytest.raises(ValidationError, match="extra"):
        StructuredDraft.model_validate(
            {
                "patient_id": "patient-123",
                "session_date": "2026-11-10",
                "template": "SOAP",
                "unexpected": "field",
                "content": {"kind": "SOAP"},
            }
        )


def test_json_validation_is_strict_and_rejects_non_positive_measure() -> None:
    with pytest.raises(ValidationError):
        StructuredDraft.from_json(
            """
            {
              "patient_id": "patient-123",
              "session_date": "2026-11-10",
              "template": "FREE",
              "content": {
                "kind": "FREE",
                "measures": [{
                  "value": 0,
                  "unit": "count",
                  "is_approximate": false,
                  "original_expression": "zero",
                  "evidence": [{"quote": "nenhuma ocorrência"}]
                }]
              }
            }
            """
        )


def test_missing_transcript_blocks_a_nonempty_draft() -> None:
    draft = StructuredDraft.model_validate(
        {
            "patient_id": "patient-123",
            "session_date": "2026-11-10",
            "template": "SOAP",
            "content": {
                "kind": "SOAP",
                "objective": [_claim("Fez uma atividade.", "Fez uma atividade.")],
            },
        }
    )

    report = verify_draft_fidelity(draft, "")

    assert report.grounded is False
    assert report.issues[0].code == "missing_transcript"


def test_patient_matching_requires_selection_for_homonyms() -> None:
    patients = [
        PatientRecord(
            id="patient-1",
            display_name="José da Silva",
            alias="J1",
            birth_date=None,
            template="SOAP",
            active=True,
        ),
        PatientRecord(
            id="patient-2",
            display_name="Jose da Silva",
            alias="J2",
            birth_date=None,
            template="ABC",
            active=True,
        ),
    ]

    result = resolve_patient_candidate("josé da silva", patients)

    assert result.status == "ambiguous"
    assert result.patient is None
    assert {patient.id for patient in result.candidates} == {"patient-1", "patient-2"}


def test_patient_matching_is_exact_and_never_uses_a_partial_guess() -> None:
    patients = [
        PatientRecord(
            id="patient-1",
            display_name="Lucas",
            alias="Lu",
            birth_date=None,
            template="SOAP",
            active=True,
        )
    ]

    assert resolve_patient_candidate(" LU ", patients).patient == patients[0]
    assert resolve_patient_candidate("Lucas Silva", patients).status == "not_found"
    assert resolve_patient_candidate("   ", patients).status == "not_found"
