def test_demo_fixture_has_reference_scale_and_recorded_analysis(service):
    from belgu.demo.fixtures import seed_demo

    inv_id = seed_demo(service)
    detail = service.get_investigation(inv_id)
    entities = []
    cursor = None
    while True:
        page = service.list_entities(inv_id, limit=100, cursor=cursor)
        entities.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    groups = service.list_groups(inv_id, "observed_ip", limit=50)
    analyses = service.list_analyses(inv_id)
    assert detail.demo is True
    assert sum(e.kind == "domain" for e in entities) == 120
    assert sum(e.kind == "ip" for e in entities) == 100
    assert groups.total_groups == 4
    assert analyses[0].recorded_demo is True
    assert analyses[0].output["claims"][0]["evidence_ids"]


def test_workbench_demo_has_real_image_two_runs_and_paused_watch(service):
    from belgu.demo.fixtures import seed_demo
    from belgu.application.insights import list_runs,compare_runs
    from belgu.application.watches import WatchService
    from hashlib import sha256
    from pathlib import Path
    from sqlalchemy import select
    from belgu.persistence.models import Artifact
    i=seed_demo(service);count=len(service.list_evidence(i))
    brand_id=service.get_investigation(i).brand_id
    with service.sessions() as session:
        reference_ids=list(session.scalars(select(Artifact.id).where(Artifact.brand_id==brand_id)))
    assert len(reference_ids)==1
    reference,reference_path=service.get_artifact(reference_ids[0],brand_id=brand_id)
    reference_bytes=reference_path.read_bytes()
    assert reference_bytes.startswith(b'\x89PNG')
    assert reference.sha256==sha256((Path(__file__).parents[1]/'src/belgu/demo/assets/fictional-reference.png').read_bytes()).hexdigest()
    assert seed_demo(service)==i and len(service.list_evidence(i))==count
    captures=[e for e in service.list_evidence(i) if e.kind=='page_browser']
    assert len(captures)==3 and all(c.payload['credential_form'] is False for c in captures)
    artifact,path=service.get_artifact(captures[0].payload['artifact_id'],investigation_id=i)
    assert path.read_bytes().startswith(b'\x89PNG')
    assert path.read_bytes()!=reference_bytes
    assert len(list_runs(service,i)['items'])==2
    assert compare_runs(service,i)['counts']['changed']>=1
    assert WatchService(service).list(i)['items'][0]['enabled'] is False
    assert not service.list_analyses(i)[0].stale

    with service.repo.transaction() as session:
        assert list(session.scalars(select(Artifact.id).where(Artifact.brand_id==brand_id)))==reference_ids
        session.delete(session.get(Artifact,reference_ids[0]))
    reference_path.unlink()
    analyses_before=[a.id for a in service.list_analyses(i)]
    jobs_before=[j.id for j in service.list_jobs(i)]
    assert seed_demo(service)==i
    assert len(service.list_evidence(i))==count
    assert [a.id for a in service.list_analyses(i)]==analyses_before
    assert [j.id for j in service.list_jobs(i)]==jobs_before
    with service.sessions() as session:
        restored=list(session.scalars(select(Artifact.id).where(Artifact.brand_id==brand_id)))
    assert len(restored)==1
    assert service.get_artifact(restored[0],brand_id=brand_id)[1].read_bytes()==reference_bytes
    assert seed_demo(service)==i
    with service.sessions() as session:
        assert list(session.scalars(select(Artifact.id).where(Artifact.brand_id==brand_id)))==restored
