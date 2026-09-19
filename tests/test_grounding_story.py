import json
from datetime import datetime,timezone
import pytest
from belgu.domain.contracts import ProviderResult,EvidenceDraft,EntityRef
from belgu.application.grounding import grounding
from belgu.reporting.story import build_story,export_story


def fixture(service):
    b=service.create_brand('Secret bank',['official-secret.test']);i=service.create_investigation(b.id,'Private case')
    service.add_submission(i.id,'private-candidate.test','analyst_discovery','customer secret')
    result=service.record_result(i.id,ProviderResult('page','ok',(EvidenceDraft(EntityRef('url','https://private-candidate.test/'),'page_content','https://private-candidate.test/?secret=token',datetime.now(timezone.utc),datetime.now(timezone.utc),{'title':'SECRET_CONTENT','text':'SECRET_BODY','credential_form':False,'status_code':200,'observed_ip':'198.51.100.12'}),)))
    return i.id,result.evidence_ids[0]


def test_grounding_shows_real_fields_and_text_only_limit(service):
    i,e=fixture(service)
    a=service.save_analysis(i,{'summary':'Summary','claims':[{'text':'Form exists','kind':'hypothesis','evidence_ids':[e]}]})
    g=grounding(service,i,a.id)
    assert g['claims'][0]['support'][0]['id']==e
    assert any(f['path']=='credential_form' and f['value'] is False for f in g['claims'][0]['support'][0]['fields'])
    assert g['claims'][0]['warnings']
    assert g['limitations']


def test_masked_story_excludes_private_data_from_entire_export(service):
    i,e=fixture(service)
    preview=build_story(service,i,[e],True)
    html=export_story(service,i,[e],True)
    for secret in ['private-candidate','official-secret','Secret bank','Private case','SECRET_CONTENT','SECRET_BODY','198.51.100.12','customer secret',e,i]:
        assert secret not in html
        assert secret not in json.dumps(preview)
    assert 'data:image' not in html
    assert 'Önceki' in html and 'Sonraki' in html
    assert 'fetch(' not in html and 'https://' not in html


def test_unmasked_story_selection_and_case_scope(service):
    i,e=fixture(service);other,other_e=fixture(service)
    raw=build_story(service,i,[e],False)
    assert any('SECRET_CONTENT' in s['body'] for s in raw['steps'])
    from belgu.application.service import NotFoundError
    with pytest.raises(NotFoundError):build_story(service,i,[other_e],False)
    assert export_story(service,i,[e],False).startswith('<!doctype html>')


def test_story_export_freezes_preview_even_after_new_evidence(service):
    from belgu.reporting.story import save_story_preview
    i,e=fixture(service)
    preview=save_story_preview(service,i,[],False)
    service.record_result(i,ProviderResult('browser_capture','ok',(EvidenceDraft(EntityRef('url','https://private-candidate.test/'),'page_browser','https://private-candidate.test/',datetime.now(timezone.utc),datetime.now(timezone.utc),{'title':'NEW_CONTENT_AFTER_PREVIEW'}),)))
    html=export_story(service,i,[],False,preview['preview_id'])
    assert 'SECRET_CONTENT' in html and 'NEW_CONTENT_AFTER_PREVIEW' not in html
    with pytest.raises(ValueError):export_story(service,i,[],True,preview['preview_id'])


def test_certificate_and_kit_citations_show_actual_values(service):
    i,e=fixture(service)
    result=service.record_result(i,ProviderResult('crtsh','ok',(EvidenceDraft(EntityRef('domain','private-candidate.test'),'certificate_transparency','urn:cert',None,datetime.now(timezone.utc),{'certificate_id':123,'names':['private-candidate.test'],'issuer':'Fixture CA','not_after':'2027-01-01','signals':['fixture-pattern']}),)))
    a=service.save_analysis(i,{'summary':'Certificate','claims':[{'text':'Certificate exists','kind':'observation','evidence_ids':result.evidence_ids}]})
    fields=grounding(service,i,a.id)['claims'][0]['support'][0]['fields']
    assert {f['path'] for f in fields} >= {'certificate_id','names','issuer','not_after','signals'}


def test_negative_dns_claim_exposes_actual_response_code(service):
    i,_=fixture(service)
    when=datetime.now(timezone.utc)
    result=service.record_result(i,ProviderResult('dns','ok',(
        EvidenceDraft(EntityRef('domain','private-candidate.test'),'dns_nxdomain','urn:dns:fixture',when,when,{'rcode':'NXDOMAIN'}),)))
    a=service.save_analysis(i,{'summary':'DNS observation','claims':[{'text':'DNS returned NXDOMAIN','kind':'observation','evidence_ids':result.evidence_ids}]})
    fields=grounding(service,i,a.id)['claims'][0]['support'][0]['fields']
    assert fields==[{'path':'rcode','value':'NXDOMAIN'}]
