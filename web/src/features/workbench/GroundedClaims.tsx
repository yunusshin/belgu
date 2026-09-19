import { ArrowRight, BookOpen, ShieldCheck } from 'lucide-react';
import { casePath, query, useResource } from '../../api/client';
import type { Analysis } from '../../api/types';
import type { Grounding } from '../../api/workbench';
import { Badge, date, ErrorBox, Loading } from '../../components/UI';
import { displayValue, Limitations } from './Common';
export function GroundedClaims({
  invId,
  analysis,
  onEvidence,
}: {
  invId: string;
  analysis: Analysis;
  onEvidence: (id: string) => void;
}) {
  const resource = useResource<Grounding>(
    `${casePath(invId)}/grounding?${query({ analysis_id: analysis.id })}`,
  );
  return (
    <>
      <div className="claims">
        {analysis.output.claims?.map((claim, index) => {
          const grounded = resource.data?.claims.find((item) => item.index === index),
            kind = grounded?.kind || claim.kind;
          return (
            <article key={index}>
              <span className="claim-number">{String(index + 1).padStart(2, '0')}</span>
              <div>
                <Badge tone={kind === 'observation' ? 'accent' : 'amber'}>
                  {kind === 'observation'
                    ? 'Gözlem'
                    : kind === 'hypothesis'
                      ? 'Hipotez'
                      : kind || 'Tür belirtilmemiş'}
                </Badge>
                <p>{claim.text}</p>
                <div className="citation-list">
                  {claim.evidence_ids.map((id, n) => (
                    <button key={id} onClick={() => onEvidence(id)}>
                      <BookOpen size={12} />
                      Kanıt {n + 1}
                      <ArrowRight size={11} />
                    </button>
                  ))}
                </div>
                {!claim.evidence_ids.length && (
                  <p className="grounding-warning">Bu iddia için kaynak kanıtı belirtilmemiş.</p>
                )}
                {grounded && (
                  <>
                    <Limitations items={grounded.warnings} />
                    <details className="grounding-fields">
                      <summary>
                        <ShieldCheck size={13} />
                        Kaynak alanları ve zamanları <span>{grounded.support.length} kayıt</span>
                      </summary>
                      {grounded.support.length ? (
                        grounded.support.map((source) => (
                          <section key={source.id}>
                            <header>
                              <strong>{source.provider}</strong>
                              <button className="text-button" onClick={() => onEvidence(source.id)}>
                                Kaydı aç
                                <ArrowRight size={12} />
                              </button>
                            </header>
                            <p className="mono">{displayValue(source.subject)}</p>
                            <div className="grounding-times">
                              <span>
                                Gözlem zamanı<strong>{date(source.observed_at, true)}</strong>
                              </span>
                              <span>
                                Alınma zamanı<strong>{date(source.retrieved_at, true)}</strong>
                              </span>
                            </div>
                            <dl>
                              {source.fields.map((field, i) => (
                                <div key={i}>
                                  <dt>{field.path}</dt>
                                  <dd>{displayValue(field.value)}</dd>
                                </div>
                              ))}
                            </dl>
                            {!source.fields.length && (
                              <p className="small muted">Bu kaynakta gösterilebilir alan bulunmuyor.</p>
                            )}
                          </section>
                        ))
                      ) : (
                        <p className="grounding-warning">
                          Bu incelemeye ait erişilebilir bir atıf bulunmuyor.
                        </p>
                      )}
                    </details>
                  </>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {resource.loading && <Loading label="Atıfların kaynak alanları yükleniyor" />}
      {resource.error && <ErrorBox message={resource.error} onRetry={resource.reload} />}
      {resource.data && (
        <>
          <Limitations items={resource.data.limitations} />
        </>
      )}
    </>
  );
}
