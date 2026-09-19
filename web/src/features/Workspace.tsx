import { useEffect, useRef, useState, type FormEvent } from 'react';
import { CaseWorkspaceProvider, useCaseStoredState, useCaseWorkspace } from './workspaceState';
import { EvidenceBoard } from './EvidenceBoard';
import '../styles/unified-workspace.css';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  Download,
  FileText,
  FolderCheck,
  History,
  Layers3,
  PanelsTopLeft,
  Pin,
  Link2,
  MessageSquare,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
} from 'lucide-react';
import { api, casePath, useResource } from '../api/client';
import type { Entity, Group, Investigation, Job } from '../api/types';
import {
  Badge,
  date,
  decisionLabel,
  Empty,
  ErrorBox,
  Loading,
  Modal,
  sourceLabel,
  Success,
} from '../components/UI';
import { Inspector, AnalysisPanel } from './Inspector';
import { Research } from './Research';
import type { ResearchFilters } from './researchState';
import { activeJob, JobCard } from './Jobs';
import { Workbench } from './workbench/Workbench';
export default function Workspace({ id, mode }: { id: string; mode?: string }) {
  return (
    <CaseWorkspaceProvider key={id} investigationId={id}>
      <WorkspaceView id={id} mode={mode} />
    </CaseWorkspaceProvider>
  );
}
function WorkspaceView({ id, mode }: { id: string; mode?: string }) {
  const [refresh, setRefresh] = useState(0),
    [group, setGroup] = useState<Group | null>(null),
    [entity, setEntity] = useState<Entity | null>(null),
    [evidenceId, setEvidenceId] = useState<string | null>(null),
    [evidenceScope, setEvidenceScope] = useState<string | null>(null),
    [filterRequest, setFilterRequest] = useState<{ id: number; filters: Partial<ResearchFilters> } | null>(
      null,
    ),
    [decision, setDecision] = useState(false),
    [submission, setSubmission] = useState(false),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [showJobs, setShowJobs] = useState(false),
    [extraJobs, setExtraJobs] = useState<Job[]>([]);
  const [tab, storeTab] = useCaseStoredState<string>(
    id,
    'tool',
    'research',
    (value): value is string =>
      typeof value === 'string' && ['research', 'analysis', 'workbench', 'history'].includes(value),
  );
  const [visited, setVisited] = useState<string[]>([tab]);
  const [boardOpen, setBoardOpen] = useState(false);
  const { pinnedEvidence } = useCaseWorkspace();
  const sourceFocus = useRef<HTMLElement | SVGElement | null>(null);
  const sourceLabelRef = useRef<string | null>(null);
  const inspectorHost = useRef<HTMLDivElement>(null);
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 1100px)').matches);
  function setTab(value: string) {
    storeTab(value);
    setVisited((prev) => (prev.includes(value) ? prev : [...prev, value]));
  }
  function closeEvidence() {
    setEvidenceId(null);
    setEvidenceScope(null);
    requestAnimationFrame(() => {
      if (sourceFocus.current?.isConnected && sourceFocus.current.getClientRects().length) {
        sourceFocus.current.focus({ preventScroll: true });
      } else if (sourceLabelRef.current) {
        Array.from(document.querySelectorAll<HTMLElement>('button, a[href], [role="button"]'))
          .find(
            (element) =>
              element.getClientRects().length &&
              (element.getAttribute('aria-label') || element.textContent?.trim()) === sourceLabelRef.current,
          )
          ?.focus({ preventScroll: true });
      }
    });
  }
  useEffect(() => {
    const media = window.matchMedia('(max-width: 1100px)');
    const changed = () => setNarrow(media.matches);
    media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);
  useEffect(() => {
    if (!evidenceId) return;
    inspectorHost.current
      ?.querySelector<HTMLButtonElement>('.inspector-close')
      ?.focus({ preventScroll: true });
    function onKey(event: KeyboardEvent) {
      if (document.querySelector('dialog[open]')) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        closeEvidence();
      }
      if (narrow && event.key === 'Tab') {
        const buttons = Array.from(
          inspectorHost.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], input:not(:disabled), [tabindex="0"]',
          ) || [],
        ).filter((el) => el.getClientRects().length);
        const first = buttons[0],
          last = buttons.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [evidenceId, narrow]);
  const detail = useResource<Investigation>(casePath(id), refresh);
  const inv = detail.data ? { ...detail.data, demo: detail.data.demo || mode === 'demo' } : null;
  const jobs = [
      ...extraJobs.filter((e) => !inv?.jobs?.some((j) => j.id === e.id)).reverse(),
      ...(inv?.jobs || []),
    ],
    running = jobs.filter(activeJob);
  useEffect(() => {
    if (!running.length) return;
    const timer = setInterval(() => setRefresh((v) => v + 1), 2500);
    return () => clearInterval(timer);
  }, [running.length]);
  function onJob(job: Job) {
    setExtraJobs((prev) => [...prev, job]);
    setShowJobs(true);
    setRefresh((v) => v + 1);
  }
  async function discover(kind = 'collect') {
    setBusy(true);
    setError('');
    try {
      onJob(
        await api.post<Job>(`${casePath(id)}/jobs`, {
          kind,
          ...(kind === 'expand' && entity ? { entity_id: entity.id } : {}),
          limits: { max_entities: 300, max_requests: 100, max_seconds: 90 },
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function openEvidence(evidence: string, investigationId = id) {
    if (!evidenceId || !inspectorHost.current?.contains(document.activeElement)) {
      const origin = document.activeElement;
      sourceFocus.current = origin instanceof HTMLElement || origin instanceof SVGElement ? origin : null;
      sourceLabelRef.current = origin?.getAttribute('aria-label') || origin?.textContent?.trim() || null;
    }
    setEvidenceId(evidence);
    setEvidenceScope(investigationId);
  }
  function applyResearchFilter(filters: Partial<ResearchFilters>) {
    setEvidenceId(null);
    setEvidenceScope(null);
    setGroup(null);
    setEntity(null);
    setFilterRequest((previous) => ({ id: (previous?.id || 0) + 1, filters }));
    setTab('research');
  }
  if (!inv)
    return detail.error ? (
      <ErrorBox message={detail.error} onRetry={detail.reload} />
    ) : (
      <Loading label="İnceleme açılıyor" />
    );
  return (
    <div className="unified-workspace">
      <a className="back-link" href="#/">
        <ArrowLeft size={14} />
        İncelemelere dön
      </a>
      <div className="case-heading">
        <div>
          <div className="case-eyebrow">
            <span className="eyebrow">{inv.brand_name.toLocaleUpperCase('tr')}</span>
            <span className="slash">/</span>
            <span className="mono small muted">{inv.id.slice(0, 8).toUpperCase()}</span>
            <Badge tone={inv.workflow === 'closed' ? 'neutral' : 'accent'}>
              <i />
              {inv.workflow === 'closed' ? 'Kapalı' : 'Açık inceleme'}
            </Badge>
            {inv.demo && <span className="mini-demo">DEMO</span>}
          </div>
          <h1>{inv.title}</h1>
          <div className="case-subtitle">
            <span>{inv.submissions?.length || 0} başlangıç bulgusu</span>
            <i />
            <span>{date(inv.created_at, true)}</span>
            <i />
            <span>{decisionLabel(inv.disposition)}</span>
          </div>
        </div>
        <div className="case-actions">
          <ReportButton id={id} />
          <button className="button primary" onClick={() => setDecision(true)}>
            <ShieldCheck size={16} />
            Karar kaydet
          </button>
        </div>
      </div>
      <div className="case-overview">
        <div className="scope-stats">
          <div>
            <span className="stat-dot mint" />
            <strong>{inv.entity_count.toLocaleString('tr-TR')}</strong>
            <span>varlık</span>
          </div>
          <div>
            <span className="stat-dot blue" />
            <strong>{inv.evidence_count.toLocaleString('tr-TR')}</strong>
            <span>kanıt kaydı</span>
          </div>
          <div>
            <span className="stat-dot amber" />
            <strong>{inv.submissions?.length || 0}</strong>
            <span>başlangıç bulgusu</span>
          </div>
        </div>
        <button
          className="button"
          disabled={inv.demo || busy || running.some((j) => j.kind !== 'analysis')}
          title={
            inv.demo
              ? 'Demo ağ bağlantısı kullanmaz. Canlı çalışma alanında keşif başlatabilirsiniz.'
              : undefined
          }
          onClick={() => discover()}
        >
          <Play size={14} />
          {busy
            ? 'Başlatılıyor…'
            : running.some((j) => j.kind !== 'analysis')
              ? 'Keşif sürüyor'
              : 'Keşfi başlat'}
        </button>
      </div>
      {inv.demo && (
        <div className="demo-context">
          <span>
            <span className="small-square" />
            Kurmaca verilerle kayıtlı araştırma.
          </span>
        </div>
      )}
      <div className="workspace-tabs">
        <div className="tab-list">
          {[
            ['research', 'Araştırma', <Layers3 size={16} />],
            ['analysis', 'Model analizi', <Sparkles size={16} />],
            ['workbench', 'Çalışma masası', <PanelsTopLeft size={16} />],
            ['history', 'Kayıt ve geçmiş', <History size={16} />],
          ].map(([key, label, icon]) => (
            <button key={String(key)} aria-pressed={tab === key} onClick={() => setTab(String(key))}>
              {icon}
              {label}
              {key === 'history' && (
                <span className="count">{(inv.decisions?.length || 0) + (inv.notes?.length || 0)}</span>
              )}
            </button>
          ))}
        </div>
        <div className="workspace-tools">
          <button
            className="text-button board-toggle"
            aria-expanded={boardOpen}
            aria-controls="case-evidence-board"
            onClick={() => setBoardOpen(!boardOpen)}
          >
            <Pin size={14} /> Kanıt panosu <span className="count">{pinnedEvidence.length}</span>
          </button>
          <button className="text-button" onClick={() => setSubmission(true)}>
            <Plus size={14} />
            Bulgu ekle
          </button>
          {jobs.length > 0 && (
            <button className="text-button" aria-expanded={showJobs} onClick={() => setShowJobs(!showJobs)}>
              {running.length > 0 ? <span className="status-dot" /> : <Check size={14} />}{' '}
              {running.length ? `${running.length} etkin iş` : `${jobs.length} çalışma`}
              <ChevronDown size={13} />
            </button>
          )}
        </div>
      </div>
      {(error || detail.error) && <ErrorBox message={error || detail.error} />}{' '}
      {showJobs && (
        <div className="case-jobs">
          {jobs.slice(0, 5).map((job) => (
            <JobCard key={job.id} job={job} onChange={() => setRefresh((v) => v + 1)} />
          ))}
        </div>
      )}
      {boardOpen && <EvidenceBoard investigationId={id} onEvidence={openEvidence} />}
      <div
        className={`unified-tool-layout${!narrow && (tab === 'research' || evidenceId) ? ' with-inspector' : ''}`}
      >
        <div className="unified-tool-main" inert={narrow && !!evidenceId ? true : undefined}>
          {visited.map((key) => (
            <div key={key} className="unified-tool-panel" hidden={tab !== key}>
              {key === 'research' ? (
                <div className="research-layout">
                  <Research
                    inv={inv}
                    refresh={refresh}
                    group={group}
                    setGroup={(value) => {
                      setGroup(value);
                      setEvidenceId(null);
                    }}
                    entity={entity}
                    setEntity={(value) => {
                      setEntity(value);
                      setEvidenceId(null);
                    }}
                    onEvidence={openEvidence}
                    filterRequest={filterRequest}
                  />
                </div>
              ) : key === 'analysis' ? (
                <AnalysisPanel inv={inv} refresh={refresh} onJob={onJob} onEvidence={openEvidence} />
              ) : key === 'workbench' ? (
                <Workbench
                  inv={inv}
                  refresh={refresh}
                  onChange={() => setRefresh((value) => value + 1)}
                  onJob={onJob}
                  onEvidence={openEvidence}
                  onResearchFilter={applyResearchFilter}
                />
              ) : (
                <HistoryPanel inv={inv} onChange={() => setRefresh((value) => value + 1)} />
              )}
            </div>
          ))}
        </div>
        {narrow && evidenceId && <div className="evidence-overlay-backdrop" onClick={closeEvidence} />}
        <div
          ref={inspectorHost}
          className={`unified-inspector-host${narrow && evidenceId ? ' evidence-overlay' : ''}`}
          hidden={tab !== 'research' && !evidenceId}
          role={narrow && evidenceId ? 'dialog' : undefined}
          aria-modal={narrow && evidenceId ? true : undefined}
          aria-label={narrow && evidenceId ? 'Kanıt inceleyicisi' : undefined}
        >
          <Inspector
            inv={inv}
            group={group}
            entity={entity}
            evidenceId={evidenceId}
            evidenceInvestigationId={evidenceScope || id}
            setEvidenceId={(value) => (value ? openEvidence(value) : closeEvidence())}
            onExpand={() => discover('expand')}
            onAnalyze={() => {
              setEvidenceId(null);
              setTab('analysis');
            }}
          />
        </div>
      </div>
      {decision && (
        <DecisionModal
          inv={inv}
          onClose={() => setDecision(false)}
          onSaved={() => {
            setDecision(false);
            setRefresh((v) => v + 1);
            setTab('history');
          }}
        />
      )}
      {submission && (
        <SubmissionModal
          inv={inv}
          onClose={() => setSubmission(false)}
          onSaved={() => {
            setSubmission(false);
            setRefresh((v) => v + 1);
          }}
        />
      )}
    </div>
  );
}
function ReportButton({ id }: { id: string }) {
  const [open, setOpen] = useState(false),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  async function download(format: string) {
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/api${casePath(id)}/report?format=${format}`);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error?.message || 'Rapor indirilemedi.');
      }
      const blob = await response.blob(),
        url = URL.createObjectURL(blob),
        a = document.createElement('a');
      a.href = url;
      a.download = `belgu-${id.slice(0, 8)}.${format === 'markdown' ? 'md' : 'json'}`;
      a.click();
      URL.revokeObjectURL(url);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="report-dropdown">
      <button className="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Download size={15} />
        Rapor
        <ChevronDown size={13} />
      </button>
      {open && (
        <div className="dropdown-menu">
          <span>RAPORU İNDİR</span>
          <button disabled={busy} onClick={() => download('markdown')}>
            <FileText size={15} />
            Markdown raporu
          </button>
          <button disabled={busy} onClick={() => download('json')}>
            <Download size={15} />
            JSON verisi
          </button>
          {error && <ErrorBox message={error} />}
        </div>
      )}
    </div>
  );
}
function DecisionModal({
  inv,
  onClose,
  onSaved,
}: {
  inv: Investigation;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [value, setValue] = useState<string>(
      inv.disposition === 'unreviewed' ? 'needs_review' : inv.disposition,
    ),
    [note, setNote] = useState(''),
    [close, setClose] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`${casePath(inv.id)}/decisions`, { value, note });
      if (close) await api.patch(casePath(inv.id), { workflow: 'closed' });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Analist kararı" onClose={onClose}>
      <form onSubmit={save}>
        <p className="form-intro">
          Kararınız model yorumundan ayrı olarak, gerekçesiyle birlikte inceleme geçmişine kaydedilir.
        </p>
        <div className="decision-options">
          {[
            ['needs_review', 'İnceleme gerekli', 'Ek gözlem veya doğrulama gerekiyor.'],
            ['confirmed_phishing', 'Oltalama doğrulandı', 'Mevcut kanıtlar oltalama kararını destekliyor.'],
            ['benign', 'Zararsız', 'İncelenen kapsamda şüphe doğrulanmadı.'],
          ].map(([v, label, desc]) => (
            <label className={value === v ? 'selected' : ''} key={v}>
              <input
                type="radio"
                name="decision"
                value={v}
                checked={value === v}
                onChange={() => setValue(v)}
              />
              <span>
                <strong>{label}</strong>
                <small>{desc}</small>
              </span>
            </label>
          ))}
        </div>
        <label>
          Karar gerekçesi
          <textarea
            required
            rows={4}
            placeholder="Kararınızı destekleyen gözlem ve kanıtları açıklayın…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={close} onChange={(e) => setClose(e.target.checked)} />
          Bu kararla incelemeyi kapat
        </label>
        {error && <ErrorBox message={error} />}
        <footer className="modal-footer">
          <button type="button" className="button" onClick={onClose}>
            Vazgeç
          </button>
          <button className="button primary" disabled={busy}>
            <ShieldCheck size={15} />
            {busy ? 'Kaydediliyor…' : 'Kararı kaydet'}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
function SubmissionModal({
  inv,
  onClose,
  onSaved,
}: {
  inv: Investigation;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [value, setValue] = useState(''),
    [source, setSource] = useState('analyst_discovery'),
    [note, setNote] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`${casePath(inv.id)}/submissions`, { value, source, note });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Başlangıç bulgusu ekle" onClose={onClose}>
      <form onSubmit={save}>
        <label>
          Tam URL veya alan adı
          <input
            autoFocus
            required
            value={value}
            placeholder="https://supheli-adres.test/oturum"
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <label>
          Bildirim kaynağı
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="customer_report">Müşteri bildirimi</option>
            <option value="analyst_discovery">Analist keşfi</option>
            <option value="automated_discovery">Otomatik keşif</option>
          </select>
        </label>
        <label>
          Not
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && <ErrorBox message={error} />}
        <footer className="modal-footer">
          <button type="button" className="button" onClick={onClose}>
            Vazgeç
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? 'Kaydediliyor…' : 'Bulguyu kaydet'}
            <ArrowRight size={15} />
          </button>
        </footer>
      </form>
    </Modal>
  );
}
function HistoryPanel({ inv, onChange }: { inv: Investigation; onChange: () => void }) {
  const [note, setNote] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [success, setSuccess] = useState('');
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`${casePath(inv.id)}/notes`, { text: note });
      setNote('');
      setSuccess('Not inceleme geçmişine kaydedildi.');
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function upload(file: File) {
    setBusy(true);
    setError('');
    try {
      const data = new FormData();
      data.append('file', file);
      await api.request(`${casePath(inv.id)}/attachments`, { method: 'POST', body: data });
      setSuccess('Ek kaydedildi. Araştırma görünümünden açabilirsiniz.');
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const events = [
    ...(inv.decisions || []).map((d) => ({ ...d, type: 'decision', text: d.note, value: d.value })),
    ...(inv.notes || []).map((n) => ({ ...n, type: 'note', value: '' })),
  ].sort((a, b) => b.created_at.localeCompare(a.created_at));
  return (
    <div className="history-layout">
      <div>
        <section className="panel history-panel">
          <div className="section-title">
            <History size={18} />
            <h2>Değerlendirme geçmişi</h2>
            <Badge>{events.length} kayıt</Badge>
          </div>
          {events.length ? (
            <div className="timeline">
              {events.map((e, i) => (
                <article key={e.id}>
                  <span className={`timeline-icon ${e.type}`}>
                    {e.type === 'decision' ? <ShieldCheck size={16} /> : <MessageSquare size={16} />}
                  </span>
                  <div>
                    <div className="timeline-heading">
                      <strong>{e.type === 'decision' ? decisionLabel(e.value) : 'Analist notu'}</strong>
                      <time>{date(e.created_at, true)}</time>
                    </div>
                    <p>{e.text}</p>
                    <span className="small muted">
                      Analist {e.type === 'decision' ? '· Karar kaydı' : ''}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <Empty title="Henüz bir değerlendirme kaydı yok">
              Analist kararları ve notlar zaman sırasıyla burada korunur.
            </Empty>
          )}
        </section>
        <section className="panel submissions-panel">
          <div className="section-title">
            <Link2 size={18} />
            <h2>Başlangıç bulguları</h2>
          </div>
          {(inv.submissions || []).map((s, i) => (
            <article key={s.id}>
              <div>
                <span className="evidence-index">{String(i + 1).padStart(2, '0')}</span>
                <Badge>{sourceLabel(s.source)}</Badge>
              </div>
              <code>{s.target.raw_value}</code>
              {s.note && <p>{s.note}</p>}
            </article>
          ))}
        </section>
      </div>
      <aside className="panel note-panel">
        <span className="eyebrow">İNCELEME NOTLARI</span>
        <h2>Bağlamı kaybetmeyin.</h2>
        <p className="muted">
          Gözlemlerinizi ve araştırmanın sonraki adımlarını ekibiniz için kayıt altına alın.
        </p>
        <form onSubmit={save}>
          <label>
            Analist notu
            <textarea
              required
              rows={5}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Gözleminizi yazın…"
            />
          </label>
          <button className="button primary full-width" disabled={busy || !note.trim()}>
            <Plus size={15} />
            {busy ? 'Kaydediliyor…' : 'Notu kaydet'}
          </button>
        </form>
        <div className="upload-section">
          <Upload size={19} />
          <h3>Kanıt eki ekleyin</h3>
          <p>Ekran görüntüsü veya metin belgesi.</p>
          <label className="button upload-button">
            Dosya seç
            <input
              type="file"
              disabled={busy}
              accept="image/png,image/jpeg,text/plain"
              onChange={(e) => {
                if (e.target.files?.[0]) upload(e.target.files[0]);
              }}
            />
          </label>
        </div>
        {error && <ErrorBox message={error} />} {success && <Success>{success}</Success>}
      </aside>
    </div>
  );
}
