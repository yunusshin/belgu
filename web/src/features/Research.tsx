import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Code2,
  Focus,
  Globe2,
  Layers3,
  Link2,
  Network,
  Pin,
  Search,
  Server,
  ShieldCheck,
  X,
} from 'lucide-react';
import { casePath, query, useResource } from '../api/client';
import type { Collection, Entity, Group, Investigation } from '../api/types';
import { Empty, ErrorBox, kindLabel, Loading, Pagination, date } from '../components/UI';
import { ResearchGraph } from './ResearchGraph';
import {
  defaultFilters,
  loadResearchState,
  PIN_LIMIT,
  saveResearchState,
  type ResearchFilters,
} from './researchState';
import '../styles/research-explorer.css';
export const groupTitle = (g: Group) =>
  g.label.length > 48
    ? `${g.criterion === 'js_sha256' ? 'İçerik grubu' : g.criterion === 'cert_sha256' ? 'Sertifika grubu' : 'IP grubu'} · ${g.key.slice(0, 6)}`
    : g.label;
export const criterionLabel = (v: string) =>
  ({
    js_sha256: 'Aynı JavaScript içerik özeti',
    cert_sha256: 'Aynı TLS sertifika özeti',
    observed_ip: 'Aynı gözlenen IP adresi',
  })[v] || v;
type ResearchProps = {
  inv: Investigation;
  refresh: number;
  group: Group | null;
  setGroup: (g: Group | null) => void;
  entity: Entity | null;
  setEntity: (e: Entity | null) => void;
  onEvidence: (id: string) => void;
  filterRequest?: { id: number; filters: Partial<ResearchFilters> } | null;
};
type ExplorerEntity = Entity & {
  has_capture?: boolean;
  shared_signals?: string[];
  priority_score?: number | null;
};
export function Research(props: ResearchProps) {
  return <ResearchContent key={props.inv.id} {...props} />;
}
function ResearchContent({
  inv,
  refresh,
  group,
  setGroup,
  entity,
  setEntity,
  onEvidence,
  filterRequest,
}: ResearchProps) {
  const [state, setState] = useState(() => loadResearchState(inv.id));
  const [search, setSearch] = useState(state.filters.q),
    [viewName, setViewName] = useState(''),
    [activeView, setActiveView] = useState(''),
    [notice, setNotice] = useState('');
  const [pagination, setPagination] = useState<{ key: string; page: number; cursors: (string | null)[] }>({
    key: '',
    page: 0,
    cursors: [null],
  });
  const [groupPage, setGroupPage] = useState(0),
    [groupCursors, setGroupCursors] = useState<(string | null)[]>([null]);
  const appliedRequest = useRef<number | null>(null);
  useEffect(() => {
    if (state.focus && !entity) setEntity(state.focus);
    if (state.group && !group) setGroup(state.group);
  }, []);
  useEffect(() => {
    if (!filterRequest || appliedRequest.current === filterRequest.id) return;
    appliedRequest.current = filterRequest.id;
    setState((current) => ({
      ...current,
      filters: { ...defaultFilters, ...filterRequest.filters },
      group: null,
      focus: null,
      selected: [],
      mode: 'groups',
    }));
    setSearch((filterRequest.filters.q || '').trim());
    setGroup(null);
    setEntity(null);
    setActiveView('');
    setNotice('Araştırma asistanının önerdiği filtre uygulandı.');
  }, [filterRequest]);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(state.filters.q.trim()), 300);
    return () => clearTimeout(timer);
  }, [state.filters.q]);
  useEffect(() => {
    if (!saveResearchState(inv.id, state))
      setNotice('Tarayıcı kaydı kullanılamıyor. Seçimler bu açık görünümde korunur.');
  }, [inv.id, state]);
  const filterQuery = query({
    kind: state.filters.kind,
    group_key: group?.key,
    q: search,
    has_capture: state.filters.hasCapture ? 'true' : undefined,
    shared: state.filters.shared,
    recent_hours: state.filters.recent ? 24 : undefined,
    sort: state.filters.sort,
  });
  const page = pagination.key === filterQuery ? pagination.page : 0;
  const cursors = pagination.key === filterQuery ? pagination.cursors : [null];
  const groups = useResource<Collection<Group>>(
    `${casePath(inv.id)}/groups?${query({ by: state.criterion, limit: 8, cursor: groupCursors[groupPage] })}`,
    refresh,
  );
  const entities = useResource<Collection<ExplorerEntity>>(
    `${casePath(inv.id)}/entities?${filterQuery}&${query({ limit: 25, cursor: cursors[page] })}`,
    refresh,
  );
  const visible = entities.data?.items || [];
  function filter(values: Partial<ResearchFilters>) {
    setState((current) => ({ ...current, filters: { ...current.filters, ...values } }));
    setActiveView('');
  }
  function chooseGroup(value: Group | null) {
    setGroup(value);
    setEntity(null);
    setState((current) => ({ ...current, group: value, focus: null }));
  }
  function chooseEntity(value: Entity) {
    setEntity(value);
    setState((current) => ({
      ...current,
      mode: 'focus',
      focus: value,
      trail: [...current.trail.filter((item) => item.id !== value.id), value].slice(-20),
    }));
  }
  function toggleSelection(value: Entity) {
    setState((current) => ({
      ...current,
      selected: current.selected.some((item) => item.id === value.id)
        ? current.selected.filter((item) => item.id !== value.id)
        : [...current.selected, value].slice(0, PIN_LIMIT),
    }));
  }
  function togglePin(value: Entity) {
    setState((current) => ({
      ...current,
      pins: current.pins.some((item) => item.id === value.id)
        ? current.pins.filter((item) => item.id !== value.id)
        : [...current.pins, value].slice(0, PIN_LIMIT),
    }));
  }
  function pinSelection() {
    const nextPins = [...new Map([...state.pins, ...state.selected].map((item) => [item.id, item])).values()];
    if (nextPins.length > PIN_LIMIT) {
      setNotice('Grafikte en fazla 20 varlık sabitlenebilir. Önce bazı sabitlemeleri kaldırın.');
      return;
    }
    setState((current) => ({ ...current, pins: nextPins, mode: 'focus' }));
    if (!entity && state.selected[0]) chooseEntity(state.selected[0]);
  }
  function saveView() {
    const name = viewName.trim();
    if (!name) return;
    if (state.views.length >= 12 && !state.views.some((view) => view.name === name)) {
      setNotice('En fazla 12 görünüm kaydedilebilir. Önce bir görünümü silin.');
      return;
    }
    setState((current) => ({
      ...current,
      views: [
        ...current.views.filter((view) => view.name !== name),
        { name, filters: { ...current.filters }, group },
      ],
    }));
    setActiveView(name);
    setViewName('');
    setNotice('Görünüm bu araştırma için kaydedildi.');
  }
  const selectedIds = new Set(state.selected.map((item) => item.id));
  return (
    <div className="research-main research-explorer">
      <section className="panel research-query" aria-label="Araştırma araması ve görünümleri">
        <div className="research-search">
          <Search size={17} />
          <input
            aria-label="Araştırmadaki tüm varlıklarda ara"
            placeholder="Tüm araştırmada alan adı, URL veya IP ara…"
            maxLength={300}
            value={state.filters.q}
            onChange={(event) => filter({ q: event.target.value })}
          />
          <span>{search !== state.filters.q.trim() ? 'Aranıyor…' : 'Tüm kayıtlar'}</span>
        </div>
        <div className="research-filters">
          <label className="research-check">
            <input
              type="checkbox"
              checked={state.filters.hasCapture}
              onChange={(event) => filter({ hasCapture: event.target.checked })}
            />
            Görsel kanıtı olanlar
          </label>
          <label className="research-check">
            <input
              type="checkbox"
              checked={state.filters.recent}
              onChange={(event) => filter({ recent: event.target.checked })}
            />
            Son 24 saatte gözlenenler
          </label>
          <label>
            Ortak bulgu
            <select
              aria-label="Ortak bulgu"
              value={state.filters.shared}
              onChange={(event) => filter({ shared: event.target.value })}
            >
              <option value="">Tüm bulgular</option>
              <option value="javascript">Ortak JavaScript</option>
              <option value="certificate">Ortak sertifika</option>
            </select>
          </label>
          <label>
            Sıralama
            <select
              aria-label="Varlıkları sırala"
              value={state.filters.sort}
              onChange={(event) => filter({ sort: event.target.value })}
            >
              <option value="name">Ada göre</option>
              <option value="latest">Son gözleme göre</option>
              <option value="priority">İnceleme önceliğine göre</option>
            </select>
          </label>
        </div>
        <div className="research-view-controls">
          <select
            aria-label="Kayıtlı görünüm"
            value={activeView}
            onChange={(event) => {
              const view = state.views.find((item) => item.name === event.target.value);
              setActiveView(event.target.value);
              if (view) {
                setState((current) => ({ ...current, filters: { ...view.filters }, group: view.group }));
                setGroup(view.group);
              }
            }}
          >
            <option value="">Kayıtlı görünüm seçin</option>
            {state.views.map((view) => (
              <option key={view.name} value={view.name}>
                {view.name}
              </option>
            ))}
          </select>
          <input
            aria-label="Görünüm adı"
            placeholder="Bu görünüme ad verin"
            value={viewName}
            maxLength={60}
            onChange={(event) => setViewName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') saveView();
            }}
          />
          <button className="button" onClick={saveView} disabled={!viewName.trim()}>
            Görünümü kaydet
          </button>
          {activeView && (
            <button
              className="text-button"
              onClick={() => {
                setState((current) => ({
                  ...current,
                  views: current.views.filter((view) => view.name !== activeView),
                }));
                setActiveView('');
              }}
            >
              Görünümü sil
            </button>
          )}
        </div>
        <div className="research-filter-chips" aria-label="Etkin filtreler">
          {state.filters.q && (
            <button onClick={() => filter({ q: '' })}>
              Arama: {state.filters.q}
              <X size={12} />
            </button>
          )}
          {state.filters.hasCapture && (
            <button onClick={() => filter({ hasCapture: false })}>
              Görsel kanıt
              <X size={12} />
            </button>
          )}
          {state.filters.recent && (
            <button onClick={() => filter({ recent: false })}>
              Son 24 saat
              <X size={12} />
            </button>
          )}
          {state.filters.shared && (
            <button onClick={() => filter({ shared: '' })}>
              {state.filters.shared === 'javascript' ? 'Ortak JavaScript' : 'Ortak sertifika'}
              <X size={12} />
            </button>
          )}
          {group && (
            <button onClick={() => chooseGroup(null)}>
              {groupTitle(group)}
              <X size={12} />
            </button>
          )}
          <button
            className="research-clear"
            onClick={() => {
              filter({ ...defaultFilters });
              chooseGroup(null);
            }}
          >
            Filtreleri temizle
          </button>
        </div>
        {notice && (
          <p className="small muted" role="status">
            {notice}
          </p>
        )}
      </section>
      <section className="panel map-panel">
        <div className="map-toolbar">
          <div className="segmented">
            <button
              aria-pressed={state.mode === 'groups'}
              onClick={() => setState((current) => ({ ...current, mode: 'groups' }))}
            >
              <Layers3 size={15} />
              Kümeler
            </button>
            <button
              aria-pressed={state.mode === 'focus'}
              onClick={() => setState((current) => ({ ...current, mode: 'focus' }))}
            >
              <Focus size={15} />
              Yakın görünüm
            </button>
          </div>
          {state.mode === 'groups' ? (
            <select
              className="quiet-select"
              aria-label="Gruplama ölçütü"
              value={state.criterion}
              onChange={(event) => {
                setState((current) => ({ ...current, criterion: event.target.value }));
                chooseGroup(null);
                setGroupPage(0);
                setGroupCursors([null]);
              }}
            >
              <option value="js_sha256">JavaScript özeti</option>
              <option value="observed_ip">Gözlenen IP</option>
              <option value="cert_sha256">TLS sertifikası</option>
            </select>
          ) : (
            <span className="small muted">Kaynaklı bağlantıları adım adım izleyin</span>
          )}
        </div>
        <div hidden={state.mode !== 'groups'}>
          <div className={`cluster-canvas ${(groups.data?.items.length || 0) > 4 ? 'many' : ''}`}>
            {groups.error ? (
              <ErrorBox message={groups.error} onRetry={groups.reload} />
            ) : groups.loading ? (
              <Loading />
            ) : !groups.data?.items.length ? (
              <Empty title="Henüz eşleşme grubu yok" icon={<Network size={30} />}>
                Keşiften sonra ortak gözlemler burada görünür. Farklı bir gruplama ölçütü seçebilirsiniz.
              </Empty>
            ) : (
              groups.data.items.map((item, index) => (
                <button
                  className={`cluster cluster-${index % 4}`}
                  key={item.key}
                  aria-label={`${item.label}, ${item.entity_count} varlık`}
                  aria-pressed={group?.key === item.key}
                  onClick={() => chooseGroup(group?.key === item.key ? null : item)}
                >
                  <div className="orbit">
                    <svg viewBox="0 0 154 154" aria-hidden="true">
                      <circle className="orbit-line" cx="77" cy="77" r="66" />
                      {Array.from({ length: 24 }, (_, n) => (
                        <circle
                          key={n}
                          cx={77 + Math.cos((n / 24) * Math.PI * 2) * 66}
                          cy={77 + Math.sin((n / 24) * Math.PI * 2) * 66}
                          r={1.6}
                        />
                      ))}
                    </svg>
                    <span className="cluster-core">
                      <strong>{item.entity_count}</strong>
                      <small>varlık</small>
                    </span>
                  </div>
                  <strong className="cluster-name">{groupTitle(item)}</strong>
                  <span className="cluster-criterion">
                    {state.criterion === 'js_sha256' ? (
                      <Code2 size={12} />
                    ) : state.criterion === 'observed_ip' ? (
                      <Server size={12} />
                    ) : (
                      <ShieldCheck size={12} />
                    )}
                    <span className="mono">
                      {item.key.length > 28 ? `${item.key.slice(0, 14)}…${item.key.slice(-8)}` : item.key}
                    </span>
                  </span>
                  <span className="cluster-evidence">
                    {item.evidence_ids.length} kaynak kaydı
                    <ArrowRight size={12} />
                  </span>
                </button>
              ))
            )}
          </div>
          {(groupPage > 0 || groups.data?.next_cursor) && (
            <div className="graph-pager">
              <button
                className="text-button"
                disabled={!groupPage}
                onClick={() => setGroupPage((value) => value - 1)}
              >
                <ChevronLeft size={14} />
                Önceki gruplar
              </button>
              <span>Grup sayfası {groupPage + 1}</span>
              <button
                className="text-button"
                disabled={!groups.data?.next_cursor}
                onClick={() => {
                  setGroupCursors((current) => [
                    ...current.slice(0, groupPage + 1),
                    groups.data!.next_cursor,
                  ]);
                  setGroupPage((value) => value + 1);
                }}
              >
                Sonraki gruplar
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>
        <div hidden={state.mode !== 'focus'}>
          <ResearchGraph
            invId={inv.id}
            entity={entity}
            refresh={refresh}
            pins={state.pins}
            trail={state.trail}
            onPin={togglePin}
            onSelect={chooseEntity}
            onEvidence={onEvidence}
          />
        </div>
        <footer className="map-footer">
          <span>
            <span className="legend-dot" />
            {state.mode === 'groups'
              ? criterionLabel(state.criterion)
              : 'Yalnız kaydedilmiş ilişkiler gösterilir'}
          </span>
          {group ? (
            <button
              className="text-button"
              onClick={() => {
                chooseGroup(null);
                setState((current) => ({ ...current, mode: 'groups' }));
              }}
            >
              Tüm varlıkları göster
              <ArrowRight size={14} />
            </button>
          ) : null}
        </footer>
      </section>
      <section className="panel entities-panel">
        <div className="section-toolbar">
          <div>
            <strong>{group ? groupTitle(group) : 'Araştırma kapsamı'}</strong>
            <span className="result-total" data-testid="entity-total">
              {entities.data?.total_unique ?? '…'}{' '}
              {state.filters.kind === 'domain'
                ? 'alan adı'
                : state.filters.kind === 'ip'
                  ? 'IP adresi'
                  : 'URL'}
            </span>
          </div>
          <div className="tab-list compact">
            {[
              ['domain', 'Alan adları'],
              ['ip', 'IP adresleri'],
              ['url', 'URL’ler'],
            ].map(([kind, label]) => (
              <button aria-pressed={state.filters.kind === kind} key={kind} onClick={() => filter({ kind })}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="research-selection">
          <span>
            {state.selected.length
              ? `${state.selected.length} varlık seçili`
              : 'Grafiğe sabitlemek için varlık seçin'}
            <small>En fazla 20 seçim · 25 kayıt / sayfa</small>
          </span>
          <button className="button" disabled={!state.selected.length} onClick={pinSelection}>
            <Pin size={14} />
            Seçilenleri grafiğe sabitle
          </button>
          {state.selected.length > 0 && (
            <button
              className="text-button"
              onClick={() => setState((current) => ({ ...current, selected: [] }))}
            >
              Seçimi temizle
            </button>
          )}
        </div>
        {entities.error ? (
          <ErrorBox message={entities.error} onRetry={entities.reload} />
        ) : entities.loading ? (
          <Loading />
        ) : !visible.length ? (
          <Empty title={search ? 'Araştırmada eşleşme yok' : 'Bu kapsamda varlık yok'}>
            Aramayı veya etkin filtreleri değiştirin.
          </Empty>
        ) : (
          <div className="table-scroll">
            <table className="entity-table">
              <thead>
                <tr>
                  <th className="research-checkbox-cell">SEÇ</th>
                  <th>{kindLabel(state.filters.kind).toLocaleUpperCase('tr')}</th>
                  <th>KANIT</th>
                  <th>SON GÖZLEM</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.id} className={entity?.id === item.id ? 'selected' : ''}>
                    <td className="research-checkbox-cell">
                      <input
                        type="checkbox"
                        aria-label={`Seç: ${item.canonical_value}`}
                        checked={selectedIds.has(item.id)}
                        disabled={!selectedIds.has(item.id) && state.selected.length >= PIN_LIMIT}
                        onChange={() => toggleSelection(item)}
                      />
                    </td>
                    <td>
                      <button
                        className="entity-link"
                        aria-label={`${item.canonical_value} ayrıntıları`}
                        onClick={() => chooseEntity(item)}
                      >
                        {item.kind === 'ip' ? <Server size={14} /> : <Globe2 size={14} />}
                        <span>{item.canonical_value}</span>
                      </button>
                      <div className="research-entity-signals">
                        {item.has_capture && <span>Görsel kanıt</span>}
                        {item.shared_signals?.map((signal) => (
                          <span key={signal}>
                            {signal === 'javascript'
                              ? 'Ortak JS'
                              : signal === 'certificate'
                                ? 'Ortak sertifika'
                                : signal}
                          </span>
                        ))}
                        {item.priority_score != null && (
                          <span title="İnceleme önceliği; olasılık değildir">
                            Öncelik {item.priority_score}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className="evidence-count">
                        {item.evidence_count ?? '—'}
                        <Link2 size={12} />
                      </span>
                    </td>
                    <td className="muted small">{date(item.last_seen)}</td>
                    <td>
                      <button
                        className="row-arrow"
                        aria-label={`${item.canonical_value} yakın görünüm`}
                        onClick={() => chooseEntity(item)}
                      >
                        <ArrowRight size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination
          page={page}
          next={!!entities.data?.next_cursor && !entities.loading && search === state.filters.q.trim()}
          onPrev={() => setPagination({ key: filterQuery, page: page - 1, cursors })}
          onNext={() => {
            if (entities.data?.next_cursor)
              setPagination({
                key: filterQuery,
                page: page + 1,
                cursors: [...cursors.slice(0, page + 1), entities.data.next_cursor],
              });
          }}
          total={entities.data?.total_unique || 0}
          count={entities.data?.items.length || 0}
        />
      </section>
    </div>
  );
}
