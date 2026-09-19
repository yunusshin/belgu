import argparse
import json

from evals import run as runner


def test_runner_passes_case_context_to_model(tmp_path, monkeypatch):
    context = {
        "targets": [{"kind": "domain", "canonical_value": "target.test", "hostname": "target.test"}],
        "brand": {"name": "Örnek", "official_domains": ["official.test"]},
        "analysis_time": "2026-09-08T12:00:00+00:00",
    }
    case = {"id": "target-time", "category": "scope_time", "context": context,
            "evidence": [], "expected_observations": [], "forbidden_claims": [], "required_uncertainties": []}
    fixtures = tmp_path / "cases.jsonl"
    fixtures.write_text(json.dumps(case) + "\n")
    seen = []
    monkeypatch.setenv("BELGU_MODEL_ID", "")
    monkeypatch.setenv("BELGU_MODEL_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setattr(runner, "get_model_status", lambda: {"status": "ready", "model_id": "fixture"})
    def analyze(evidence, supplied_context):
        seen.append(supplied_context)
        return {"metrics": {"repair_attempted": False}}
    monkeypatch.setattr(runner, "analyze_evidence", analyze)
    args = argparse.Namespace(base_url="http://127.0.0.1:8080/v1", model=None, cases=fixtures,
                              max_cases=None, output=tmp_path / "results.jsonl", resume=False, repeats=1)
    assert runner.run(args) == 0
    assert seen[0]["targets"] == context["targets"]
    assert seen[0]["brand"] == context["brand"]
    assert seen[0]["analysis_time"] == context["analysis_time"]
    assert seen[0]["evaluation_case"] == "target-time"
