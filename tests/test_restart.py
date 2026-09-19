from pathlib import Path


def test_case_survives_service_restart(tmp_path: Path):
    from belgu.application.service import BelguService

    db_url = f"sqlite:///{tmp_path / 'restart.db'}"
    evidence_dir = tmp_path / "evidence"
    first = BelguService.open(db_url, evidence_dir)
    brand = first.create_brand("Kalıcı", ["kalici.test"])
    investigation = first.create_investigation(brand.id, "Yeniden aç")
    first.add_submission(investigation.id, "https://kalici.test/Giris?x=1", "analyst_discovery")
    first.add_note(investigation.id, "SQLite yeniden açılacak")
    first.close()

    reopened = BelguService.open(db_url, evidence_dir)
    detail = reopened.get_investigation(investigation.id)
    assert detail.submissions[0].target.raw_value.endswith("/Giris?x=1")
    assert detail.notes[0].text == "SQLite yeniden açılacak"
    assert detail.entity_count == 2
    reopened.close()
