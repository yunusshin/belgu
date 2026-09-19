import { useState } from 'react';
import { ArrowDown, ArrowUp, Eye, GripVertical, Pin, X } from 'lucide-react';
import { casePath, useResource } from '../api/client';
import type { Evidence } from '../api/types';
import { date, Empty, ErrorBox, kindLabel, Loading } from '../components/UI';
import { EVIDENCE_LIMIT, useCaseWorkspace } from './workspaceState';

export function EvidenceBoard({
  investigationId,
  onEvidence,
}: {
  investigationId: string;
  onEvidence: (id: string) => void;
}) {
  const { pinnedEvidence, setPinnedEvidence } = useCaseWorkspace();
  return (
    <section
      className="panel evidence-board"
      role="region"
      aria-label="Kanıt panosu"
      id="case-evidence-board"
    >
      <header>
        <div>
          <span className="eyebrow accent">
            <Pin size={13} /> İNCELEME PANOSU
          </span>
          <h2>Dayanaklarınız, sizin sıranızla</h2>
          <p>Bu tarayıcıda saklanır. Paylaşım aracında aynı sırayla sunuma aktarabilirsiniz.</p>
        </div>
        <span className="board-count">
          {pinnedEvidence.length} / {EVIDENCE_LIMIT}
        </span>
      </header>
      {!pinnedEvidence.length ? (
        <Empty title="Henüz sabitlenmiş kanıt yok">Bir kaynak kaydını açıp panoya sabitleyin.</Empty>
      ) : (
        <EvidenceOrderList
          investigationId={investigationId}
          ids={pinnedEvidence}
          onChange={setPinnedEvidence}
          onEvidence={onEvidence}
        />
      )}
    </section>
  );
}
export function EvidenceOrderList({
  investigationId,
  ids,
  onChange,
  onEvidence,
  disabled = false,
}: {
  investigationId: string;
  ids: string[];
  onChange: (ids: string[]) => void;
  onEvidence: (id: string) => void;
  disabled?: boolean;
}) {
  const [dragged, setDragged] = useState<string | null>(null);
  function move(from: number, to: number) {
    if (disabled || from < 0 || to < 0 || from >= ids.length || to >= ids.length || from === to) return;
    const next = [...ids];
    next.splice(to, 0, next.splice(from, 1)[0]);
    onChange(next);
  }
  return (
    <ol className="evidence-order-list">
      {ids.map((id, index) => (
        <li
          key={id}
          data-evidence-id={id}
          draggable={!disabled}
          className={dragged === id ? 'dragging' : ''}
          onDragStart={(event) => {
            setDragged(id);
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', id);
          }}
          onDragEnd={() => setDragged(null)}
          onDragOver={(event) => {
            if (dragged && !disabled) event.preventDefault();
          }}
          onDrop={(event) => {
            event.preventDefault();
            if (dragged && event.dataTransfer.getData('text/plain') === dragged)
              move(ids.indexOf(dragged), index);
            setDragged(null);
          }}
        >
          <span className="evidence-order-number" title="Sürükleyerek sıralayın">
            <GripVertical size={13} />
            {String(index + 1).padStart(2, '0')}
          </span>
          <EvidenceSummary investigationId={investigationId} id={id} />
          <div className="evidence-order-actions">
            <button
              className="icon-button"
              aria-label={`Kanıt ${index + 1} ayrıntıları`}
              onClick={() => onEvidence(id)}
            >
              <Eye size={14} />
            </button>
            <button
              className="icon-button"
              aria-label={`Kanıt ${index + 1} yukarı`}
              disabled={disabled || index === 0}
              onClick={() => move(index, index - 1)}
            >
              <ArrowUp size={14} />
            </button>
            <button
              className="icon-button"
              aria-label={`Kanıt ${index + 1} aşağı`}
              disabled={disabled || index === ids.length - 1}
              onClick={() => move(index, index + 1)}
            >
              <ArrowDown size={14} />
            </button>
            <button
              className="icon-button"
              aria-label={`Kanıt ${index + 1} kaldır`}
              disabled={disabled}
              onClick={() => onChange(ids.filter((value) => value !== id))}
            >
              <X size={14} />
            </button>
          </div>
        </li>
      ))}
    </ol>
  );
}
function EvidenceSummary({ investigationId, id }: { investigationId: string; id: string }) {
  const record = useResource<Evidence>(`${casePath(investigationId)}/evidence/${encodeURIComponent(id)}`);
  return (
    <div className="evidence-order-summary">
      {record.loading ? (
        <Loading label="Kanıt yükleniyor" />
      ) : record.error ? (
        <ErrorBox
          message="Bu kanıt yüklenemedi. Yeniden deneyin veya listeden kaldırın."
          onRetry={record.reload}
        />
      ) : record.data ? (
        <>
          <span>
            {kindLabel(record.data.kind || record.data.subject.kind)} · {record.data.provider}
          </span>
          <strong>{record.data.subject.value}</strong>
          <small>
            {record.data.observed_at ? 'Gözlem' : 'Alınma'} ·{' '}
            {date(record.data.observed_at || record.data.retrieved_at, true)}
          </small>
        </>
      ) : (
        <span>Kanıt kaydı bulunamadı</span>
      )}
    </div>
  );
}
