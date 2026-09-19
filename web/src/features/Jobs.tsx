import { useEffect, useState } from 'react';
import { Activity, Check, ChevronDown, Clock3, Square, XCircle } from 'lucide-react';
import { api, casePath, useResource } from '../api/client';
import type { Collection, Investigation, Job } from '../api/types';
import { Badge, Empty, ErrorBox, Loading } from '../components/UI';
export const activeJob = (j: Job) => ['queued', 'running', 'pending'].includes(j.status);
const statusLabel = (s: string) =>
  ({
    queued: 'Sırada',
    running: 'Çalışıyor',
    completed: 'Tamamlandı',
    succeeded: 'Tamamlandı',
    partial: 'Kısmi sonuç',
    failed: 'Başarısız',
    cancelled: 'İptal edildi',
    pending: 'Bekliyor',
  })[s] || s;
const progressLabels: Record<string, string> = {
  requests: 'İstek',
  entities: 'Varlık',
  provider: 'Sağlayıcı',
  message: 'Durum',
  completed: 'Tamamlanan',
  remaining_requests: 'Kalan istek',
  elapsed_seconds: 'Geçen süre (sn)',
  new_entities: 'Yeni varlık',
  observations: 'Gözlem',
  provider_count: 'Kaynak denemesi',
};
const providerLabels: Record<string, string> = {
  dns: 'DNS',
  sgb: 'SGB',
  threatfox: 'ThreatFox',
  page: 'Sayfa',
  favicon: 'Site simgesi',
  urlscan: 'URLScan',
  crtsh: 'Sertifika kayıtları',
  'reverse_ip.hackertarget': 'Ters IP · HackerTarget',
  'reverse_ip.mnemonic': 'Ters IP · Mnemonic',
};
const providerStatusLabels: Record<string, string> = {
  ok: 'Tamamlandı',
  partial: 'Kısmi sonuç',
  error: 'Hata',
  unavailable: 'Kullanılamıyor',
  rate_limited: 'Kaynak kotası doldu',
  skipped: 'Atlandı',
  cancelled: 'İptal edildi',
  unknown: 'Belirtilmedi',
};
const providerErrorLabels: Record<string, string> = {
  ConnectError: 'Bağlantı kurulamadı',
  ReadTimeout: 'Yanıt süresi aşıldı',
  ConnectTimeout: 'Bağlantı süresi aşıldı',
  TimeoutError: 'Zaman aşımı',
  NetworkPolicyError: 'Ağ erişim kuralı nedeniyle alınamadı',
  feed_not_configured: 'Kaynak yapılandırılmamış',
  collection_limit: 'Çalışma sınırına ulaşıldı',
  http_status: 'HTTP yanıtı hatası',
  https_transport_failed: 'HTTPS bağlantısı kurulamadı',
  page_connecterror: 'Sayfaya bağlantı kurulamadı',
  page_connecttimeout: 'Sayfa bağlantı süresi aşıldı',
  page_readtimeout: 'Sayfa yanıt süresi aşıldı',
  upstream_rate_limited: 'Kaynak kotası doldu',
  upstream_access_denied: 'Kaynak erişimi reddetti',
};
function providerErrorLabel(code: string) {
  const httpStatus = /^upstream_http_(\d{3})$/.exec(code)?.[1];
  return httpStatus ? `HTTP ${httpStatus} yanıtı alındı` : providerErrorLabels[code] || code;
}
type ProviderOutcome = {
  provider: string;
  status: string;
  errorCode: string;
  truncated: boolean;
  attempts: number;
  observations: number;
};
function ProviderResults({ records }: { records: unknown[] }) {
  const grouped = new Map<string, ProviderOutcome>();
  for (const raw of records) {
    const record = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
    const provider = typeof record.provider === 'string' ? record.provider : 'Bilinmeyen kaynak';
    const status = typeof record.status === 'string' ? record.status : 'unknown';
    const errorCode = typeof record.error_code === 'string' ? record.error_code : '';
    const truncated = record.truncated === true;
    const key = JSON.stringify([provider, status, errorCode, truncated]);
    const result = grouped.get(key) || {
      provider,
      status,
      errorCode,
      truncated,
      attempts: 0,
      observations: 0,
    };
    result.attempts += 1;
    result.observations +=
      typeof record.observations === 'number' && Number.isFinite(record.observations)
        ? record.observations
        : 0;
    grouped.set(key, result);
  }
  const outcomes = [...grouped.values()];
  const observations = outcomes.reduce((total, result) => total + result.observations, 0);
  return (
    <section className="provider-results" aria-label="Kaynak sonuçları">
      <header>
        <strong>Kaynak sonuçları</strong>
        <span>
          {records.length} deneme · {observations} gözlem
        </span>
      </header>
      <ul className="provider-results-list" tabIndex={0} aria-label="Kaynak sonucu listesi">
        {outcomes.map((result, index) => (
          <li className="provider-result" key={index}>
            <div className="provider-result-heading">
              <strong>{providerLabels[result.provider] || result.provider}</strong>
              <Badge
                tone={
                  result.status === 'ok'
                    ? 'accent'
                    : result.status === 'error'
                      ? 'danger'
                      : result.status === 'partial'
                        ? 'amber'
                        : 'neutral'
                }
              >
                {providerStatusLabels[result.status] || statusLabel(result.status)}
              </Badge>
            </div>
            <div className="provider-result-counts">
              <span>{result.attempts} deneme</span>
              <span>{result.observations} gözlem</span>
            </div>
            {result.errorCode && (
              <p className="provider-result-error">{providerErrorLabel(result.errorCode)}</p>
            )}
            {result.truncated && (
              <p className="provider-result-error">Sonuçlar çalışma sınırıyla kısıtlandı.</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
export function JobCard({ job, onChange }: { job: Job; onChange: () => void }) {
  const [expanded, setExpanded] = useState(false),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const running = activeJob(job),
    progress = job.progress || {};
  async function cancel() {
    setBusy(true);
    try {
      await api.post(`/jobs/${job.id}/cancel`);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className={`job-card ${running ? 'running' : ''}`}>
      <div className="job-heading">
        <span className="job-icon">
          {running ? (
            <Activity size={18} />
          ) : job.status === 'failed' ? (
            <XCircle size={18} />
          ) : (
            <Check size={18} />
          )}
        </span>
        <div>
          <strong>
            {job.kind === 'analysis'
              ? 'Kanıt analizi'
              : job.kind === 'expand'
                ? 'Varlık genişletme'
                : job.kind === 'capture'
                  ? 'Görsel kanıt toplama'
                  : 'Keşif çalışması'}
          </strong>
          <small>{typeof progress.message === 'string' ? progress.message : statusLabel(job.status)}</small>
        </div>
        <Badge
          tone={
            running
              ? 'accent'
              : job.status === 'failed'
                ? 'danger'
                : job.status === 'partial'
                  ? 'amber'
                  : 'neutral'
          }
        >
          {statusLabel(job.status)}
        </Badge>
        {running && (
          <button
            className="icon-button"
            aria-label="İşi iptal et"
            disabled={busy || job.cancel_requested}
            onClick={cancel}
          >
            <Square size={13} />
          </button>
        )}
        <button
          className="icon-button"
          aria-label="İş ayrıntıları"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          <ChevronDown size={16} />
        </button>
      </div>
      {running && (
        <div className="indeterminate-progress" aria-label="İş sürüyor">
          <span />
        </div>
      )}
      {job.cancel_requested && <p className="muted small">İptal istendi. Toplanan kanıtlar korunacak.</p>}
      {job.truncated && (
        <p className="callout compact">Çalışma sınırına ulaşıldı. Mevcut sonuçlar korunuyor.</p>
      )}
      {expanded && (
        <div className="job-details">
          <dl>
            {Object.entries(progress)
              .filter(([key]) => key !== 'providers' || !Array.isArray(progress.providers))
              .map(([k, v]) => (
                <div key={k}>
                  <dt>
                    {job.kind === 'analysis' && k === 'entities'
                      ? 'İnceleme kanıtı'
                      : progressLabels[k] || k.replaceAll('_', ' ')}
                  </dt>
                  <dd className={v && typeof v === 'object' ? 'job-detail-object' : undefined}>
                    {v === null || v === undefined || v === ''
                      ? '—'
                      : typeof v === 'object'
                        ? JSON.stringify(v)
                        : String(v)}
                  </dd>
                </div>
              ))}
          </dl>
          {Array.isArray(progress.providers) && progress.providers.length > 0 && (
            <ProviderResults records={progress.providers} />
          )}
          <details>
            <summary>Çalışma sınırları</summary>
            <pre>{JSON.stringify(job.limits, null, 2)}</pre>
          </details>
          <span className="mono muted small">{job.id}</span>
        </div>
      )}
      {job.error && (
        <ErrorBox message={typeof job.error === 'string' ? job.error : JSON.stringify(job.error)} />
      )}{' '}
      {error && <ErrorBox message={error} />}
    </article>
  );
}
export function JobsPage() {
  const cases = useResource<Collection<Investigation>>('/investigations?limit=100');
  const [entries, setEntries] = useState<{ inv: Investigation; job: Job }[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [version, setVersion] = useState(0);
  useEffect(() => {
    if (!cases.data) return;
    let alive = true;
    Promise.all(cases.data.items.map((c) => api.get<Investigation>(casePath(c.id))))
      .then((values) => {
        if (alive) setEntries(values.flatMap((inv) => (inv.jobs || []).map((job) => ({ inv, job }))));
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [cases.data, version]);
  useEffect(() => {
    if (!entries.some((e) => activeJob(e.job))) return;
    const timer = setInterval(() => setVersion((v) => v + 1), 3000);
    return () => clearInterval(timer);
  }, [entries]);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ÇALIŞMALAR VE SONUÇLAR</span>
          <h1>İş merkezi</h1>
          <p>Keşif, görsel kanıt toplama, genişletme ve analiz çalışmalarının ilerleyişi.</p>
        </div>
        <Badge tone="accent">
          <Activity size={13} />
          {entries.filter((e) => activeJob(e.job)).length} etkin iş
        </Badge>
      </div>
      {cases.error || error ? (
        <ErrorBox message={cases.error || error} />
      ) : loading ? (
        <Loading />
      ) : !entries.length ? (
        <div className="panel">
          <Empty title="Henüz bir çalışma yok" icon={<Clock3 size={30} />}>
            Bir incelemede keşfi başlattığınızda ilerleyişi burada görünür.
          </Empty>
        </div>
      ) : (
        <div className="jobs-list">
          {entries.map(({ inv, job }) => (
            <section key={job.id}>
              <a className="job-case-link" href={`#/investigations/${inv.id}`}>
                {inv.title}
              </a>
              <JobCard job={job} onChange={() => setVersion((v) => v + 1)} />
            </section>
          ))}
        </div>
      )}
    </>
  );
}
