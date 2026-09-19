"""Offline adversarial response fixtures: no live model required."""
import json

import pytest


def test_assistant_rejects_case_fabrication_and_alias_substrings():
    from belgu.analysis.assistant import AssistantError, validate_assistant_output
    aliases = {'E001': {'investigation_id': 'current', 'evidence_id': 'real'}}
    for alias in ('E001 extra', 'e001', 'E001,E002', 'real', 'E002'):
        raw = {'answer': 'Yanıt', 'claims': [{'text': 'İddia', 'kind': 'observation', 'evidence_aliases': [alias]}], 'actions': [], 'uncertainties': []}
        with pytest.raises(AssistantError):
            validate_assistant_output(json.dumps(raw), aliases)


def test_unsubstantiated_claim_and_extra_output_keys_fail():
    from belgu.analysis.assistant import AssistantError, validate_assistant_output
    for raw in (
        {'answer': 'Yanıt', 'claims': [{'text': 'İddia', 'kind': 'observation', 'evidence_aliases': []}], 'actions': [], 'uncertainties': []},
        {'answer': 'Yanıt', 'claims': [], 'actions': [], 'uncertainties': [], 'execute': 'command'},
    ):
        with pytest.raises(AssistantError):
            validate_assistant_output(json.dumps(raw), {})
