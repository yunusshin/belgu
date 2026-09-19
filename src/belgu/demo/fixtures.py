from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from belgu.domain.contracts import EvidenceDraft, EntityRef, ProviderResult, RelationDraft


def seed_demo(service) -> str:
    existing = next((item for item in service.list_investigations()
                     if item.demo and item.title == 'Kurgusal mobil bankacılık oltalama kümesi'), None)
    if existing:
        from belgu.demo.workbench import seed_workbench
        seed_workbench(service, existing.id)
        from belgu.demo.intelligence import seed_intelligence
        seed_intelligence(service, existing.id)
        return existing.id

    brand = service.create_brand("Kuzey Yıldızı Finans", ["kuzeyyildizi.test"])
    investigation = service.create_investigation(brand.id, "Kurgusal mobil bankacılık oltalama kümesi", demo=True)
    submission = service.add_submission(
        investigation.id,
        "https://guvenli-giris-kuzey.test/Mobil/Giris?kampanya=eylul&kanal=sms",
        "customer_report",
        "Kurgusal müşteri bildirimi — demo verisi, canlı hedef değildir.",
    )

    domains = [EntityRef("domain", "guvenli-giris-kuzey.test")]
    domains.extend(EntityRef("domain", f"kuzey-destek-{index:03d}.test") for index in range(1, 120))
    ips = [EntityRef("ip", f"198.51.100.{index}") for index in range(1, 101)]
    group_ips = ips[:4]
    retrieved = datetime(2026, 9, 7, 20, 15, tzinfo=timezone.utc)
    observations: list[EvidenceDraft] = []
    relations: list[RelationDraft] = []
    script_evidence = []
    page_evidence = []
    for index, domain in enumerate(domains):
        grouped_ip = group_ips[index % 4]
        observed = datetime(2026, 9, 1 + (index % 7), 10 + (index % 6), 0, tzinfo=timezone.utc)
        group_evidence_index = len(observations)
        observations.append(EvidenceDraft(
            domain,
            "dns_a",
            f"urn:belgu:demo:dns:{index:03d}",
            observed,
            retrieved,
            {
                "observed_ip": grouped_ip.value,
                "answer": grouped_ip.value,
                "fictional": True,
                "confidence_note": "Ortak IP, tek başına ortak kampanya kanıtı değildir.",
            },
        ))
        relations.append(RelationDraft(domain, grouped_ip, "resolves_to", (group_evidence_index,)))

        inventory_ip = ips[index % 100]
        inventory_index = len(observations)
        observations.append(EvidenceDraft(
            domain,
            "passive_dns_context",
            f"urn:belgu:demo:context:{index:03d}",
            observed,
            retrieved,
            {"address": inventory_ip.value, "fictional": True, "context_only": True},
        ))
        relations.append(RelationDraft(domain, inventory_ip, "historically_observed_on", (inventory_index,)))

        digest = sha256(f'belgu-fictional-script-family-{index % 4}'.encode()).hexdigest()
        script_index = len(observations)
        observations.append(EvidenceDraft(domain, 'javascript_content',
            f'https://{domain.value}/assets/app.js', observed, retrieved,
            {'js_sha256': digest, 'script_url': f'https://{domain.value}/assets/app.js',
             'bytes': 18420 + index % 4 * 2100, 'fictional': True}))
        relations.append(RelationDraft(domain, EntityRef('js_hash', digest), 'loads_script', (script_index,)))
        if index % 4 == 0:
            script_evidence.append(script_index)

        cert = sha256(f'belgu-fictional-cert-{index % 6}'.encode()).hexdigest()
        cert_index = len(observations)
        observations.append(EvidenceDraft(domain, 'tls_certificate',
            f'https://{domain.value}/', observed, retrieved,
            {'cert_sha256': cert, 'issuer': 'Kurgusal Demo CA', 'fictional': True}))
        relations.append(RelationDraft(domain, EntityRef('cert', cert), 'certificate', (cert_index,)))

        if index < 4:
            page_index = len(observations)
            observations.append(EvidenceDraft(domain, 'page_content',
                f'https://{domain.value}/Mobil/Giris', observed, retrieved,
                {'title': 'Kuzey Yıldızı — Mobil Şube',
                 'text': 'Kuzey Yıldızı Finans mobil şubenize hoş geldiniz. Hesabınızı doğrulamak için müşteri numaranız ve parolanızla devam edin. Bu ekran, Belgü gösterimi için hazırlanmış kurmaca bir örnektir.',
                 'credential_form': True, 'brand_impersonation': True,
                 'forms': [{'action': '/hesap/dogrula', 'method': 'post'}],
                 'official_domain': 'kuzeyyildizi.test', 'fictional': True}))
            page_evidence.append(page_index)

    saved = service.record_result(
        investigation.id,
        ProviderResult("recorded_demo", "ok", tuple(observations), tuple(relations)),
    )
    screenshot = Path(__file__).with_name('assets') / 'fictional-login.png'
    if screenshot.exists():
        service.attach_to_investigation(investigation.id, screenshot.read_bytes(), 'image/png', submission.id)
    service.add_note(investigation.id, "Müşteri bildiriminden başlayan araştırmada dört JS içerik grubu ve 100 benzersiz IP gözleniyor. Paylaşımlı barındırma ihtimali korunuyor; sahiplik atfı yapılmadı.")
    service.set_disposition(investigation.id, "needs_review", "Kurgusal demo: ek sayfa içeriği incelemesi gerekiyor.")
    service.save_analysis(
        investigation.id,
        {
            "summary": "Kurgusal incelemede 120 alan adı, aynı JavaScript içeriğini paylaşan dört grupta toplanıyor. İlk sayfalarda finans markasını taklit eden giriş metni ve parola alanı var. DNS geçmişindeki 100 IP araştırmayı genişletiyor; bu ortaklık tek başına aynı saldırganı göstermez.",
            "claims": [
                {
                    "text": "guvenli-giris-kuzey.test ve kuzey-destek-004.test aynı JavaScript SHA-256 değerini paylaşıyor.",
                    "evidence_ids": [saved.evidence_ids[i] for i in script_evidence[:2]],
                    "kind": "observation",
                },
                {'text': 'Başlangıç sayfasının kurmaca içerik kaydı marka taklidi metni ve parola isteyen form içeriyor.',
                 'evidence_ids': [saved.evidence_ids[page_evidence[0]]], 'kind': 'observation'},
            ],
            "uncertainties": ["IP paylaşımı kampanya veya aktör ortaklığını tek başına göstermez.", "Gösterilen sayfa ve gözlemler kurmacadır; canlı bir banka veya müşteri verisi içermez."],
            "next_steps": ["Kimlik bilgisi formu ve marka taklidi sinyallerini ayrı kanıtla doğrula.", "Sertifika ve içerik özetlerini karşılaştır."],
            "model_id": "recorded-belgu-demo",
            "runtime_version": "recorded-fixture-1",
            "prompt_version": "belgu-demo-v1",
            "metrics": {"source": "recorded_demo", "live_inference": False},
            "evidence_ids": saved.evidence_ids,
            "omitted_count": 0,
        },
        recorded_demo=True,
    )
    from belgu.demo.workbench import seed_workbench
    seed_workbench(service, investigation.id)
    from belgu.demo.intelligence import seed_intelligence
    seed_intelligence(service, investigation.id)
    return investigation.id
