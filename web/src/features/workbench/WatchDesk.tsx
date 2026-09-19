import { useEffect, useState, type FormEvent } from 'react';
import { Bell, Check, Clock3, Pause, Play, Plus, Radar } from 'lucide-react';
import { api, casePath, query, useResource } from '../../api/client';
import type { Collection, Entity, Job } from '../../api/types';
import type { Watch, Watches, WorkbenchProps } from '../../api/workbench';
import { Badge, date, Empty, ErrorBox, Loading, Success } from '../../components/UI';
import { DeskHeading, errorMessage } from './Common';
const intervals = [
  [5, '5 dakika'],
  [15, '15 dakika'],
  [60, '1 saat'],
  [360, '6 saat'],
  [1440, '1 gün'],
  [10080, '7 gün'],
] as const;
function IntervalOptions({ value }: { value: number }) {
  return (
    <>
      {!intervals.some(([minutes]) => minutes === value) && <option value={value}>{value} dakika</option>}
      {intervals.map(([value, label]) => (
        <option key={value} value={value}>
          {label}
        </option>
      ))}
    </>
  );
}
export function WatchDesk({ inv, refresh, onJob }: WorkbenchProps) {
  const [targetCursor, setTargetCursor] = useState<string | null>(null),
    [targetOptions, setTargetOptions] = useState<Entity[]>([]),
    [targetTotal, setTargetTotal] = useState(0);
  const resource = useResource<Watches>(`${casePath(inv.id)}/watches`, refresh),
    entities = useResource<Collection<Entity>>(
      `${casePath(inv.id)}/entities?${query({ limit: 100, cursor: targetCursor })}`,
      refresh,
    );
  useEffect(() => {
    if (!entities.data) return;
    setTargetOptions((previous) => [
      ...new Map([...previous, ...entities.data!.items].map((entity) => [entity.id, entity])).values(),
    ]);
    setTargetTotal(entities.data.total_unique);
  }, [entities.data]);
  const [entityId, setEntityId] = useState(''),
    [interval, setMinutes] = useState(60),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [message, setMessage] = useState('');
  useEffect(() => {
    setTargetCursor(null);
    setTargetOptions([]);
    setTargetTotal(0);
    setEntityId('');
  }, [inv.id]);
  useEffect(() => {
    const timer = setInterval(() => resource.reload(), 10000);
    return () => clearInterval(timer);
  }, [resource.reload]);
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api.post(`${casePath(inv.id)}/watches`, {
        entity_id: entityId || null,
        interval_minutes: interval,
        enabled: true,
      });
      resource.reload();
      setMessage('İzleme kaydedildi. Sonuçlar değiştiğinde burada bildirilir.');
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function read(id: string) {
    setError('');
    try {
      await api.post(`${casePath(inv.id)}/alerts/${encodeURIComponent(id)}/read`);
      resource.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <>
      <DeskHeading
        eyebrow="SESSİZ VE SÜREKLİ"
        title="Değişiklik olduğunda haberdar olun."
        action={
          <Badge>
            <Radar size={13} />
            {resource.data?.items.filter((w) => w.enabled).length ?? 0} etkin izleme
          </Badge>
        }
      >
        Seçtiğiniz hedefleri belirli aralıklarla kontrol edin. Aynı kalan sonuçlar bildirim oluşturmaz;
        değişiklikler ve yeni toplama hataları burada görünür.
      </DeskHeading>
      <form className="panel desk-watch-form" onSubmit={create}>
        <label>
          İzlenecek hedef
          <select value={entityId} onChange={(e) => setEntityId(e.target.value)}>
            <option value="">Tüm başlangıç bulguları</option>
            {targetOptions
              .filter((e) => ['domain', 'url', 'ip'].includes(e.kind))
              .map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.canonical_value}
                </option>
              ))}
          </select>
        </label>
        <label>
          Kontrol aralığı
          <select value={interval} onChange={(e) => setMinutes(Number(e.target.value))}>
            <IntervalOptions value={interval} />
          </select>
        </label>
        <button className="button primary" disabled={inv.demo || busy || !inv.submissions?.length}>
          <Plus size={15} />
          {busy ? 'Kaydediliyor…' : 'İzleme ekle'}
        </button>
        <p className="small muted">
          <span role="status">
            {entities.loading
              ? 'Hedefler yükleniyor…'
              : `${targetOptions.length} / ${targetTotal} varlık yüklendi${targetOptions.length < targetTotal ? ` · ${targetTotal - targetOptions.length} kayıt kaldı` : ''}.`}
          </span>
          {entities.data?.next_cursor && (
            <button
              type="button"
              className="text-button"
              style={{ marginInlineStart: 12 }}
              disabled={entities.loading}
              onClick={() => setTargetCursor(entities.data!.next_cursor)}
            >
              Daha fazla hedef yükle
            </button>
          )}
        </p>
        <p className="small muted">
          {inv.demo
            ? 'Demo ortamında zamanlanmış ağ çalışması başlatılmaz.'
            : 'İzleme bu yerel servis çalışırken sürer. Kayıtlar yeniden başlatmada korunur.'}
        </p>
        {entities.error && <ErrorBox message={entities.error} onRetry={entities.reload} />}
      </form>
      {error && <ErrorBox message={error} />}
      {message && <Success>{message}</Success>}
      {resource.error ? (
        <ErrorBox message={resource.error} onRetry={resource.reload} />
      ) : resource.loading ? (
        <Loading label="İzlemeler yükleniyor" />
      ) : (
        resource.data && (
          <div className="desk-watch-grid">
            <section className="desk-watch-list" aria-label="Kaydedilen izlemeler">
              {resource.data.items.length ? (
                resource.data.items.map((watch) => (
                  <WatchCard
                    key={watch.id}
                    watch={watch}
                    invId={inv.id}
                    demo={!!inv.demo}
                    onChange={resource.reload}
                    onJob={onJob}
                  />
                ))
              ) : (
                <div className="panel">
                  <Empty title="Henüz bir izleme yok" icon={<Radar size={28} />}>
                    Bir hedef ve kontrol aralığı seçerek izleme ekleyin.
                  </Empty>
                </div>
              )}
            </section>
            <aside className="panel desk-alerts">
              <header>
                <Bell size={17} />
                <h3>Değişiklik bildirimleri</h3>
                <Badge>{resource.data.alerts.filter((a) => !a.read).length} yeni</Badge>
              </header>
              {resource.data.alerts.length ? (
                resource.data.alerts.map((alert) => (
                  <article key={alert.id} className={alert.read ? 'read' : ''}>
                    <div>
                      <Badge tone={alert.kind === 'error' || alert.kind === 'failure' ? 'amber' : 'accent'}>
                        {alert.kind === 'error' || alert.kind === 'failure' ? 'Toplama hatası' : 'Değişiklik'}
                      </Badge>
                      <time>{date(alert.created_at, true)}</time>
                    </div>
                    <p>{alert.message}</p>
                    {alert.read ? (
                      <span className="small muted">
                        <Check size={12} /> Okundu
                      </span>
                    ) : (
                      <button className="text-button" onClick={() => read(alert.id)}>
                        <Check size={12} />
                        Okundu olarak işaretle
                      </button>
                    )}
                  </article>
                ))
              ) : (
                <Empty title="Yeni bir bildirim yok">
                  Anlamlı değişiklik veya yeni toplama hatası olduğunda burada görünür.
                </Empty>
              )}
            </aside>
          </div>
        )
      )}
    </>
  );
}
function WatchCard({
  watch,
  invId,
  demo,
  onChange,
  onJob,
}: {
  watch: Watch;
  invId: string;
  demo: boolean;
  onChange: () => void;
  onJob: (job: Job) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  async function update(body: object) {
    setBusy(true);
    setError('');
    try {
      await api.patch(`${casePath(invId)}/watches/${encodeURIComponent(watch.id)}`, body);
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function run() {
    setBusy(true);
    setError('');
    try {
      onJob(await api.post<Job>(`${casePath(invId)}/watches/${encodeURIComponent(watch.id)}/run`));
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="panel desk-watch">
      <header>
        <span className={`desk-watch-icon ${watch.enabled ? 'enabled' : ''}`}>
          <Radar size={20} />
        </span>
        <div>
          <h3>{watch.target}</h3>
          <Badge tone={watch.enabled ? 'accent' : 'neutral'}>
            {watch.enabled ? 'İzleniyor' : 'Duraklatıldı'}
          </Badge>
        </div>
      </header>
      <div className="desk-watch-schedule">
        <label>
          Kontrol aralığı
          <select
            aria-label={`İzleme aralığı: ${watch.target}`}
            disabled={busy || demo}
            value={watch.interval_minutes}
            onChange={(e) => update({ interval_minutes: Number(e.target.value) })}
          >
            <IntervalOptions value={watch.interval_minutes} />
          </select>
        </label>
        <div>
          <span>
            <Clock3 size={12} /> Sonraki kontrol
          </span>
          <strong>{watch.enabled ? date(watch.next_run_at, true) : 'Duraklatıldı'}</strong>
        </div>
      </div>
      {watch.last_error && <p className="callout amber">{watch.last_error}</p>}
      <footer>
        <button
          className="button"
          disabled={busy || demo}
          onClick={() => update({ enabled: !watch.enabled })}
        >
          {watch.enabled ? <Pause size={13} /> : <Play size={13} />}
          {watch.enabled ? 'Duraklat' : 'Etkinleştir'}
        </button>
        <button className="text-button" disabled={busy || demo} onClick={run}>
          <Play size={13} />
          Şimdi çalıştır
        </button>
      </footer>
      {error && <ErrorBox message={error} />}
    </article>
  );
}
