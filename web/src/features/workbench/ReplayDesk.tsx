import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeft,
  ArrowRight,
  Download,
  Eye,
  History,
  LockKeyhole,
  Maximize2,
  Pause,
  Play,
  X,
} from 'lucide-react';
import type { WorkbenchProps } from '../../api/workbench';
import {
  downloadReplay,
  previewReplay,
  type Replay,
  type ReplayEdge,
  type ReplayEvent,
  type ReplayNode,
} from '../../api/replay';
import { Badge, date, Empty, ErrorBox, Loading } from '../../components/UI';
import { DeskHeading, errorMessage } from './Common';
import '../../styles/replay.css';

const statusLabels: Record<string, string> = {
  recorded: 'Kaydedildi',
  queued: 'Sırada',
  running: 'Çalışıyor',
  completed: 'Tamamlandı',
  partial: 'Kısmi',
  failed: 'Başarısız',
  cancelled: 'İptal edildi',
  unreviewed: 'İncelenmedi',
  confirmed_phishing: 'Oltalama doğrulandı',
  benign: 'Zararsız',
  needs_review: 'İnceleme gerekli',
};

type GraphState = { nodes: ReplayNode[]; edges: ReplayEdge[] };

function graphAt(events: ReplayEvent[], index: number): GraphState {
  const nodes = new Map<string, ReplayNode>();
  const edges = new Map<string, ReplayEdge>();
  events.slice(0, index + 1).forEach((event) => {
    event.graph_additions.nodes.forEach((node) => nodes.set(node.id, node));
    event.graph_additions.edges.forEach((edge) => edges.set(edge.id, edge));
  });
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

export function ReplayDesk({ inv, onEvidence }: WorkbenchProps) {
  const [redact, setRedact] = useState(true);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [focus, setFocus] = useState(false);
  const requestVersion = useRef(0);

  async function load() {
    const request = ++requestVersion.current;
    setBusy('preview');
    setError('');
    setPlaying(false);
    try {
      const value = await previewReplay(inv.id, redact);
      if (request !== requestVersion.current) return;
      setReplay(value);
      setIndex(0);
    } catch (reason) {
      if (request !== requestVersion.current) return;
      setReplay(null);
      setError(errorMessage(reason));
    } finally {
      if (request === requestVersion.current) setBusy('');
    }
  }

  useEffect(() => {
    void load();
    return () => {
      requestVersion.current += 1;
    };
    // A loaded preview stays frozen while background case polling changes WorkbenchProps.refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inv.id, redact]);

  useEffect(() => {
    if (!playing || !replay || replay.events.length < 2) return;
    const timer = window.setInterval(() => {
      setIndex((value) => {
        if (value >= replay.events.length - 1) {
          setPlaying(false);
          return value;
        }
        return value + 1;
      });
    }, 1500 / speed);
    return () => window.clearInterval(timer);
  }, [playing, replay, speed]);

  function seek(value: number) {
    if (!replay?.events.length) return;
    setPlaying(false);
    setIndex(Math.max(0, Math.min(replay.events.length - 1, value)));
  }

  async function download() {
    if (!replay?.preview_id) return;
    setBusy('export');
    setError('');
    try {
      const blob = await downloadReplay(inv.id, replay.preview_id, replay.redacted);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'belgu-kayitli-inceleme.html';
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy('');
    }
  }

  const events = replay?.events || [];
  const current = events[index];
  const graph = useMemo(() => graphAt(events, index), [events, index]);
  return (
    <>
      <DeskHeading eyebrow="KAYDEDİLMİŞ İNCELEME AKIŞI" title="İncelemenin nasıl geliştiğini oynatın">
        Gerçekte kaydedilmiş bildirimleri, gözlemleri, kanıtlı bağlantıları, çalışma sonuçlarını ve kararları
        bilinen zaman sırasıyla izleyin.
      </DeskHeading>
      <section className="replay-workspace" aria-label="Kayıtlı inceleme oynatması">
        <div className="panel replay-toolbar">
          <span className="replay-recorded-label">
            <History size={14} /> Kayıtlardan yeniden oluşturuldu
          </span>
          <label className="replay-mask">
            <span>
              <LockKeyhole size={13} /> Kimlikleri maskele
            </span>
            <input
              type="checkbox"
              checked={redact}
              disabled={!!busy}
              onChange={(event) => setRedact(event.target.checked)}
            />
          </label>
          <button className="button" disabled={busy === 'preview'} onClick={() => void load()}>
            <Eye size={14} /> Yeniden oluştur
          </button>
        </div>
        {error && <ErrorBox message={error} onRetry={() => void load()} />}
        {busy === 'preview' ? (
          <Loading label="Kayıtlı inceleme hazırlanıyor" />
        ) : replay ? (
          <>
            <div className="replay-stage-grid">
              <ReplayGraph graph={graph} />
              <ReplayEventCard
                replay={replay}
                event={current}
                index={index}
                onEvidence={onEvidence}
                invId={inv.id}
              />
            </div>
            <ReplayControls
              events={events}
              index={index}
              playing={playing}
              speed={speed}
              onSeek={seek}
              onPlaying={setPlaying}
              onSpeed={setSpeed}
            />
            <ReplayCoverage replay={replay} />
            <div className="replay-actions">
              <span>Önizlenen kayıt sabitlenir; HTML aynı kayıt anlık görüntüsünden üretilir.</span>
              <div>
                {replay.redacted && !!events.length && (
                  <button className="button" onClick={() => setFocus(true)}>
                    <Maximize2 size={14} /> Maskeli odak görünümünü aç
                  </button>
                )}
                <button
                  className="button primary"
                  aria-label="Çevrimdışı HTML indir"
                  disabled={!replay.preview_id || busy === 'export'}
                  onClick={() => void download()}
                >
                  <Download size={14} /> {busy === 'export' ? 'Hazırlanıyor…' : 'Çevrimdışı HTML indir'}
                </button>
              </div>
            </div>
          </>
        ) : null}
      </section>
      {focus && replay?.redacted && (
        <ReplayFocus replay={replay} initialIndex={index} onClose={() => setFocus(false)} />
      )}
    </>
  );
}

function ReplayGraph({ graph }: { graph: GraphState }) {
  const width = 620;
  const height = 390;
  const dense = graph.nodes.length > 16;
  const radius = Math.min(width, height) * 0.36;
  const columns = 10;
  const rows = Math.max(1, Math.ceil(graph.nodes.length / columns));
  const positions = new Map(
    graph.nodes.map((node, index) => {
      if (dense) {
        const column = index % columns;
        const row = Math.floor(index / columns);
        return [
          node.id,
          {
            x: 36 + (column * (width - 72)) / (columns - 1),
            y: 32 + (row * (height - 64)) / Math.max(1, rows - 1),
          },
        ];
      }
      const angle = (Math.PI * 2 * index) / Math.max(1, graph.nodes.length) - Math.PI / 2;
      return [node.id, { x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius }];
    }),
  );
  return (
    <section className="panel replay-graph" aria-label="Büyüyen inceleme grafiği">
      <header>
        <div>
          <span className="eyebrow">KRONOLOJİK GRAFİK</span>
          <h3>Bu adıma kadar bilinenler</h3>
        </div>
        <Badge>{graph.nodes.length} düğüm</Badge>
      </header>
      {!graph.nodes.length ? (
        <Empty title="Bu adımda grafik kaydı yok">Sonraki kayıtlarla eklenen düğümler burada görünür.</Empty>
      ) : (
        <svg
          className={dense ? 'dense' : undefined}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="İnceleme grafiğinin kayıtlı durumu"
        >
          {graph.edges.map((edge) => {
            const source = positions.get(edge.src_id);
            const target = positions.get(edge.dst_id);
            return source && target ? (
              <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} />
            ) : null;
          })}
          {graph.nodes.map((node) => {
            const point = positions.get(node.id)!;
            const visibleLabel = dense && node.label.length > 11 ? `${node.label.slice(0, 10)}…` : node.label;
            return (
              <g key={node.id}>
                <title>{node.label}</title>
                <circle cx={point.x} cy={point.y} r={dense ? 7 : 16} />
                <text x={point.x} y={point.y + (dense ? 17 : 31)} textAnchor="middle">
                  {visibleLabel}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </section>
  );
}

function ReplayEventCard({
  replay,
  event,
  index,
  onEvidence,
  invId,
}: {
  replay: Replay;
  event?: ReplayEvent;
  index: number;
  onEvidence: WorkbenchProps['onEvidence'];
  invId: string;
}) {
  return (
    <section className="panel replay-event" aria-live="polite">
      {!event ? (
        <Empty title="Oynatılacak kayıt bulunmuyor">
          Bu incelemede henüz bildirim, gözlem, çalışma, analiz veya karar kaydı yok.
        </Empty>
      ) : (
        <>
          <header>
            <span className="eyebrow">KAYITLI ADIM {String(index + 1).padStart(2, '0')}</span>
            <Badge tone={event.status === 'failed' ? 'amber' : 'neutral'}>
              {statusLabels[event.status] || event.status}
            </Badge>
          </header>
          <h2>{event.title}</h2>
          <p>{event.detail}</p>
          <dl>
            <div>
              <dt>Bilinen zaman</dt>
              <dd>{date(event.known_at, true)}</dd>
            </div>
            <div>
              <dt>Gözlem zamanı</dt>
              <dd>{event.observed_at ? date(event.observed_at, true) : 'Kaydedilmedi'}</dd>
            </div>
            <div>
              <dt>Kanıt kapsamı</dt>
              <dd>
                {event.evidence_refs.length
                  ? `${event.evidence_refs.length} bağlı kayıt`
                  : 'Kayıtlı kanıt bağlantısı yok'}
              </dd>
            </div>
          </dl>
          {!replay.redacted && !!event.evidence_refs.length && (
            <div className="replay-evidence-links">
              {event.evidence_refs.map((evidence) => (
                <button
                  key={evidence}
                  className="text-button"
                  aria-label={`Kanıt ${evidence} kaydını aç`}
                  onClick={() => onEvidence(evidence, invId)}
                >
                  Kanıtı aç <ArrowRight size={13} />
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function ReplayControls({
  events,
  index,
  playing,
  speed,
  onSeek,
  onPlaying,
  onSpeed,
}: {
  events: ReplayEvent[];
  index: number;
  playing: boolean;
  speed: number;
  onSeek: (value: number) => void;
  onPlaying: (value: boolean) => void;
  onSpeed: (value: number) => void;
}) {
  return (
    <section className="panel replay-controls" aria-label="Oynatma denetimleri">
      <div>
        <button
          className="icon-button"
          aria-label="Önceki kayıt"
          disabled={!index}
          onClick={() => onSeek(index - 1)}
        >
          <ArrowLeft size={16} />
        </button>
        <button
          className="button primary replay-play"
          aria-label={playing ? 'Kaydı duraklat' : 'Kaydı oynat'}
          disabled={events.length < 2}
          onClick={() => onPlaying(!playing)}
        >
          {playing ? <Pause size={15} /> : <Play size={15} />}
          {playing ? 'Duraklat' : 'Oynat'}
        </button>
        <button
          className="icon-button"
          aria-label="Sonraki kayıt"
          disabled={!events.length || index >= events.length - 1}
          onClick={() => onSeek(index + 1)}
        >
          <ArrowRight size={16} />
        </button>
      </div>
      <label className="replay-seek">
        <span>
          Kayıtta ara <strong>{events.length ? `${index + 1} / ${events.length}` : '0 / 0'}</strong>
        </span>
        <input
          type="range"
          aria-label="Kayıtta ara"
          min="0"
          max={Math.max(0, events.length - 1)}
          value={index}
          disabled={!events.length}
          onChange={(event) => onSeek(Number(event.target.value))}
        />
      </label>
      <label className="replay-speed">
        <span>Oynatma hızı</span>
        <select
          aria-label="Oynatma hızı"
          value={speed}
          onChange={(event) => onSpeed(Number(event.target.value))}
        >
          <option value="0.5">0,5×</option>
          <option value="1">1×</option>
          <option value="2">2×</option>
        </select>
      </label>
    </section>
  );
}

function ReplayCoverage({ replay }: { replay: Replay }) {
  const coverage = replay.coverage;
  return (
    <section className="replay-coverage" aria-label="Oynatma kapsamı">
      <div>
        <span>Gösterilen kayıt</span>
        <strong>
          {coverage.included_events} / {coverage.available_events}
        </strong>
        <small>Üst sınır {coverage.event_limit}</small>
      </div>
      <div>
        <span>Grafik düğümü</span>
        <strong>
          {coverage.included_graph_nodes} / {coverage.available_graph_nodes}
        </strong>
        <small>Üst sınır {coverage.graph_node_limit}</small>
      </div>
      <div>
        <span>Gösterilen grafik kenarı</span>
        <strong>{coverage.rendered_graph_edges}</strong>
        <small>
          {coverage.included_relation_events} ilişki olayı · {coverage.omitted_graph_edges} kenar grafik
          dışında · {coverage.unsupported_relations} desteksiz · {coverage.omitted_evidence_lifecycle_events}{' '}
          tam kanıtıyla sığmayan sonuç
        </small>
      </div>
      <ul>
        {replay.limitations.map((limitation, item) => (
          <li key={item}>{limitation}</li>
        ))}
      </ul>
    </section>
  );
}

function ReplayFocus({
  replay,
  initialIndex,
  onClose,
}: {
  replay: Replay;
  initialIndex: number;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const [index, setIndex] = useState(initialIndex);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.classList.add('belgu-replay-focus');
    dialog.current?.showModal();
    close.current?.focus();
    return () => {
      document.body.classList.remove('belgu-replay-focus');
      dialog.current?.close();
      prior?.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    if (!playing || replay.events.length < 2) return;
    const timer = window.setInterval(() => {
      setIndex((value) => {
        if (value >= replay.events.length - 1) {
          setPlaying(false);
          return value;
        }
        return value + 1;
      });
    }, 1500 / speed);
    return () => window.clearInterval(timer);
  }, [playing, replay.events.length, speed]);
  const current = replay.events[index];
  return createPortal(
    <dialog
      ref={dialog}
      className="replay-focus"
      aria-label="Maskeli kayıtlı inceleme"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header>
        <span className="replay-focus-brand">BELGÜ / KAYITLI İNCELEME</span>
        <div>
          <Badge tone="accent">
            <LockKeyhole size={12} /> Maskeli kayıt
          </Badge>
          <button ref={close} className="icon-button" aria-label="Odak görünümünü kapat" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
      </header>
      <main>
        <ReplayGraph graph={graphAt(replay.events, index)} />
        <ReplayEventCard replay={replay} event={current} index={index} onEvidence={() => {}} invId="" />
      </main>
      <ReplayControls
        events={replay.events}
        index={index}
        playing={playing}
        speed={speed}
        onSeek={(value) => {
          setPlaying(false);
          setIndex(value);
        }}
        onPlaying={setPlaying}
        onSpeed={setSpeed}
      />
    </dialog>,
    document.body,
  );
}
