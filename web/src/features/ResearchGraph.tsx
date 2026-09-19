import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Focus, Link2, Pin, PinOff, RefreshCw, X } from 'lucide-react';
import { api, casePath, query } from '../api/client';
import type { Entity, Graph, Relation } from '../api/types';
import { Empty, ErrorBox, kindLabel } from '../components/UI';
import { PIN_LIMIT } from './researchState';
const CANVAS_LIMIT = 60,
  CACHE_LIMIT = 300,
  PAGE_SIZE = 25;
type PageState = { cursor: string | null; hasMore: boolean; count: number; refresh: number };
type Cache = { nodes: Record<string, Entity>; relations: Record<string, Relation>; recent: string[] };
export function ResearchGraph({
  invId,
  entity,
  refresh,
  pins,
  trail,
  onPin,
  onSelect,
  onEvidence,
}: {
  invId: string;
  entity: Entity | null;
  refresh: number;
  pins: Entity[];
  trail: Entity[];
  onPin: (entity: Entity) => void;
  onSelect: (entity: Entity) => void;
  onEvidence: (id: string) => void;
}) {
  const [cache, setCache] = useState<Cache>({ nodes: {}, relations: {}, recent: [] });
  const [pages, setPages] = useState<Record<string, PageState>>({});
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const pageRef = useRef(pages),
    cacheRef = useRef(cache),
    pinRef = useRef(pins),
    request = useRef<AbortController | null>(null),
    scroll = useRef<HTMLDivElement>(null);
  pinRef.current = pins;
  const load = useCallback(
    async (root: Entity, cursor: string | null, version: number) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setBusy(true);
      setError('');
      try {
        const result = await api.get<Graph>(
          `${casePath(invId)}/graph?${query({ root_id: root.id, limit: PAGE_SIZE, cursor })}`,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setCache((current) => {
          const incoming = [root, ...result.nodes];
          const recent = [
            ...current.recent.filter((id) => !incoming.some((node) => node.id === id)),
            ...incoming.map((node) => node.id),
          ].slice(-CACHE_LIMIT);
          const keep = new Set([root.id, ...pinRef.current.map((node) => node.id), ...recent]);
          const nodes = Object.fromEntries(
            [...Object.values(current.nodes), ...pinRef.current, ...incoming]
              .filter((node) => keep.has(node.id))
              .map((node) => [node.id, node]),
          );
          const relations = Object.fromEntries(
            [...Object.values(current.relations), ...result.relations]
              .filter((edge) => nodes[edge.src_id] && nodes[edge.dst_id])
              .slice(-600)
              .map((edge) => [edge.id, edge]),
          );
          const nextCache = { nodes, relations, recent };
          cacheRef.current = nextCache;
          return nextCache;
        });
        const next = {
          ...pageRef.current,
          [root.id]: {
            cursor: result.next_cursor || null,
            hasMore: result.has_more,
            count: (cursor ? pageRef.current[root.id]?.count || 0 : 0) + result.relations.length,
            refresh: version,
          },
        };
        pageRef.current = next;
        setPages(next);
      } catch (problem) {
        if (!controller.signal.aborted)
          setError(problem instanceof Error ? problem.message : 'Bağlantılar yüklenemedi.');
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    },
    [invId],
  );
  useEffect(() => {
    const saved = entity ? pageRef.current[entity.id] : null;
    const present =
      entity &&
      cacheRef.current.nodes[entity.id] &&
      (!saved?.count ||
        Object.values(cacheRef.current.relations).some(
          (edge) => edge.src_id === entity.id || edge.dst_id === entity.id,
        ));
    setError('');
    setSelectedEdge(null);
    if (entity && (!saved || saved.refresh !== refresh || !present)) void load(entity, null, refresh);
    else setBusy(false);
    scroll.current?.scrollTo({ top: 0, left: 0 });
    return () => {
      request.current?.abort();
    };
  }, [entity?.id, refresh, load]);
  if (!entity)
    return (
      <div className="focus-canvas">
        <Empty title="Bir varlığa yakından bakın" icon={<Focus size={30} />}>
          Bir gruptan veya tablodan varlık seçin. Kaydedilmiş komşularını ekleyin, önemli düğümleri
          sabitleyin.
        </Empty>
      </div>
    );
  const neighborIds = new Set(
    Object.values(cache.relations).flatMap((edge) =>
      edge.src_id === entity.id ? [edge.dst_id] : edge.dst_id === entity.id ? [edge.src_id] : [],
    ),
  );
  const recentNodes = cache.recent
    .slice()
    .reverse()
    .map((id) => cache.nodes[id])
    .filter(Boolean);
  const roots = [entity, ...pins, ...recentNodes.filter((node) => neighborIds.has(node.id)), ...recentNodes];
  const unique = new Map<string, Entity>();
  for (const node of roots) if (!unique.has(node.id)) unique.set(node.id, node);
  const nodes = [...unique.values()].slice(0, CANVAS_LIMIT);
  const ids = new Set(nodes.map((node) => node.id));
  const edges = Object.values(cache.relations).filter((edge) => ids.has(edge.src_id) && ids.has(edge.dst_id));
  const columns = 3,
    width = 900,
    height = Math.max(330, Math.ceil(nodes.length / columns) * 105 + 25);
  const points = new Map(
    nodes.map((node, index) => [
      node.id,
      { x: 150 + (index % columns) * 300, y: 57 + Math.floor(index / columns) * 105 },
    ]),
  );
  const activePage = pages[entity.id],
    selected = selectedEdge ? cache.relations[selectedEdge] : null;
  const isPinned = pins.some((node) => node.id === entity.id);
  const openEdge = (edge: Relation) => {
    setSelectedEdge(edge.id);
    if (edge.evidence_ids[0]) onEvidence(edge.evidence_ids[0]);
  };
  return (
    <div className="research-graph">
      <nav className="research-trail" aria-label="Grafik araştırma izi">
        <span>Araştırma izi</span>
        {trail.map((node, index) => (
          <span key={node.id}>
            {index > 0 && <ArrowRight size={11} />}
            <button
              aria-current={node.id === entity.id ? 'step' : undefined}
              onClick={() => onSelect(node)}
              title={node.canonical_value}
            >
              {node.canonical_value}
            </button>
          </span>
        ))}
      </nav>
      <div className="research-graph-actions">
        <div>
          <strong className="mono">{entity.canonical_value}</strong>
          <span>
            {nodes.length} düğüm görünümde · {edges.length} bağlantı
          </span>
        </div>
        <button
          className="button"
          aria-label={isPinned ? 'Seçili düğümün sabitlemesini kaldır' : 'Seçili düğümü sabitle'}
          disabled={!isPinned && pins.length >= PIN_LIMIT}
          onClick={() => onPin(entity)}
        >
          {isPinned ? <PinOff size={14} /> : <Pin size={14} />}
          {isPinned ? 'Sabitlemeyi kaldır' : 'Sabitle'}
        </button>
        <button
          className="icon-button"
          aria-label="Seçili düğümün bağlantılarını yenile"
          disabled={busy}
          onClick={() => void load(entity, null, refresh)}
        >
          <RefreshCw size={15} />
        </button>
      </div>
      {!!pins.length && (
        <div className="research-pins" aria-label="Sabitlenmiş grafik varlıkları">
          {pins.map((node) => (
            <span key={node.id}>
              <Pin size={12} />
              <button title={node.canonical_value} onClick={() => onSelect(node)}>
                {node.canonical_value}
              </button>
              <button aria-label={`${node.canonical_value} sabitlemesini kaldır`} onClick={() => onPin(node)}>
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      {error && (
        <ErrorBox message={error} onRetry={() => void load(entity, activePage?.cursor || null, refresh)} />
      )}
      <div
        ref={scroll}
        className="research-graph-scroll"
        role="region"
        aria-label="Varlık bağlantı grafiği"
        tabIndex={0}
      >
        <svg
          className="research-graph-svg"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          aria-label="Kaydedilmiş ilişkiler"
        >
          {edges.map((edge) => {
            const start = points.get(edge.src_id)!,
              end = points.get(edge.dst_id)!;
            const label = `${cache.nodes[edge.src_id]?.canonical_value || entity.canonical_value} → ${cache.nodes[edge.dst_id]?.canonical_value || ''}: ${kindLabel(edge.kind)}`;
            return (
              <g
                key={edge.id}
                className={`research-graph-edge ${selectedEdge === edge.id ? 'active' : ''}`}
                role="button"
                tabIndex={edge.evidence_ids.length ? 0 : -1}
                aria-label={`${label} kanıtları`}
                onClick={() => openEdge(edge)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    openEdge(edge);
                  }
                }}
              >
                <path
                  className="research-edge-hit"
                  d={`M${start.x} ${start.y} C${start.x + 120} ${start.y + 40},${end.x - 120} ${end.y - 40},${end.x} ${end.y}`}
                />
                <path
                  className="research-edge-line"
                  d={`M${start.x} ${start.y} C${start.x + 120} ${start.y + 40},${end.x - 120} ${end.y - 40},${end.x} ${end.y}`}
                />
                <title>
                  {label} · {edge.evidence_ids.length} kaynak
                </title>
              </g>
            );
          })}
          {nodes.map((node) => {
            const point = points.get(node.id)!;
            const pinned = pins.some((item) => item.id === node.id);
            return (
              <g
                key={node.id}
                data-node-id={node.id}
                className={`graph-node ${pinned ? 'pinned' : ''}`}
                role="button"
                tabIndex={0}
                aria-label={`${node.canonical_value} düğümü`}
                onClick={() => onSelect(node)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelect(node);
                  }
                }}
              >
                <rect
                  x={point.x - 120}
                  y={point.y - 32}
                  width="240"
                  height="64"
                  rx="10"
                  fill={node.id === entity.id ? 'var(--accent-soft)' : 'var(--surface)'}
                  stroke={node.id === entity.id || pinned ? 'var(--accent)' : 'var(--line)'}
                />
                <text x={point.x - 105} y={point.y - 9} className="graph-kind">
                  {node.id === entity.id ? 'SEÇİLİ VARLIK' : kindLabel(node.kind).toLocaleUpperCase('tr')}
                  {pinned ? ' · SABİT' : ''}
                </text>
                <text x={point.x - 105} y={point.y + 14} className="graph-value">
                  {node.canonical_value.length > 29
                    ? node.canonical_value.slice(0, 27) + '…'
                    : node.canonical_value}
                </text>
                <title>{node.canonical_value}</title>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="research-graph-page">
        <span role="status">
          {busy ? 'Bağlantılar yükleniyor…' : `${activePage?.count || 0} doğrudan bağlantı yüklendi`}
        </span>
        <button
          className="button"
          aria-label="Sonraki bağlantıları ekle"
          disabled={busy || !activePage?.cursor}
          onClick={() => void load(entity, activePage!.cursor, refresh)}
        >
          Sonraki bağlantıları ekle
          <ArrowRight size={14} />
        </button>
      </div>
      <p className="research-graph-note">
        Grafik en fazla 60 düğüm gösterir; yeni komşular eklendikçe sabitlenmemiş eski düğümler görünümden
        çıkar. Daha fazla kayıt için sayfalama sürer. Bu görünüm tüm araştırma grafiği değildir.
      </p>
      {!busy && !edges.length && (
        <p className="research-graph-note">
          Bu görünümde kaynaklı bir bağlantı bulunmuyor. Sabitlenen düğümler arasında ilişki varsayılmaz.
        </p>
      )}
      {selected && (
        <section className="research-edge-detail" aria-label="Seçili bağlantının kaynakları">
          <strong>{kindLabel(selected.kind)}</strong>
          <span>{selected.evidence_ids.length} kanıt kaydı</span>
          {selected.evidence_ids.map((id, index) => (
            <button className="button" key={id} onClick={() => onEvidence(id)}>
              Kaynak {index + 1}
              <Link2 size={12} />
            </button>
          ))}
        </section>
      )}
      {!!edges.length && (
        <details className="research-edge-list" open={edges.length <= 3}>
          <summary>Görünümdeki bağlantılar ve kaynakları ({edges.length})</summary>
          <div>
            {edges.map((edge) => (
              <button
                key={edge.id}
                data-edge-id={edge.id}
                className="edge-pill"
                aria-label="Bağlantının kanıtını aç"
                disabled={!edge.evidence_ids.length}
                onClick={() => openEdge(edge)}
              >
                <Link2 size={12} />
                <span>
                  {cache.nodes[edge.src_id]?.canonical_value || entity.canonical_value} →{' '}
                  {cache.nodes[edge.dst_id]?.canonical_value}
                  <small>
                    {kindLabel(edge.kind)} · {edge.evidence_ids.length} kaynak
                  </small>
                </span>
              </button>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
