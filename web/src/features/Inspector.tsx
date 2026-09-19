import { GroundedClaims } from './workbench/GroundedClaims';
import { useState } from 'react';
import { EVIDENCE_LIMIT, useCaseWorkspace } from './workspaceState';
import {
  ArrowRight,
  BookOpen,
  Check,
  Copy,
  FileImage,
  Layers3,
  Link2,
  Maximize2,
  Radio,
  Pin,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import { api, casePath, useResource } from '../api/client';
import type {
  Analysis,
  Collection,
  Entity,
  Evidence,
  Group,
  Investigation,
  Job,
  ModelStatus,
} from '../api/types';
import { Badge, date, Empty, ErrorBox, kindLabel, Loading, Modal, sourceLabel } from '../components/UI';
import { criterionLabel, groupTitle } from './Research';
export function Inspector({
  inv,
  group,
  entity,
  evidenceId,
  evidenceInvestigationId,
  setEvidenceId,
  onExpand,
  onAnalyze,
}: {
  inv: Investigation;
  group: Group | null;
  entity: Entity | null;
  evidenceId: string | null;
  evidenceInvestigationId?: string;
  setEvidenceId: (id: string | null) => void;
  onExpand: () => void;
  onAnalyze: () => void;
}) {
  const { pinnedEvidence, toggleEvidence } = useCaseWorkspace();
  const sourceCase = evidenceInvestigationId || inv.id;
  const foreignEvidence = !!evidenceId && sourceCase !== inv.id;
  const sourceInvestigation = useResource<Investigation>(foreignEvidence ? casePath(sourceCase) : null);
  const attachmentCase = foreignEvidence
    ? sourceInvestigation.data?.id === sourceCase
      ? sourceInvestigation.data
      : null
    : inv;
  const evidence = useResource<Evidence>(
    evidenceId ? `${casePath(sourceCase)}/evidence/${encodeURIComponent(evidenceId)}` : null,
  );
  const [copied, setCopied] = useState(false),
    [image, setImage] = useState<{ id: string; investigationId: string } | null>(null);
  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }
  return (
    <aside className="panel inspector">
      <header className="inspector-heading">
        <div className="eyebrow accent">
          <span className="status-dot" />
          {evidenceId
            ? 'KANIT KAYDI'
            : entity
              ? 'SEÇİLİ VARLIK'
              : group
                ? 'İÇERİK GRUBU'
                : 'İNCELEME BAĞLAMI'}
        </div>
        <h2>
          {evidenceId
            ? 'Kaynağa yakından bakın'
            : entity?.canonical_value || (group ? groupTitle(group) : inv.brand_name)}
        </h2>
        <p>
          {entity
            ? kindLabel(entity.kind)
            : group
              ? `${group.entity_count} varlık · ortak gözlem`
              : 'Her bağlantının arkasındaki kanıt.'}
        </p>
        {evidenceId && (
          <button className="text-button inspector-close" onClick={() => setEvidenceId(null)}>
            <X size={13} />
            Kanıtı kapat
          </button>
        )}
      </header>
      <div className="inspector-tabs">
        <button className="active">
          <BookOpen size={14} />
          Kanıtlar
        </button>
        <button onClick={onAnalyze} disabled={foreignEvidence}>
          <Sparkles size={14} />
          Model yorumu
        </button>
      </div>
      <div className="inspector-body">
        {evidenceId ? (
          <section role="region" aria-label="Kanıt ayrıntıları">
            {foreignEvidence && (
              <div className="callout foreign-evidence-context">
                <strong>Başka incelemenin kanıtı</strong>
                <span>{sourceInvestigation.data?.title || 'Kaynak inceleme'}</span>
                <a href={`#/investigations/${encodeURIComponent(sourceCase)}`}>Kaynak incelemeyi aç</a>
                <p>Bu kayıt kaynak incelemenin panosuna eklenebilir.</p>
                {sourceInvestigation.error && (
                  <ErrorBox message={sourceInvestigation.error} onRetry={sourceInvestigation.reload} />
                )}
              </div>
            )}
            {evidence.loading ? (
              <Loading />
            ) : evidence.error ? (
              <ErrorBox message={evidence.error} onRetry={evidence.reload} />
            ) : (
              evidence.data && (
                <>
                  <div className="evidence-meta">
                    <Badge tone="accent">
                      <Radio size={12} />
                      {evidence.data.provider}
                    </Badge>
                    <span className="mono small">{evidence.data.id.slice(0, 10)}</span>
                  </div>
                  <button
                    className="button inspector-pin"
                    aria-pressed={pinnedEvidence.includes(evidence.data.id)}
                    disabled={
                      foreignEvidence ||
                      (!pinnedEvidence.includes(evidence.data.id) && pinnedEvidence.length >= EVIDENCE_LIMIT)
                    }
                    onClick={() => {
                      if (!foreignEvidence) toggleEvidence(evidence.data!.id);
                    }}
                  >
                    <Pin size={14} />
                    {pinnedEvidence.includes(evidence.data.id)
                      ? 'Kanıtı panodan çıkar'
                      : 'Kanıtı panoya sabitle'}
                  </button>
                  {pinnedEvidence.length >= EVIDENCE_LIMIT && !pinnedEvidence.includes(evidence.data.id) && (
                    <p className="small muted">Pano dolu. Yeni kanıt için 12 kayıttan birini kaldırın.</p>
                  )}
                  <label className="detail-label">KAYNAK</label>
                  <div className="source-box">
                    <code>{evidence.data.source_ref || 'Kaynak adresi belirtilmemiş'}</code>
                    <button
                      className="icon-button"
                      aria-label="Kanıt kaynağını kopyala"
                      onClick={() => copy(evidence.data!.source_ref)}
                    >
                      {copied ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                  </div>
                  <dl className="evidence-dates">
                    <div>
                      <dt>Gözlem zamanı</dt>
                      <dd>{date(evidence.data.observed_at, true)}</dd>
                    </div>
                    <div>
                      <dt>Alınma zamanı</dt>
                      <dd>{date(evidence.data.retrieved_at, true)}</dd>
                    </div>
                    <div>
                      <dt>Gözlem türü</dt>
                      <dd>{kindLabel(evidence.data.kind || evidence.data.subject?.kind || '—')}</dd>
                    </div>
                  </dl>
                  <label className="detail-label">GÖZLEM İÇERİĞİ</label>
                  <div className="payload">
                    {Object.entries(evidence.data.payload || {}).map(([key, value]) => (
                      <div key={key}>
                        <span>{key.replaceAll('_', ' ')}</span>
                        <pre>{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>
                      </div>
                    ))}
                  </div>
                </>
              )
            )}
          </section>
        ) : (
          <>
            {group && (
              <>
                <label className="detail-label">BİRLEŞTİRME ÖLÇÜTÜ</label>
                <div className="criterion-box">
                  <Layers3 size={16} />
                  <p>
                    {criterionLabel(group.criterion)}
                    <code>{group.key}</code>
                  </p>
                </div>
                <label className="detail-label">
                  DAYANAK KAYITLARI <span>{group.evidence_ids.length}</span>
                </label>
                <div className="evidence-list">
                  {group.evidence_ids.slice(0, 3).map((id, i) => (
                    <button key={id} onClick={() => setEvidenceId(id)}>
                      <span className="evidence-index">E{String(i + 1).padStart(2, '0')}</span>
                      <div>
                        Kaynak gözlemi<small>{id.slice(0, 16)}</small>
                      </div>
                      <ArrowRight size={14} />
                    </button>
                  ))}
                </div>
                {group.evidence_ids.length > 3 && (
                  <details className="more-evidence">
                    <summary>{group.evidence_ids.length - 3} ek kanıt kaydı</summary>
                    {group.evidence_ids.slice(3).map((id) => (
                      <button className="text-button" key={id} onClick={() => setEvidenceId(id)}>
                        {id.slice(0, 16)}
                        <ArrowRight size={12} />
                      </button>
                    ))}
                  </details>
                )}
              </>
            )}
            {entity && (
              <>
                <label className="detail-label">VARLIK DEĞERİ</label>
                <div className="source-box">
                  <code>{entity.canonical_value}</code>
                  <button
                    className="icon-button"
                    aria-label="Varlığı kopyala"
                    onClick={() => copy(entity.canonical_value)}
                  >
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                  </button>
                </div>
                <button
                  className="button full-width"
                  onClick={onExpand}
                  disabled={inv.demo || !['domain', 'ip', 'url'].includes(entity.kind)}
                  title={
                    inv.demo
                      ? 'Demo kayıtlı gözlemleri gösterir; canlı çalışma alanında genişletebilirsiniz.'
                      : !['domain', 'ip', 'url'].includes(entity.kind)
                        ? 'Genişletme yalnız alan adı, IP adresi ve URL için kullanılabilir.'
                        : undefined
                  }
                >
                  <Maximize2 size={14} />
                  Bu varlığı genişlet
                </button>
                <p className="insight-note">
                  Grafikteki bağlantıya tıklayarak gözlemin kaynağını açın. Alan adı, IP ve dosya gözlemleri
                  ayrı kanıtlardır.
                </p>
              </>
            )}
            {!group && !entity && (
              <div className="inspector-intro">
                <span className="intro-graphic">
                  <Link2 size={27} />
                </span>
                <h3>Bağlantıdan kanıta</h3>
                <p>
                  Bir grup veya varlık seçerek ortak gözlemleri, kaynaklarını ve gözlem zamanlarını inceleyin.
                </p>
                <div className="tiny-flow">
                  <span>Grup</span>
                  <ArrowRight size={11} />
                  <span>Varlık</span>
                  <ArrowRight size={11} />
                  <span>Kanıt</span>
                </div>
              </div>
            )}
            {!entity && (inv.submissions || []).length > 0 && (
              <>
                <label className="detail-label">
                  BAŞLANGIÇ BULGULARI <span>{inv.submissions!.length}</span>
                </label>
                <div className="submission-list">
                  {inv.submissions!.slice(0, 3).map((s) => (
                    <div key={s.id}>
                      <span className="small muted">{sourceLabel(s.source)}</span>
                      <code>{s.target.raw_value}</code>
                      {s.note && <p>{s.note}</p>}
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
        {!!attachmentCase?.attachments?.length && (
          <>
            <label className="detail-label">GÖRSEL VE BELGE EKLERİ</label>
            <div className="attachment-grid">
              {attachmentCase.attachments.map((a) =>
                a.mime.startsWith('image/') ? (
                  <button
                    key={a.id}
                    onClick={() => setImage({ id: a.id, investigationId: attachmentCase.id })}
                    aria-label="Ekran görüntüsünü büyüt"
                  >
                    <img
                      src={`/api${casePath(attachmentCase.id)}/attachments/${a.id}`}
                      alt="İncelemeye eklenmiş ekran görüntüsü"
                      loading="lazy"
                    />
                    <span>
                      <FileImage size={12} />
                      Ekran görüntüsü
                      <Maximize2 size={12} />
                    </span>
                  </button>
                ) : (
                  <a
                    className="text-button"
                    key={a.id}
                    href={`/api${casePath(attachmentCase.id)}/attachments/${a.id}`}
                    download
                  >
                    Belgeyi indir
                    <ArrowRight size={13} />
                  </a>
                ),
              )}
            </div>
          </>
        )}
        <div className="inspector-footnote">
          <ShieldCheck size={14} />
          <span>Kanıt kaynağı ve zaman bilgisi korunur.</span>
        </div>
      </div>
      {image && (
        <Modal title="Ekran görüntüsü" onClose={() => setImage(null)} wide>
          <img
            className="attachment-full"
            src={`/api${casePath(image.investigationId)}/attachments/${image.id}`}
            alt="İnceleme ekran görüntüsü"
          />
        </Modal>
      )}
    </aside>
  );
}
export function AnalysisPanel({
  inv,
  refresh,
  onJob,
  onEvidence,
}: {
  inv: Investigation;
  refresh: number;
  onJob: (j: Job) => void;
  onEvidence: (id: string) => void;
}) {
  const analyses = useResource<Collection<Analysis>>(`${casePath(inv.id)}/analyses`, refresh),
    models = useResource<{ items: ModelStatus[]; status: string }>('/models', refresh);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [selected, setSelected] = useState<string | null>(null);
  const analysis = analyses.data?.items.find((a) => a.id === selected) || analyses.data?.items[0],
    model = models.data?.items[0],
    ready = model?.status === 'ready';
  const hasScopeMetadata =
    analysis?.output.analysis_scope !== undefined ||
    analysis?.output.scope_excluded_count !== undefined ||
    analysis?.output.budget_omitted_count !== undefined;
  async function run() {
    setBusy(true);
    setError('');
    try {
      const job = await api.post<Job>(`${casePath(inv.id)}/analyses`, { model_id: model?.model_id });
      onJob(job);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="analysis-layout">
      <section className="panel analysis-panel">
        <div className="analysis-header">
          <div className="analysis-symbol">
            <Sparkles size={23} />
          </div>
          <div>
            <span className="eyebrow accent">KANITA DAYALI YORUM</span>
            <h2>Model analizi</h2>
          </div>
          <button
            className="button primary"
            disabled={inv.demo || !ready || busy || !inv.evidence_count}
            onClick={run}
          >
            <Sparkles size={15} />
            {busy ? 'Başlatılıyor…' : 'Analizi başlat'}
          </button>
        </div>
        {inv.demo && (
          <p className="demo-analysis-note">
            Kayıtlı demo yanıtı. Bu ortamda model çağrısı yapılmaz.
          </p>
        )}
        {models.loading ? (
          <Loading label="Model durumu kontrol ediliyor" />
        ) : (
          !ready &&
          model?.status !== 'recorded_demo' && (
            <div className="model-unavailable">
              <span className="status-dot offline" />
              <div>
                <strong>Model kullanılamıyor</strong>
                <p>
                  {models.error ||
                    model?.message ||
                    'Model servisine ulaşılamıyor. Ayarlar bölümünden bağlantıyı kontrol edebilirsiniz.'}
                </p>
              </div>
              <button className="text-button" onClick={models.reload}>
                Yeniden kontrol et
              </button>
            </div>
          )
        )}
        {error && <ErrorBox message={error} />}{' '}
        {analyses.error ? (
          <ErrorBox message={analyses.error} onRetry={analyses.reload} />
        ) : analyses.loading ? (
          <Loading />
        ) : !analysis ? (
          <Empty title="Henüz bir analiz yok" icon={<Sparkles size={28} />}>
            Model hazır olduğunda mevcut kanıtların bir anlık görüntüsü değerlendirilir. Yorumlar, kaynak
            kayıtlarına atıf yapar.
          </Empty>
        ) : (
          <div className="analysis-content">
            <div className="analysis-meta">
              <Badge tone={analysis.recorded_demo ? 'demo' : 'accent'}>
                {analysis.recorded_demo ? 'Kayıtlı demo yanıtı' : 'Model çıktısı'}
              </Badge>
              <span>{date(analysis.created_at, true)}</span>
              {analyses.data!.items.length > 1 && (
                <select
                  aria-label="Analiz geçmişi"
                  value={analysis.id}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  {analyses.data!.items.map((a) => (
                    <option key={a.id} value={a.id}>
                      {date(a.created_at, true)}
                    </option>
                  ))}
                </select>
              )}
            </div>
            {analysis.stale && (
              <p className="callout amber">
                Bu analizden sonra kanıtlar değişti. Güncel kapsam için yeni bir analiz başlatın.
              </p>
            )}
            {analysis.output.analysis_scope === 'submitted_targets' && (
              <p className="callout" role="status">
                Hedef analizi: {analysis.output.evidence_ids?.length ?? 0} kanıt değerlendirildi. İlişkili
                varlıklara ait {analysis.output.scope_excluded_count ?? 0} kayıt bu değerlendirmenin dışında.
              </p>
            )}
            {analysis.output.analysis_scope === 'provided_evidence' && (
              <p className="callout" role="status">
                Sunulan kanıt analizi: {analysis.output.evidence_ids?.length ?? 0} kanıt değerlendirildi.
              </p>
            )}
            {(analysis.output.budget_omitted_count ?? 0) > 0 && (
              <p className="callout amber" role="status">
                Bağlam sınırı nedeniyle {analysis.output.budget_omitted_count} kayıt bu analize alınmadı.
              </p>
            )}
            {!hasScopeMetadata && (analysis.output.omitted_count ?? 0) > 0 && (
              <p className="callout amber" role="status">
                Model {analysis.output.evidence_ids?.length ?? 0} kanıtı değerlendirdi; bağlam sınırı
                nedeniyle {analysis.output.omitted_count} kayıt bu analize alınmadı.
              </p>
            )}
            <h3>Değerlendirme özeti</h3>
            <p className="analysis-summary">{analysis.output.summary || 'Özet sağlanmamış.'}</p>
            {(analysis.output.claims || []).length > 0 && (
              <>
                <label className="detail-label">BULGULAR VE DAYANAKLARI</label>
                <GroundedClaims invId={inv.id} analysis={analysis} onEvidence={onEvidence} />
              </>
            )}
            {(analysis.output.uncertainties || []).length > 0 && (
              <div className="uncertainties">
                <h3>Belirsizlikler</h3>
                <ul>
                  {analysis.output.uncertainties!.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              </div>
            )}
            {(analysis.output.next_steps || []).length > 0 && (
              <>
                <h3>Önerilen sonraki adımlar</h3>
                <ul className="next-steps">
                  {analysis.output.next_steps!.map((v, i) => (
                    <li key={i}>
                      <ArrowRight size={14} />
                      {v}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <details className="analysis-provenance">
              <summary>Analiz kaydı ve sürüm bilgisi</summary>
              <dl>
                <div>
                  <dt>Model</dt>
                  <dd>{analysis.model_id}</dd>
                </div>
                <div>
                  <dt>İstem sürümü</dt>
                  <dd>{analysis.prompt_version}</dd>
                </div>
                <div>
                  <dt>Kanıt görüntüsü</dt>
                  <dd className="mono">{analysis.snapshot_id}</dd>
                </div>
              </dl>
            </details>
          </div>
        )}
      </section>
      <aside className="panel analysis-guide">
        <span className="eyebrow">ANALİZ BAĞLANTISI</span>
        <h3>Model durumu</h3>
        <p className="mono" style={{ overflowWrap: 'anywhere' }}>{model?.model_id || 'Model seçilmedi'}</p>
        <div>
          <BookOpen size={19} />
          <strong>İnceleme kanıtları</strong>
          <span>{inv.evidence_count} kayıt</span>
        </div>
        <div>
          <Radio size={19} />
          <strong>Model bağlantısı</strong>
          <a href="#/settings">Bağlantı ayarlarını aç</a>
        </div>
        <Badge tone={ready ? 'accent' : 'neutral'}>
          {inv.demo ? 'Kayıtlı demo analizi' : ready ? 'Model hazır' : 'Model bağlantısı bekleniyor'}
        </Badge>
      </aside>
    </div>
  );
}
