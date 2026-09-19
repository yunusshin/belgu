from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw


def encoded(image, fmt='PNG'):
    output = BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def controls():
    image = Image.new('RGB', (640, 420), '#eeeeee')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 640, 65), fill='#124b42')
    draw.rectangle((50, 100, 330, 330), fill='#bad7c8')
    for y in (140, 190, 240):
        draw.rectangle((80, y, 290, y+20), fill='#315f48')
    draw.rectangle((400, 280, 550, 320), fill='#ab6134')
    other = Image.new('RGB', image.size, '#40214c')
    d = ImageDraw.Draw(other)
    for x in range(40, 640, 120):
        d.ellipse((x, 50, x+60, 390), fill='#ffc14d')
    shifted = Image.new('RGB', image.size, '#eeeeee')
    shifted.paste(image, (100, 80))
    return image, shifted, other


def test_perceptual_controls_rank_exact_and_transforms_above_unrelated():
    from belgu.core.visual_similarity import compare_images
    image, shifted, other = controls()
    exact = compare_images(encoded(image), encoded(image))
    jpeg = compare_images(encoded(image), encoded(image, 'JPEG'))
    resized = compare_images(encoded(image), encoded(image.resize((960, 630))))
    moved = compare_images(encoded(image), encoded(shifted))
    unrelated = compare_images(encoded(image), encoded(other))
    assert exact['score'] == 100
    assert exact['score'] > moved['score']
    assert exact['score'] > unrelated['score']
    assert jpeg['score'] > 90 and resized['score'] > 90
    assert set(exact['components']) == {'perceptual', 'structure', 'color'}
    assert exact['method_version']


def test_blank_unreadable_and_incompatible_geometry_are_unassessed():
    from belgu.core.visual_similarity import compare_images
    image, _, _ = controls()
    blank = encoded(Image.new('RGB', image.size, 'white'))
    for left, right, reason in ((encoded(image), blank, 'low_detail'), (blank, blank, 'low_detail'),
                               (encoded(image), b'bad image', 'unreadable'),
                               (encoded(image), encoded(image.resize((390, 844))), 'incompatible_geometry')):
        result = compare_images(left, right)
        assert result['status'] == 'unassessed'
        assert result['score'] is None
        assert reason in result['reason']


def test_repository_fictional_pages_are_not_high_similarity():
    from belgu.core.visual_similarity import compare_images
    assets = Path(__file__).parents[1] / 'src/belgu/demo/assets'
    result = compare_images((assets/'fictional-reference.png').read_bytes(), (assets/'fictional-login.png').read_bytes())
    assert result['status'] == 'assessed'
    assert result['score'] < 80


def test_ranking_deduplicates_bytes_reports_missing_and_preserves_scope(service):
    from datetime import datetime, timezone
    from belgu.application.visual_similarity import rank_captures
    from belgu.domain.contracts import EntityRef, EvidenceDraft, ProviderResult
    from belgu.application.service import NotFoundError
    import pytest
    brand = service.create_brand('Visual fixture', ['fixture.test'])
    case = service.create_investigation(brand.id, 'Visual fixture')
    other = service.create_investigation(brand.id, 'Other scope')
    reference = service.attach_to_brand(brand.id, encoded(controls()[0]), 'image/png')
    def record(inv, data, artifact_id=None):
        artifact = artifact_id or service.attach_to_investigation(inv.id, data, 'image/png').id
        now = datetime.now(timezone.utc)
        result = service.record_result(inv.id, ProviderResult('browser_capture', 'ok', (
            EvidenceDraft(EntityRef('url','https://fixture.test/'), 'page_browser', 'https://fixture.test/', now, now,
                          {'artifact_id': artifact, 'url': 'https://fixture.test/', 'profile': 'desktop'}),)))
        return result.evidence_ids[0]
    first = record(case, encoded(controls()[0]))
    second = record(case, encoded(controls()[0]))
    missing = record(case, b'', 'missing-artifact')
    foreign = record(other, encoded(controls()[0]))
    result = rank_captures(service, case.id, reference.id)
    assert result['coverage'] == {'captures': 3, 'assessed_unique': 1, 'unassessed': 1, 'duplicates': 1}
    assert set(result['items'][0]['evidence_ids']) == {first, second}
    assert result['items'][0]['score'] == 100
    assert result['unassessed'][0]['evidence_id'] == missing
    assert foreign not in str(result)
    assert result['reference']['artifact_id'] == reference.id
    with pytest.raises(NotFoundError):
        rank_captures(service, case.id, foreign)


def test_capture_reference_excludes_itself_and_withholds_cross_profile_score(service):
    from datetime import datetime, timezone
    from belgu.application.visual_similarity import rank_captures
    from belgu.domain.contracts import EntityRef, EvidenceDraft, ProviderResult
    brand = service.create_brand('Profiles', ['fixture.test'])
    case = service.create_investigation(brand.id, 'Profiles')
    ids = []
    for profile in ('desktop', 'mobile'):
        artifact = service.attach_to_investigation(case.id, encoded(controls()[0]), 'image/png')
        now = datetime.now(timezone.utc)
        ids += service.record_result(case.id, ProviderResult('browser_capture', 'ok', (
            EvidenceDraft(EntityRef('url','https://fixture.test/'), 'page_browser', 'https://fixture.test/', now, now,
                          {'artifact_id':artifact.id,'profile':profile}),))).evidence_ids
    result = rank_captures(service, case.id, ids[0])
    assert result['items'] == []
    assert len(result['unassessed']) == 1
    assert result['unassessed'][0]['evidence_id'] == ids[1]
    assert result['unassessed'][0]['reason'] == 'incompatible_profile'
