import { useState } from 'react';
import {
  ArrowDownLeft,
  ArrowRight,
  CheckCheck,
  Clock3,
  FolderSearch,
  Plus,
  Search,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react';
import { useResource } from '../api/client';
import type { Collection, Investigation } from '../api/types';
import { Badge, date, decisionLabel, Empty, ErrorBox, Loading, sourceLabel } from '../components/UI';
export default function Queue({ onNew }: { onNew: () => void }) {
  const { data, error, loading, reload } =
    useResource<Collection<Investigation>>('/investigations?limit=100');
  const [search, setSearch] = useState(''),
    [filter, setFilter] = useState('all');
  const cases = data?.items || [],
    visible = cases.filter(
      (c) =>
        (filter === 'all' || c.workflow === filter) &&
        `${c.title} ${c.brand_name}`.toLocaleLowerCase('tr').includes(search.toLocaleLowerCase('tr')),
    );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">ANALİST ÇALIŞMA ALANI</div>
          <h1>İncelemeler</h1>
          <p>İlk işaretten, kanıta dayalı bir karara.</p>
        </div>
        <button className="button primary" onClick={onNew}>
          <Plus size={17} />
          Yeni inceleme
        </button>
      </div>
      <div className="queue-stats">
        <Stat
          icon={<FolderSearch />}
          value={data?.total_unique ?? '—'}
          label="Toplam inceleme"
          detail="Çalışma alanınız"
        />
        <Stat
          icon={<Clock3 />}
          value={cases.filter((c) => c.workflow === 'open').length}
          label="Açık inceleme"
          detail="Analist değerlendirmesinde"
        />
        <Stat
          icon={<ShieldCheck />}
          value={cases.reduce((s, c) => s + c.evidence_count, 0)}
          label="Kanıt kaydı"
          detail="Kaynağı ve zamanı korunur"
        />
        <Stat
          icon={<CheckCheck />}
          value={cases.filter((c) => c.workflow === 'closed').length}
          label="Tamamlanan"
          detail="Karar geçmişiyle birlikte"
        />
      </div>
      <section className="panel queue-panel">
        <div className="section-toolbar">
          <div className="tab-list">
            {[
              ['all', 'Tüm incelemeler'],
              ['open', 'Açık'],
              ['closed', 'Kapalı'],
            ].map(([key, label]) => (
              <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>
                {label}
                {key === 'all' && <span className="count">{cases.length}</span>}
              </button>
            ))}
          </div>
          <label className="search">
            <Search size={16} />
            <input
              aria-label="İncelemelerde ara"
              placeholder="İnceleme veya marka ara…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <kbd>/</kbd>
          </label>
        </div>
        {error ? (
          <ErrorBox message={error} onRetry={reload} />
        ) : loading ? (
          <Loading />
        ) : visible.length === 0 ? (
          <Empty
            title={search ? 'Eşleşen inceleme yok' : 'Henüz inceleme yok'}
            icon={<FolderSearch size={30} />}
          >
            {search
              ? 'Farklı bir arama deneyin.'
              : 'Bir marka ve başlangıç URL’si ekleyerek araştırmaya başlayın.'}
          </Empty>
        ) : (
          <div className="table-scroll">
            <table className="queue-table">
              <thead>
                <tr>
                  <th>İNCELEME / MARKA</th>
                  <th>DURUM</th>
                  <th>KAPSAM</th>
                  <th>BİLDİRİM KAYNAĞI</th>
                  <th>SON GÜNCELLEME</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map((c, i) => (
                  <tr key={c.id}>
                    <td>
                      <div className="case-title">
                        <span className={`brand-avatar hue-${i % 3}`}>
                          {c.brand_name?.slice(0, 1) || 'B'}
                          <span />
                        </span>
                        <div>
                          <a href={`#/investigations/${c.id}`} className="case-link">
                            {c.title}
                          </a>
                          <div className="table-sub">
                            {c.brand_name}
                            <span>·</span>
                            <span className="mono">{c.id.slice(0, 8).toUpperCase()}</span>
                            {c.demo && <span className="mini-demo">DEMO</span>}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <Badge
                        tone={
                          c.workflow === 'closed'
                            ? 'neutral'
                            : c.disposition === 'confirmed_phishing'
                              ? 'danger'
                              : 'amber'
                        }
                      >
                        <i />
                        {c.workflow === 'closed' ? 'Kapalı' : decisionLabel(c.disposition)}
                      </Badge>
                    </td>
                    <td>
                      <span className="table-number">{c.entity_count}</span>
                      <span className="muted"> varlık</span>
                      <div className="table-sub">{c.evidence_count} kanıt</div>
                    </td>
                    <td>
                      <span className="source-cell">
                        <ArrowDownLeft size={14} />
                        {sourceLabel(c.source)}
                      </span>
                    </td>
                    <td className="muted">{date(c.updated_at, true)}</td>
                    <td>
                      <a
                        className="icon-button"
                        aria-label={`${c.title} aç`}
                        href={`#/investigations/${c.id}`}
                      >
                        <ArrowRight size={18} />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="queue-footer">
          <span>
            <SlidersHorizontal size={14} /> {visible.length} inceleme gösteriliyor
          </span>
          <span>Her gözlem, kendi bağlamıyla.</span>
        </div>
      </section>
      <div className="principle">
        <ShieldCheck size={18} />
        <p>
          Bağlantıları keşfedin. Kanıtları değerlendirin.
          <br />
          <strong>Son karar her zaman analistte.</strong>
        </p>
      </div>
    </>
  );
}
function Stat({
  icon,
  value,
  label,
  detail,
}: {
  icon: React.ReactNode;
  value: number | string;
  label: string;
  detail: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">
        {label}
        <span>{icon}</span>
      </div>
      <strong>{value.toLocaleString('tr-TR')}</strong>
      <span className="stat-detail">{detail}</span>
    </div>
  );
}
