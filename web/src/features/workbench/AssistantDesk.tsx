import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, MessageSquare, Send } from 'lucide-react';
import { api, casePath, query, useResource } from '../../api/client';
import type { AssistantAction, AssistantHistory, AssistantTurn } from '../../api/intelligence';
import type { WorkbenchProps } from '../../api/workbench';
import { Badge, date, ErrorBox, Loading } from '../../components/UI';
import { DeskHeading, errorMessage, Limitations } from './Common';
import { useCaseWorkspace } from '../workspaceState';
import '../../styles/intelligence.css';

const examples = [
  'Hangi kanıtı incelemeliyim?',
  'Önceki araştırmalarla hangi izler ortak?',
  'Bu değerlendirmede hangi belirsizlikler var?',
];
export function AssistantDesk(props: WorkbenchProps) {
  return <Conversation key={props.inv.id} {...props} />;
}
function Conversation({ inv, refresh, onEvidence, onResearchFilter }: WorkbenchProps) {
  const history = useResource<AssistantHistory>(`${casePath(inv.id)}/assistant`, refresh);
  const [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [fresh, setFresh] = useState<AssistantTurn[]>([]),
    [older, setOlder] = useState<AssistantTurn[]>([]);
  const [before, setBefore] = useState<string | null | undefined>(),
    [loadingOlder, setLoadingOlder] = useState(false);
  const { pinnedEvidence } = useCaseWorkspace();
  const [useBoard, setUseBoard] = useState(false);
  const lastRequest = useRef<{ question: string; evidenceIds: string[] } | null>(null);
  const failedOperation = useRef<'send' | 'history'>('send');
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const turns = [
    ...new Map([...older, ...(history.data?.items || []), ...fresh].map((turn) => [turn.id, turn])).values(),
  ];
  const cursor = before === undefined ? history.data?.next_cursor : before;
  async function send(question: string, evidenceIds = useBoard ? [...pinnedEvidence] : []) {
    if (busy || !question.trim()) return;
    lastRequest.current = { question, evidenceIds: [...evidenceIds] };
    failedOperation.current = 'send';
    setBusy(true);
    setError('');
    try {
      const turn = await api.post<AssistantTurn>(`${casePath(inv.id)}/assistant`, {
        message: question.trim(),
        evidence_ids: evidenceIds,
      });
      if (alive.current) {
        setFresh((current) => [...current, turn]);
        setMessage('');
      }
    } catch (e) {
      if (alive.current) setError(errorMessage(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function loadOlder() {
    if (!cursor) return;
    failedOperation.current = 'history';
    setLoadingOlder(true);
    setError('');
    try {
      const page = await api.get<AssistantHistory>(
        `${casePath(inv.id)}/assistant?${query({ before: cursor })}`,
      );
      if (alive.current) {
        setOlder((current) => [...page.items, ...current]);
        setBefore(page.next_cursor);
      }
    } catch (e) {
      if (alive.current) setError(errorMessage(e));
    } finally {
      if (alive.current) setLoadingOlder(false);
    }
  }
  function action(value: AssistantAction) {
    if (value.type === 'open_evidence') onEvidence(value.evidence_id, value.investigation_id);
    else onResearchFilter?.(value.filters);
  }
  return (
    <>
      <DeskHeading eyebrow="KANITLA BİRLİKTE DÜŞÜNÜN" title="Araştırmaya bir soru sorun.">
        İnceleme kayıtları ve ilişkili geçmiş gözlemler üzerinden, kaynaklarıyla birlikte yanıt alın.
      </DeskHeading>
      <p className="intelligence-mode">
        <MessageSquare size={14} />
        {inv.demo
          ? 'Demo: deterministik yanıtlar, model çağrısı yok.'
          : 'Metin kanıtları · Araştırmaya özel konuşma'}
      </p>
      {history.error ? (
        <ErrorBox message={history.error} onRetry={history.reload} />
      ) : history.loading ? (
        <Loading label="Kayıtlı konuşma yükleniyor" />
      ) : (
        <>
          {cursor && (
            <button className="text-button" disabled={loadingOlder} onClick={loadOlder}>
              {loadingOlder ? 'Yükleniyor…' : 'Önceki konuşmaları yükle'}
            </button>
          )}
          {!turns.length && (
            <div className="assistant-examples">
              <span className="eyebrow">BAŞLAMAK İÇİN</span>
              {examples.map((example) => (
                <button className="panel" key={example} onClick={() => setMessage(example)}>
                  <span>{example}</span>
                  <ArrowUpRight size={15} />
                </button>
              ))}
            </div>
          )}
          <div className="assistant-conversation" aria-live="polite">
            {turns.map((turn) => (
              <article className="assistant-turn" key={turn.id}>
                <div className="assistant-question">
                  <span className="eyebrow">SORUNUZ</span>
                  <p>{turn.message}</p>
                </div>
                <div className="panel assistant-answer">
                  <header>
                    <strong>Belgü</strong>
                    <Badge>{turn.model.recorded_demo ? 'Kayıtlı demo yanıtı' : 'Model yanıtı'}</Badge>
                    <time>{date(turn.created_at, true)}</time>
                  </header>
                  <p>{turn.answer}</p>
                  <div className="assistant-claims">
                    {turn.claims.map((claim, index) => (
                      <section key={index}>
                        <Badge>{claim.kind === 'observation' ? 'Gözlem' : 'Çıkarım'}</Badge>
                        <p>{claim.text}</p>
                        <div className="desk-evidence-links">
                          {claim.evidence_refs.map((ref) => (
                            <button
                              className="text-button"
                              key={`${ref.investigation_id}:${ref.evidence_id}`}
                              onClick={() => onEvidence(ref.evidence_id, ref.investigation_id)}
                            >
                              <span>
                                {ref.investigation_id === inv.id ? 'Bu araştırma' : 'Önceki araştırma'} ·{' '}
                                {ref.subject.value}
                              </span>
                              <ArrowUpRight size={12} />
                            </button>
                          ))}
                        </div>
                      </section>
                    ))}
                  </div>
                  <Limitations items={turn.uncertainties} />
                  <div className="assistant-actions">
                    {turn.actions.map((value, index) => (
                      <button
                        className="button"
                        key={index}
                        disabled={value.type === 'apply_filters' && !onResearchFilter}
                        onClick={() => action(value)}
                      >
                        {value.label}
                        <ArrowUpRight size={13} />
                      </button>
                    ))}
                  </div>
                  <details className="assistant-snapshot">
                    <summary>{turn.snapshot.evidence_refs.length} kaynak içeren kayıtlı bağlam</summary>
                    <p>
                      Yanıt anındaki kaynak alanları saklanır; kanıt düğmeleri kaynağın güncel kaydını açar.
                    </p>
                    <code>{turn.snapshot.id}</code>
                    {(turn.snapshot.omissions.retrieval_capped ||
                      turn.snapshot.omissions.context_evidence > 0 ||
                      turn.snapshot.omissions.token_budget_evidence > 0 ||
                      turn.snapshot.omissions.token_budget_history > 0 ||
                      turn.snapshot.omissions.history_capped ||
                      turn.snapshot.omissions.memory_cases_omitted > 0 ||
                      (turn.snapshot.omissions.candidates_omitted || 0) > 0 ||
                      turn.snapshot.omissions.candidates_retrieval_capped) && (
                      <p>
                        Bağlam sınırlı: {turn.snapshot.omissions.token_budget_evidence} kaynak ve{' '}
                        {turn.snapshot.omissions.token_budget_history} konuşma token sınırı nedeniyle
                        dışarıda. Daha eski kayıtlar ve ilişkili araştırmaların bir bölümü kapsam dışında
                        olabilir.
                      </p>
                    )}
                  </details>
                </div>
              </article>
            ))}
          </div>
          {busy && <Loading label="Asistan kanıtları değerlendiriyor" />}
          {error && (
            <ErrorBox
              message={error}
              onRetry={() =>
                failedOperation.current === 'send' && lastRequest.current
                  ? send(lastRequest.current.question, lastRequest.current.evidenceIds)
                  : loadOlder()
              }
            />
          )}
          <form
            className="panel assistant-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send(message);
            }}
          >
            <label htmlFor={`assistant-question-${inv.id}`}>Araştırma sorusu</label>
            <textarea
              id={`assistant-question-${inv.id}`}
              value={message}
              disabled={busy}
              maxLength={2000}
              rows={3}
              placeholder="Örneğin: Ortak betik izi hangi önceki araştırmalarda var?"
              onChange={(event) => setMessage(event.target.value)}
            />
            <label className="assistant-board-toggle">
              <input
                type="checkbox"
                checked={useBoard}
                disabled={busy || !pinnedEvidence.length}
                onChange={(event) => setUseBoard(event.target.checked)}
              />
              Panodaki kanıtları kullan ({pinnedEvidence.length}/12)
            </label>
            <footer>
              <span>{message.length}/2000 · Yanıtlar araştırmayla saklanır.</span>
              <button className="button primary" disabled={busy || !message.trim()} type="submit">
                <Send size={14} />
                {busy ? 'Yanıt bekleniyor…' : 'Sor'}
              </button>
            </footer>
          </form>
        </>
      )}
    </>
  );
}
