def _case(client):
    brand = client.post("/api/brands", json={"name": "Örnek", "official_domains": ["ornek.test"]}).json()
    investigation = client.post("/api/investigations", json={"brand_id": brand["id"], "title": "Ek"}).json()
    submission = client.post(
        f"/api/investigations/{investigation['id']}/submissions",
        json={"value": "https://ek.test/giris", "source": "customer_report", "note": ""},
    ).json()
    return brand, investigation, submission


def test_attachment_is_magic_checked_scoped_and_downloadable(api):
    _, investigation, submission = _case(api)
    uploaded = api.post(
        f"/api/investigations/{investigation['id']}/attachments",
        data={"submission_id": submission["id"]},
        files={"file": ("screen.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
    )
    assert uploaded.status_code == 201
    artifact = uploaded.json()
    assert artifact["size_bytes"] == 15
    downloaded = api.get(f"/api/investigations/{investigation['id']}/attachments/{artifact['id']}")
    assert downloaded.content == b"\x89PNG\r\n\x1a\nfixture"
    assert downloaded.headers["x-content-type-options"] == "nosniff"

    _, other, _ = _case(api)
    assert api.get(f"/api/investigations/{other['id']}/attachments/{artifact['id']}").status_code == 404


def test_mime_label_cannot_bypass_attachment_content_check(api):
    _, investigation, _ = _case(api)
    rejected = api.post(
        f"/api/investigations/{investigation['id']}/attachments",
        files={"file": ("fake.png", b"<script>alert(1)</script>", "image/png")},
    )
    assert rejected.status_code == 415
    assert rejected.json()["error"]["code"] == "attachment_rejected"
