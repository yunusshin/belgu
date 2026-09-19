import json


def test_doctor_reports_database_and_explicit_model_state(tmp_path, capsys, monkeypatch):
    from belgu.cli import main

    monkeypatch.setenv("BELGU_MODEL_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("BELGU_MODEL_TIMEOUT", "1")
    main(["doctor", "--data-dir", str(tmp_path)])
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["model"]["status"] == "unavailable"
    assert output["database"].startswith("sqlite:///")
