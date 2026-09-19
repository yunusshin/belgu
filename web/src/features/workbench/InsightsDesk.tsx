import { useEffect, useState } from 'react';
import {
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  GitCompareArrows,
  ListFilter,
  Plus,
} from 'lucide-react';
import { api, casePath, query, useResource } from '../../api/client';
import type {
  Candidate,
  Candidates,
  CollectionRun,
  RunChanges,
  Runs,
  WorkbenchProps,
} from '../../api/workbench';
import { Badge, date, Empty, ErrorBox, Loading, Success } from '../../components/UI';
import { DeskHeading, displayValue, errorMessage, EvidenceLinks, Limitations } from './Common';
import '../../styles/research-explorer.css';
const priorityLabels = { high: 'Yüksek öncelik', medium: 'Orta öncelik', low: 'Düşük öncelik' };
const strengthLabels = { strong: 'Güçlü sinyal', moderate: 'Orta sinyal', weak: 'Zayıf sinyal' };
export function CandidateDesk({ inv, refresh, onChange, onEvidence }: WorkbenchProps) {
  const scope = inv.id;
  const [pagination, setPagination] = useState<{ scope: string; page: number; cursors: (string | null)[] }>({
    scope,
    page: 0,
    cursors: [null],
  });
  const page = pagination.scope === scope ? pagination.page : 0;
  const cursors = pagination.scope === scope ? pagination.cursors : [null];
  const resource = useResource<Candidates & { next_cursor?: string | null }>(
    `${casePath(inv.id)}/candidates?${query({ limit: 30, cursor: cursors[page] })}`,
    refresh,
  );
  useEffect(() => {
    if (!resource.loading && resource.data && !resource.data.items.length && page > 0)
      setPagination({ scope, page: 0, cursors: [null] });
  }, [resource.loading, resource.data, page, scope]);
  return (
    <>
      <DeskHeading
        eyebrow="İLİŞKİLERİ İZLEYİN"
        title="Sıradaki incelemeyi kanıt seçsin."
        action={resource.data && <Badge>{resource.data.total_unique} aday</Badge>}
      >
        Ortak altyapı ve içerik izlerinden açıklanabilir bir araştırma sırası. Puanlar olasılık veya aktör
        atfı değildir.
      </DeskHeading>
      {resource.error ? (
        <ErrorBox message={resource.error} onRetry={resource.reload} />
      ) : resource.loading ? (
        <Loading label="Adayların dayanakları hazırlanıyor" />
      ) : !resource.data?.items.length ? (
        <div className="panel">
          <Empty title="Henüz sıralanacak aday yok" icon={<ListFilter size={30} />}>
            Keşif sırasında toplanan IP, sertifika ve içerik ilişkileri burada dayanaklarıyla sıralanır.
          </Empty>
        </div>
      ) : (
        <div className="desk-candidates">
          {resource.data.items.map((candidate, index) => (
            <CandidateCard
              key={candidate.entity_id}
              candidate={candidate}
              index={page * 30 + index}
              invId={inv.id}
              submitted={
                !!inv.submissions?.some(
                  (s) =>
                    s.target.hostname === candidate.domain || s.target.canonical_value === candidate.domain,
                )
              }
              onChange={onChange}
              onEvidence={onEvidence}
            />
          ))}
        </div>
      )}
      <nav className="research-candidate-pagination" aria-label="Aday sayfaları">
        <span>
          {resource.data?.total_unique
            ? `${page * 30 + 1}–${page * 30 + resource.data.items.length} / ${resource.data.total_unique} aday`
            : '0 aday'}
        </span>
        <div>
          <button
            className="icon-button"
            aria-label="Önceki aday sayfası"
            disabled={!page || resource.loading}
            onClick={() => setPagination({ scope, page: page - 1, cursors })}
          >
            <ChevronLeft size={16} />
          </button>
          <span>{page + 1}</span>
          <button
            className="icon-button"
            aria-label="Sonraki aday sayfası"
            disabled={!resource.data?.next_cursor || resource.loading}
            onClick={() => {
              if (resource.data?.next_cursor)
                setPagination({
                  scope,
                  page: page + 1,
                  cursors: [...cursors.slice(0, page + 1), resource.data.next_cursor],
                });
            }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </nav>
    </>
  );
}
function CandidateCard({
  candidate,
  index,
  invId,
  submitted,
  onChange,
  onEvidence,
}: {
  candidate: Candidate;
  index: number;
  invId: string;
  submitted: boolean;
  onChange: () => void;
  onEvidence: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false),
    [added, setAdded] = useState(false),
    [error, setError] = useState('');
  async function add() {
    setBusy(true);
    setError('');
    try {
      await api.post(`${casePath(invId)}/submissions`, {
        value: candidate.domain,
        source: 'analyst_discovery',
        note: '',
      });
      setAdded(true);
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="panel desk-candidate">
      <div className="desk-candidate-top">
        <span className="desk-rank">{String(index + 1).padStart(2, '0')}</span>
        <div>
          <h3 className="mono">{candidate.domain}</h3>
          <Badge
            tone={
              candidate.priority === 'high' ? 'accent' : candidate.priority === 'medium' ? 'amber' : 'neutral'
            }
          >
            {priorityLabels[candidate.priority]}
          </Badge>
        </div>
        <div className="desk-score">
          <strong>{candidate.score}</strong>
          <span>öncelik puanı</span>
        </div>
      </div>
      <div className="desk-reasons">
        {candidate.reasons.map((reason, i) => (
          <div key={i}>
            <div>
              <span className={`desk-signal ${reason.strength}`} />
              <strong>{reason.label}</strong>
              <Badge>{strengthLabels[reason.strength]}</Badge>
            </div>
            <EvidenceLinks ids={reason.evidence_ids} onEvidence={onEvidence} />
          </div>
        ))}
      </div>
      <Limitations items={candidate.limitations} />
      {!candidate.reasons.length && <p className="muted">Sıralama dayanağı sağlanmamış.</p>}
      <footer>
        <span className="small muted">{new Set(candidate.evidence_ids).size} kaynak kaydı</span>
        <button className="button" disabled={busy || added || submitted} onClick={add}>
          {added || submitted ? <Check size={14} /> : <Plus size={14} />}
          {added || submitted ? 'Başlangıç bulgusunda' : busy ? 'Ekleniyor…' : 'Başlangıç bulgusu yap'}
        </button>
      </footer>
      {added && <Success>Başlangıç bulgusuna eklendi.</Success>}
      {error && <ErrorBox message={error} />}
    </article>
  );
}
const runLabel = (run: CollectionRun) =>
  `${date(run.created_at, true)} · ${run.evidence_count} kanıt${run.approximate ? ' · yaklaşık' : ''}${run.status === 'partial' ? ' · kısmi' : run.status === 'failed' ? ' · başarısız' : ''}`;
export function ChangesDesk({ inv, refresh, onEvidence }: WorkbenchProps) {
  const runs = useResource<Runs>(`${casePath(inv.id)}/runs`, refresh);
  const [chosenBefore, setBefore] = useState(''),
    [chosenAfter, setAfter] = useState('');
  const before = chosenBefore || runs.data?.items[1]?.id || '',
    after = chosenAfter || runs.data?.items[0]?.id || '';
  const changes = useResource<RunChanges>(
    runs.data && runs.data.items.length > 1 && before !== after
      ? `${casePath(inv.id)}/changes?${query({ before, after })}`
      : null,
    refresh,
  );
  return (
    <>
      <DeskHeading eyebrow="İKİ GÖZLEM ARASINDA" title="Gerçekte ne değişti?">
        Yeni gözlemler, değişen değerler ve bu çalışmada gözlenmeyen kayıtlar ayrı gösterilir. Toplama zamanı
        ve DNS TTL farkları değişiklik sayılmaz.
      </DeskHeading>
      {runs.error ? (
        <ErrorBox message={runs.error} onRetry={runs.reload} />
      ) : runs.loading ? (
        <Loading label="Keşif geçmişi yükleniyor" />
      ) : (runs.data?.items.length || 0) < 2 ? (
        <div className="panel">
          <Empty title="Karşılaştırma için iki keşif çalışması gerekli" icon={<GitCompareArrows size={30} />}>
            Kaydedilen her yeni keşif, kendi kanıt kümesiyle karşılaştırılabilir.
          </Empty>
        </div>
      ) : (
        <>
          <div className="panel desk-run-select">
            <label>
              Önceki çalışma
              <select value={before} onChange={(e) => setBefore(e.target.value)}>
                {runs.data?.items.map((run) => (
                  <option key={run.id} value={run.id}>
                    {runLabel(run)}
                  </option>
                ))}
              </select>
            </label>
            <ArrowRight size={18} />
            <label>
              Sonraki çalışma
              <select value={after} onChange={(e) => setAfter(e.target.value)}>
                {runs.data?.items.map((run) => (
                  <option key={run.id} value={run.id}>
                    {runLabel(run)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {before === after ? (
            <p className="callout amber">Karşılaştırmak için iki farklı çalışma seçin.</p>
          ) : changes.error ? (
            <ErrorBox message={changes.error} onRetry={changes.reload} />
          ) : changes.loading ? (
            <Loading label="Gözlemler karşılaştırılıyor" />
          ) : (
            changes.data && (
              <>
                <div className="desk-change-counts">
                  {(
                    [
                      ['new', 'Yeni gözlem'],
                      ['changed', 'Değişen değer'],
                      ['not_observed', 'Bu çalışmada gözlenmedi'],
                    ] as const
                  ).map(([kind, label]) => (
                    <div key={kind} className={kind}>
                      <strong>{changes.data!.counts[kind]}</strong>
                      <span>{label}</span>
                    </div>
                  ))}
                </div>
                <Limitations items={changes.data.limitations} />
                {changes.data.changes.length ? (
                  <div className="desk-change-list">
                    {changes.data.changes.map((change, index) => (
                      <article className={`panel desk-change ${change.kind}`} key={index}>
                        <header>
                          <Badge tone={change.kind === 'new' ? 'accent' : 'amber'}>
                            {
                              {
                                new: 'Yeni gözlem',
                                changed: 'Değişen değer',
                                not_observed: 'Bu çalışmada gözlenmedi',
                              }[change.kind]
                            }
                          </Badge>
                          <code>{change.field}</code>
                        </header>
                        <h3>{displayValue(change.subject)}</h3>
                        <p>{change.message}</p>
                        <div className="desk-before-after">
                          <div>
                            <span>ÖNCEKİ</span>
                            <pre>{displayValue(change.before)}</pre>
                          </div>
                          <div>
                            <span>SONRAKİ</span>
                            <pre>{displayValue(change.after)}</pre>
                          </div>
                        </div>
                        {change.kind === 'not_observed' && (
                          <p className="small muted">
                            Bu sonuç kaydın ortadan kalktığını kanıtlamaz; kaynak kapsamı ve toplama hataları
                            dikkate alınmalıdır.
                          </p>
                        )}
                        <EvidenceLinks ids={change.evidence_ids} onEvidence={onEvidence} />
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="panel">
                    <Empty title="Anlamlı bir değişiklik gözlenmedi">
                      Seçili çalışmaların karşılaştırılabilir alanları aynı.
                    </Empty>
                  </div>
                )}
              </>
            )
          )}
        </>
      )}
      <p className="desk-caption">
        Yaklaşık etiketli eski çalışmalar toplama aralığından yeniden oluşturulur; eksiksiz çalışma kaydı
        olarak değerlendirilmez.
      </p>
    </>
  );
}
