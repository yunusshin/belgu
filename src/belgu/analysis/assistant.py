"""Text-only local assistant, with server-owned context and durable cited snapshots."""
from __future__ import annotations

from hashlib import sha256
import json
import ipaddress
import os
import re
from pathlib import Path
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from belgu.application.memory import cross_investigation_memory, evidence_ref, timestamp
from belgu.persistence.models import AssistantTurn, Entity, Investigation, Observation, new_id, utcnow
from .client import ModelClient, ModelClientError
from .service import _resolve_model
from .budget import input_limit, measure_input, reported_input_tokens

MAX_INPUT_TOKENS = 6144
MAX_OUTPUT_TOKENS = 1024
MAX_CONTEXT_EVIDENCE = 48
PROMPT_VERSION = 'assistant-v1'


class AssistantError(RuntimeError):
    def __init__(self, code, message, *, retryable=True):
        super().__init__(message)
        self.code, self.retryable = code, retryable


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Filters(Strict):
    q: str | None = Field(None, max_length=300)
    kind: Literal['domain', 'ip', 'url'] | None = None
    hasCapture: bool | None = None
    shared: Literal['', 'javascript', 'certificate'] | None = None
    recent: bool | None = None
    sort: Literal['name', 'latest', 'priority'] | None = None


class ApplyFilters(Strict):
    type: Literal['apply_filters']
    label: str = Field(min_length=1, max_length=120)
    filters: Filters


class OpenEvidence(Strict):
    type: Literal['open_evidence']
    label: str = Field(min_length=1, max_length=120)
    evidence_alias: str


class Claim(Strict):
    text: str = Field(min_length=1, max_length=1000)
    kind: Literal['observation', 'hypothesis']
    evidence_aliases: list[str] = Field(min_length=1, max_length=12)


class Output(Strict):
    answer: str = Field(min_length=1, max_length=4000)
    claims: list[Claim] = Field(max_length=8)
    actions: list[ApplyFilters | OpenEvidence] = Field(max_length=3)
    uncertainties: list[str] = Field(max_length=12)


def _make_client(*, transport=None, connection=None):
    if connection is not None:
        return ModelClient(**{**connection, 'timeout_seconds': min(connection['timeout_seconds'], 90)}, transport=transport)
    return ModelClient(os.getenv('BELGU_MODEL_URL', 'http://127.0.0.1:8080/v1'),
                       os.getenv('BELGU_MODEL_ID', ''), timeout_seconds=90, transport=transport,
                       backend=os.getenv('BELGU_MODEL_BACKEND', 'llama.cpp'), api_key=os.getenv('BELGU_MODEL_KEY', ''))


def validate_assistant_output(raw, aliases):
    try:
        value = Output.model_validate_json(raw)
        def resolve(alias):
            if alias not in aliases:
                raise ValueError('Snapshot dışında kanıt atfı.')
            return dict(aliases[alias])
        def prose(text):
            def description(match):
                ref = resolve(match.group(0))
                return ref.get('subject', {}).get('value', 'kayıtlı kaynak') + ' gözlemi'
            return re.sub(r'\bE[0-9]{3,}\b', description, text)
        result = {'answer': prose(value.answer), 'claims': [], 'actions': [],
                  'uncertainties': [prose(item) for item in value.uncertainties]}
        for claim in value.claims:
            result['claims'].append({'text': prose(claim.text), 'kind': claim.kind,
                                     'evidence_refs': [resolve(alias) for alias in dict.fromkeys(claim.evidence_aliases)]})
        for action in value.actions:
            if isinstance(action, OpenEvidence):
                ref = resolve(action.evidence_alias)
                subject = ref.get('subject', {}).get('value', 'Kayıtlı kaynak')
                provider = ref.get('provider', 'kaynak')
                label = f'{subject[:100]} · {provider[:40]} kanıtını aç'
                result['actions'].append({'type': action.type, 'label': label,
                                          'investigation_id': ref['investigation_id'], 'evidence_id': ref['evidence_id']})
            else:
                # Strict cloud schemas require every optional property, using null
                # for unused filters. Do not pass those nulls into the UI action.
                filters = action.filters.model_dump(exclude_unset=True, exclude_none=True)
                if not filters:
                    raise ValueError('Boş veya geçersiz filtre eylemi.')
                result['actions'].append(_filter_action(filters, aliases))
        return result
    except (ValidationError, ValueError, TypeError) as exc:
        raise AssistantError('invalid_model_output', 'Model yanıtı kanıt ve eylem doğrulamasını geçemedi. Yeniden deneyin.') from exc


def _filter_action(filters, aliases):
    # Assistant actions deliberately support page-content filters only on
    # domains/URLs. IP entities cannot have captures, and shared content is
    # host membership rather than DNS relationship traversal.
    if filters.get('kind') == 'ip' and (filters.get('hasCapture') or filters.get('shared')):
        raise ValueError('IP türü sayfa görseli veya ortak içerik filtresiyle birleştirilemez.')
    query = filters.get('q', '').strip()
    try:
        address = ipaddress.ip_address(query).compressed
    except ValueError:
        address = None
    if address and filters.get('kind') != 'ip':
        # Research q searches canonical names. It does not traverse DNS relations.
        # Open the actual observation instead of offering an empty domain search.
        for ref in aliases.values():
            payload = ref.get('payload', {})
            if str(payload.get('rcode', 'NOERROR')).upper() not in {'NOERROR', '0'}:
                continue
            for field in ('observed_ip', 'answer'):
                try:
                    observed = ipaddress.ip_address(payload.get(field, '')).compressed
                except ValueError:
                    continue
                if observed == address:
                    return {'type': 'open_evidence', 'label': f'{address} IP gözlemini aç',
                            'investigation_id': ref['investigation_id'], 'evidence_id': ref['evidence_id']}
        raise ValueError('IP ilişkisi için snapshot içinde kaynak gerekli.')
    return {'type': 'apply_filters', 'label': f'Araştırmada ara: {query}' if query else 'Araştırma filtrelerini uygula',
            'filters': filters}


def list_assistant_turns(service, investigation_id, *, limit=50, before=None):
    if not 1 <= limit <= 100:
        raise ValueError('Geçersiz konuşma sayfası.')
    with service.sessions() as session:
        service._required(session, Investigation, investigation_id)
        query = select(AssistantTurn).where(AssistantTurn.investigation_id == investigation_id)
        if before:
            anchor = session.get(AssistantTurn, before)
            if anchor is None or anchor.investigation_id != investigation_id:
                raise ValueError('Geçersiz konuşma sayfası.')
            query = query.where((AssistantTurn.created_at < anchor.created_at) |
                                ((AssistantTurn.created_at == anchor.created_at) & (AssistantTurn.id < anchor.id)))
        rows = session.scalars(query.order_by(AssistantTurn.created_at.desc(), AssistantTurn.id.desc()).limit(limit + 1)).all()
        return {'items': [dict(row.output) for row in reversed(rows[:limit])],
                'next_cursor': rows[limit - 1].id if len(rows) > limit else None}


def _project(value, depth=0):
    if isinstance(value, str):
        return value[:2000]
    if depth >= 3:
        return '[ayrıntı sınırlandı]' if isinstance(value, (dict, list)) else value
    if isinstance(value, dict):
        return {str(k)[:100]: _project(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [_project(v, depth + 1) for v in value[:12]]
    return value


def _context(service, investigation_id, evidence_ids):
    from belgu.application.insights import rank_candidates
    from belgu.persistence.models import InvestigationEntity, Submission

    memory = cross_investigation_memory(service, investigation_id, limit=4)
    with service.sessions() as session:
        inv = service._required(session, Investigation, investigation_id)
        # The existing ranking scans a whole case. Call it only for bounded cases;
        # large cases retain source context and explicitly omit candidate ranking.
        capped_ranking = any(len(session.scalars(select(model.id).where(
            model.investigation_id == investigation_id).limit(cap + 1)).all()) > cap
            for model, cap in ((Observation, 1000), (InvestigationEntity, 2000), (Submission, 200)))
        ranking = {'items': [], 'total_unique': 0} if capped_ranking else rank_candidates(service, investigation_id, limit=3)
        query = select(Observation, Entity).join(Entity, Entity.id == Observation.subject_id)
        current_query = query.where(Observation.investigation_id == investigation_id)
        selected = session.execute(current_query.where(Observation.id.in_(evidence_ids))).all() if evidence_ids else []
        if evidence_ids and {row.id for row, _ in selected} != set(evidence_ids):
            raise ValueError('Seçilen kanıtlar bu araştırmada kayıtlı olmalıdır.')
        # Retrieve bounded rounds by kind: newest of each kind first, then the
        # second newest of each, etc. Repeated CT results must not displace
        # an older A response before token fitting even sees it.
        by_kind = select(Observation.id.label('evidence_id'), func.row_number().over(
            partition_by=Observation.kind,
            order_by=(Observation.retrieved_at.desc(), Observation.id),
        ).label('round')).where(Observation.investigation_id == investigation_id).subquery()
        recent = session.execute(current_query.join(by_kind, by_kind.c.evidence_id == Observation.id)
                                 .order_by(by_kind.c.round, Observation.retrieved_at.desc(), Observation.id)
                                 .limit(25)).all() if not evidence_ids else []
        ordered_ids = list(dict.fromkeys(evidence_ids))
        for item in memory['items']:
            # Each retained reason starts with a current and historical source.
            # Old current-side support must not be displaced by recent filler.
            for reason in item['reasons'][:3]:
                for case_id in (investigation_id, item['investigation_id']):
                    ref = next((ref for ref in reason['evidence_refs'] if ref['investigation_id'] == case_id), None)
                    if ref:
                        ordered_ids.append(ref['evidence_id'])
        # Preserve basic case coverage before a candidate's repeated supporting
        # CT records. Full candidate summaries remain conditional on all cited
        # support surviving the same snapshot/token fit below.
        represented_kinds = set()
        for observation, _ in recent[:24]:
            if observation.kind not in represented_kinds:
                ordered_ids.append(observation.id)
                represented_kinds.add(observation.kind)
        eligible_candidates = [item for item in ranking['items'] if len(item['evidence_ids']) <= 12]
        for item in eligible_candidates:
            ordered_ids.extend(item['evidence_ids'])
        ordered_ids.extend(row.id for row, _ in recent[:24])
        ordered_ids = list(dict.fromkeys(ordered_ids))
        omitted = max(0, len(ordered_ids) - MAX_CONTEXT_EVIDENCE)
        ordered_ids = ordered_ids[:MAX_CONTEXT_EVIDENCE]
        # All IDs originated from scoped server queries above; no model/user
        # supplied foreign IDs can enter this snapshot.
        rows = session.execute(query.where(Observation.id.in_(ordered_ids))).all() if ordered_ids else []
        by_id = {row.id: (row, subject) for row, subject in rows}
        sources = []
        for evidence_id in ordered_ids:
            if evidence_id not in by_id:
                omitted += 1
                continue
            observation, subject = by_id[evidence_id]
            ref = evidence_ref(observation, subject)
            ref['payload'] = _project(observation.payload)
            ref['projection_truncated'] = ref['payload'] != observation.payload
            if len(json.dumps(ref, ensure_ascii=False).encode()) > 16 * 1024:
                omitted += 1
                continue
            sources.append(ref)
        history = session.scalars(select(AssistantTurn).where(AssistantTurn.investigation_id == investigation_id)
                                 .order_by(AssistantTurn.created_at.desc(), AssistantTurn.id.desc()).limit(7)).all()
        return {'investigation': {'id': inv.id, 'title': inv.title, 'workflow': inv.workflow},
                'demo': inv.demo, 'sources': sources, 'memory': memory, 'candidates': eligible_candidates,
                'candidate_total': ranking['total_unique'],
                'history': [{'message': row.message, 'answer': row.output['answer'][:2000]} for row in reversed(history[:6])],
                'omissions': {'retrieval_capped': bool(len(recent) > 24 or memory['coverage']['truncated']),
                              'context_evidence': omitted, 'history_capped': len(history) > 6,
                              'token_budget_evidence': 0, 'token_budget_history': 0,
                              'candidates_retrieval_capped': capped_ranking, 'candidates_omitted': 0,
                              'memory_cases_omitted': max(0, memory['total_unique'] - len(memory['items']))}}


def _candidate_context(context, aliases):
    by_id = {ref['evidence_id']: alias for alias, ref in aliases.items()
             if ref['investigation_id'] == context['investigation']['id']}
    candidates = []
    for item in context['candidates']:
        if not set(item['evidence_ids']) <= by_id.keys():
            continue
        candidates.append({key: item[key] for key in ('domain', 'score', 'priority', 'limitations')} |
                          {'reasons': [{'label': reason['label'], 'strength': reason['strength'],
                                        'evidence_aliases': [by_id[eid] for eid in reason['evidence_ids']]}
                                       for reason in item['reasons']]})
    context['omissions']['candidates_omitted'] = context['candidate_total'] - len(candidates)
    return candidates


def _messages(context, message, sources, history):
    aliases = {f'E{index:03d}': ref for index, ref in enumerate(sources, 1)}
    by_id = {(ref['investigation_id'], ref['evidence_id']): alias for alias, ref in aliases.items()}
    memory = []
    for item in context['memory']['items']:
        refs = [ref for ref in item['evidence_refs'] if (ref['investigation_id'], ref['evidence_id']) in by_id]
        if len({ref['investigation_id'] for ref in refs}) < 2:
            continue
        memory.append({'investigation_id': item['investigation_id'], 'title': item['title'],
                       'workflow': item['workflow'], 'decision': item['decision'],
                       'evidence_aliases': [by_id[(ref['investigation_id'], ref['evidence_id'])] for ref in refs]})
    context['omissions']['memory_cases_omitted'] = context['memory']['total_unique'] - len(memory)
    candidates = _candidate_context(context, aliases)
    data = {'candidates': candidates, 'investigation': context['investigation'], 'question': message, 'history': history,
            'memory': memory, 'omissions': context['omissions'],
            'evidence': [{'alias': alias, **ref} for alias, ref in aliases.items()]}
    return [{'role': 'system', 'content': Path(__file__).with_name('prompts').joinpath('assistant-v1.txt').read_text()},
            {'role': 'user', 'content': json.dumps(data, ensure_ascii=False, separators=(',', ':'))}], aliases


def ask_assistant(service, investigation_id, message, evidence_ids=None, *, client=None, recorded_demo=False):
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
        raise ValueError('Soru 1–2000 karakter olmalıdır.')
    evidence_ids = evidence_ids or []
    if not isinstance(evidence_ids, list) or len(evidence_ids) > 12 or any(not isinstance(v, str) for v in evidence_ids):
        raise ValueError('En fazla 12 kanıt seçilebilir.')
    context = _context(service, investigation_id, evidence_ids)
    sources, history = context['sources'], context['history']
    demo = recorded_demo or context['demo']
    if demo:
        _, aliases = _messages(context, message, sources, history)
        raw = {'answer': 'Kayıtlı demo yanıtı: kaynakları açarak gözlemleri ve önceki kararları karşılaştırabilirsiniz.',
               'claims': [{'text': 'Bu kaynak araştırmada kayıtlı bir gözlemdir.', 'kind': 'observation', 'evidence_aliases': [alias]}
                          for alias in list(aliases)[:2]],
               'actions': ([{'type': 'open_evidence', 'label': 'İlk kanıtı aç', 'evidence_alias': next(iter(aliases))}] if aliases else []),
               'uncertainties': ['Deterministik demo yanıtı; yerel model çağrılmadı.', 'Ortak altyapı ve içerik tek başına atıf sağlamaz.']}
        by_id = {ref['evidence_id']: alias for alias, ref in aliases.items()}
        for item in context['memory']['items']:
            match = next((reason for reason in item['reasons']
                          if len({ref['investigation_id'] for ref in reason['evidence_refs']
                                  if ref['evidence_id'] in by_id}) == 2), None)
            if match:
                support = [by_id[ref['evidence_id']] for ref in match['evidence_refs'] if ref['evidence_id'] in by_id]
                required = [next(alias for alias in support if aliases[alias]['investigation_id'] == scope)
                            for scope in (investigation_id, item['investigation_id'])]
                support = list(dict.fromkeys(required + support))[:12]
                raw['claims'] = [{'text': match['label'] + ' iki araştırmada kayıtlıdır.',
                                  'kind': 'observation', 'evidence_aliases': support}]
                previous = next(alias for alias in support if aliases[alias]['investigation_id'] != investigation_id)
                raw['actions'].append({'type': 'open_evidence', 'label': 'Önceki kanıtı aç', 'evidence_alias': previous})
                break
        result = validate_assistant_output(json.dumps(raw), aliases)
        metadata = {'id': 'recorded-demo', 'recorded_demo': True, 'prompt_version': PROMPT_VERSION,
                    'input_tokens': None, 'output_tokens': None, 'runtime_version': None}
    else:
        owned = client is None
        if client is None:
            connection = service.integrations.configured_connection()
            client = _make_client(connection=connection) if connection is not None else _make_client()
        client.output_schema = Output.model_json_schema()
        started = monotonic()
        try:
            info = _resolve_model(client)
            while True:
                if monotonic() - started > 60:
                    raise AssistantError('model_timeout', 'Model süre sınırını aştı. Yeniden deneyin.')
                messages, aliases = _messages(context, message, sources, history)
                tokens = measure_input(client, messages)
                if tokens <= input_limit(client):
                    break
                if history:
                    context['omissions']['token_budget_history'] += len(history)
                    history = []
                elif sources:
                    keep = len(sources) // 2
                    context['omissions']['token_budget_evidence'] += len(sources) - keep
                    sources = sources[:keep]
                else:
                    raise AssistantError('token_budget_unverified', 'Soru ve sistem bağlamı token sınırına sığmadı. Daha kısa bir soru ile yeniden deneyin.')
            completion = client.complete(messages, Output.model_json_schema(), max_output_tokens=MAX_OUTPUT_TOKENS)
            result = validate_assistant_output(completion.text, aliases)
            metadata = {'id': info.id, 'runtime_version': info.runtime_version, 'recorded_demo': False,
                        'prompt_version': PROMPT_VERSION, 'input_tokens': reported_input_tokens(client, completion, tokens),
                        'input_budget_kind': getattr(client, 'budget_kind', 'tokens'), 'input_budget_units': tokens,
                        'output_tokens': completion.output_tokens}
        except ModelClientError as exc:
            message = ('Model yanıt üretirken süre sınırına ulaştı. Daha kısa bir soru ile yeniden deneyin.'
                       if exc.code == 'model_timeout' else 'Model yanıt veremedi. Yeniden deneyin.')
            raise AssistantError(exc.code, message) from exc
        finally:
            if owned:
                client.close()
    now, turn_id = utcnow(), new_id()
    supplied = {(ref['investigation_id'], ref['evidence_id']) for ref in sources}
    memory_snapshot = []
    for item in context['memory']['items']:
        refs = [ref for ref in item['evidence_refs'] if (ref['investigation_id'], ref['evidence_id']) in supplied]
        if len({ref['investigation_id'] for ref in refs}) == 2:
            memory_snapshot.append({key: item[key] for key in ('investigation_id', 'title', 'brand_name', 'workflow', 'decision')} | {'evidence_refs': refs})
    candidates = _candidate_context(context, aliases)
    for candidate in candidates:
        for reason in candidate['reasons']:
            reason['evidence_refs'] = [aliases[alias] for alias in reason.pop('evidence_aliases')]
    snapshot = {'evidence_refs': sources, 'omissions': context['omissions'], 'memory': memory_snapshot, 'candidates': candidates, 'selected_evidence_ids': evidence_ids}
    snapshot['id'] = sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    result.update({'id': turn_id, 'investigation_id': investigation_id, 'message': message.strip(),
                   'created_at': timestamp(now), 'model': metadata, 'snapshot': snapshot})
    with service.repo.transaction() as session:
        service._required(session, Investigation, investigation_id)
        session.add(AssistantTurn(id=turn_id, investigation_id=investigation_id, message=message.strip(), output=result, created_at=now))
    return result
