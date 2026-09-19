import { useState } from 'react';
import { ArrowUpRight, History, ChevronLeft, ChevronRight } from 'lucide-react';
import { casePath, query, useResource } from '../../api/client';
import type { MemoryResponse, ScopedEvidenceRef } from '../../api/intelligence';
import type { WorkbenchProps } from '../../api/workbench';
import { Badge, date, decisionLabel, Empty, ErrorBox, Loading } from '../../components/UI';
import { DeskHeading, Limitations } from './Common';
import '../../styles/intelligence.css';

export function MemoryDesk(props: WorkbenchProps) {
  return <MemoryContent key={props.inv.id} {...props} />;
}
function MemoryContent({ inv, refresh, onEvidence }: WorkbenchProps) {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const page = cursors.length - 1;
  const resource = useResource<MemoryResponse>(
    `${casePath(inv.id)}/memory?${query({ limit: 20, cursor: cursors[page] })}`,
    refresh,
  );
  function retry() {
    setCursors([null]);
    resource.reload();
  }
  return (
    <>
      <DeskHeading
        eyebrow="ARAŞTIRMALAR ARASINDA"
        title="Bu izi daha önce gördük mü?"
        action={resource.data && <Badge>{resource.data.total_unique} ilişkili inceleme</Badge>}
      >
        Kayıtlı araştırmalardaki ortak içerik ve altyapı izlerini, önceki kararların bağlamıyla karşılaştırın.
      </DeskHeading>
      {inv.demo && (
        <p className="intelligence-mode">
          <History size={14} /> Kayıtlı demo araştırmaları arasında yerel karşılaştırma
        </p>
      )}
      {resource.error ? (
        <ErrorBox message={resource.error} onRetry={retry} />
      ) : resource.loading ? (
        <Loading label="İnceleme hafızası taranıyor" />
      ) : !resource.data?.items.length ? (
        <div className="panel">
          <Empty title="Henüz ilişkili inceleme yok" icon={<History size={28} />}>
            Kayıtlı gözlemlerde ortak IP, sertifika veya içerik özeti bulunduğunda dayanakları burada görünür.
          </Empty>
        </div>
      ) : (
        <div className="memory-list">
          {resource.data.items.map((item) => (
            <article className="panel memory-card" key={item.investigation_id}>
              <header>
                <div>
                  <span className="eyebrow">ÖNCEKİ İNCELEME</span>
                  <h3>{item.title}</h3>
                  <span className="small muted">{item.brand_name}</span>
                </div>
                <Badge tone={item.priority === 'high' ? 'accent' : 'neutral'}>
                  {item.priority === 'high' ? 'Yüksek' : item.priority === 'medium' ? 'Orta' : 'Düşük'}{' '}
                  öncelik
                </Badge>
              </header>
              <div className="memory-decision">
                <Badge>{item.workflow === 'closed' ? 'Kapalı inceleme' : 'Açık inceleme'}</Badge>
                <strong>{decisionLabel(item.disposition)}</strong>
                {item.decision && (
                  <>
                    <time>{date(item.decision.created_at, true)}</time>
                    <p>{item.decision.note || 'Karar notu eklenmemiş.'}</p>
                  </>
                )}
              </div>
              <div className="memory-reasons">
                {item.reasons.map((reason, index) => (
                  <div key={index}>
                    <strong>{reason.label}</strong>
                    {reason.discounted && <Badge>Ayırt ediciliği düşük</Badge>}
                    <code title={reason.value}>{reason.value}</code>
                    <p>{reason.detail}</p>
                  </div>
                ))}
              </div>
              <div className="memory-sources">
                <SourceColumn
                  title="GÜNCEL ARAŞTIRMA"
                  refs={item.evidence_refs.filter((ref) => ref.investigation_id === inv.id)}
                  label="Güncel kanıtı aç"
                  onEvidence={onEvidence}
                />
                <SourceColumn
                  title="ÖNCEKİ ARAŞTIRMA"
                  refs={item.evidence_refs.filter((ref) => ref.investigation_id !== inv.id)}
                  label="Önceki kanıtı aç"
                  onEvidence={onEvidence}
                />
              </div>
            </article>
          ))}
        </div>
      )}
      {resource.data && (
        <>
          <nav className="intelligence-pagination" aria-label="Hafıza sayfaları">
            <span>
              {resource.data.coverage.cases_scanned} araştırma tarandı
              {resource.data.coverage.truncated ? ' · Sınırlı kapsam' : ''}
            </span>
            <div>
              <button
                className="icon-button"
                aria-label="Önceki hafıza sayfası"
                disabled={!page || resource.loading}
                onClick={() => setCursors(cursors.slice(0, -1))}
              >
                <ChevronLeft size={16} />
              </button>
              <span>{page + 1}</span>
              <button
                className="icon-button"
                aria-label="Sonraki hafıza sayfası"
                disabled={!resource.data.next_cursor || resource.loading}
                onClick={() =>
                  resource.data?.next_cursor && setCursors([...cursors, resource.data.next_cursor])
                }
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </nav>
          <Limitations items={resource.data.limitations} />
        </>
      )}
    </>
  );
}
function SourceColumn({
  title,
  refs,
  label,
  onEvidence,
}: {
  title: string;
  refs: ScopedEvidenceRef[];
  label: string;
  onEvidence: WorkbenchProps['onEvidence'];
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <section>
      <span className="eyebrow">{title}</span>
      {(expanded ? refs : refs.slice(0, 3)).map((ref) => (
        <div className="memory-source" key={ref.evidence_id}>
          <button
            className="text-button"
            aria-label={label}
            onClick={() => onEvidence(ref.evidence_id, ref.investigation_id)}
          >
            <span>{ref.subject.value}</span>
            <ArrowUpRight size={13} />
          </button>
          <span>Gözlem: {ref.observed_at ? date(ref.observed_at, true) : 'Zaman bilinmiyor'}</span>
          <span>Toplama: {date(ref.retrieved_at, true)}</span>
        </div>
      ))}
      {refs.length > 3 && (
        <button className="text-button" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Daha az göster' : `${refs.length - 3} kaynak daha`}
        </button>
      )}
    </section>
  );
}
