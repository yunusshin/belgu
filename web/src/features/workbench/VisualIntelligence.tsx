import type { Capture, VisualRanking } from '../../api/workbench';
import { casePath, useResource } from '../../api/client';
import { Badge, date, Empty, ErrorBox, Loading } from '../../components/UI';
import { EvidenceLinks, Limitations } from './Common';
import './visual-intelligence.css';

export function profileLabel(capture: Partial<Capture>) {
  return (
    capture.profile_label ||
    (capture.profile === 'mobile'
      ? 'Mobil'
      : capture.profile
        ? 'Masaüstü'
        : 'Masaüstü · eski kayıt (ayarlar bilinmiyor)')
  );
}
const reasonLabels: Record<string, string> = {
  incompatible_geometry: 'En-boy oranları uyumsuz; sayısal karşılaştırma yapılmadı.',
  incompatible_profile: 'Profiller farklı; sayısal karşılaştırma yapılmadı.',
  low_detail: 'Görüntü boş veya yeterli ayrıntı içermiyor.',
  unreadable: 'Görüntü okunamadı.',
  capture_artifact_unavailable: 'Yakalama görüntüsü bulunamadı.',
  reference_artifact_unavailable: 'Referans görüntüsü bulunamadı.',
  missing_or_oversize: 'Görüntü eksik veya boyut sınırının üzerinde.',
  unreasonable_dimensions: 'Görüntü boyutları değerlendirme sınırları dışında.',
};

export function VisualSimilarity({
  caseId,
  referenceId,
  refresh,
  onOpen,
  onEvidence,
}: {
  caseId: string;
  referenceId?: string;
  refresh: number;
  onOpen: (evidenceId: string) => void;
  onEvidence: (id: string) => void;
}) {
  const resource = useResource<VisualRanking>(
    referenceId
      ? `${casePath(caseId)}/visual-similarity?reference_id=${encodeURIComponent(referenceId)}`
      : null,
    refresh,
  );
  const data = resource.data;
  return (
    <section className="panel visual-ranking" aria-label="Yerel görsel sıralama">
      <header>
        <div>
          <span className="eyebrow">YEREL GÖRÜNTÜ İŞLEME</span>
          <h3>Yerel görsel sıralama</h3>
        </div>
        <Badge>Sezgisel · 0–100</Badge>
      </header>
      <p className="muted small">
        Seçili referansa göre algısal yapı, kenar yerleşimi ve renk benzerliği.
      </p>
      {!referenceId ? (
        <Empty title="Sıralama için bir referans seçin">
          Marka görüntüsü yükleyin veya iki gözlem görünümünü açın.
        </Empty>
      ) : resource.loading ? (
        <Loading label="Görüntüler yerel olarak karşılaştırılıyor" />
      ) : resource.error ? (
        <ErrorBox message={resource.error} onRetry={resource.reload} />
      ) : (
        data && (
          <>
            <div className="visual-coverage" aria-label="Görsel kapsam">
              <span>
                <strong>{data.coverage.captures}</strong> yakalama
              </span>
              <span>
                <strong>{data.coverage.assessed_unique}</strong> benzersiz puan
              </span>
              <span>
                <strong>{data.coverage.unassessed}</strong> değerlendirilmedi
              </span>
              <span>
                <strong>{data.coverage.duplicates}</strong> tekrar birleştirildi
              </span>
            </div>
            <div className="visual-rank-list">
              {data.items.map((item) => (
                <article key={item.evidence_id} className="visual-rank-card">
                  <div className="visual-score">
                    <strong>{item.score.toFixed(1)}</strong>
                    <span>/ 100</span>
                  </div>
                  <div className="visual-rank-detail">
                    <code>{item.final_url || item.url}</code>
                    <p className="small muted">
                      {profileLabel(item)} · {date(item.observed_at, true)}
                    </p>
                    <div className="visual-components">
                      {[
                        ['Algısal', item.components.perceptual],
                        ['Yapı', item.components.structure],
                        ['Renk', item.components.color],
                      ].map(([label, value]) => (
                        <span key={label}>
                          {label} <strong>{Number(value).toFixed(0)}</strong>
                        </span>
                      ))}
                    </div>
                    <EvidenceLinks ids={item.evidence_ids} onEvidence={onEvidence} />
                  </div>
                  <button type="button" className="button" onClick={() => onOpen(item.evidence_id)}>
                    Görüntüleri aç
                  </button>
                </article>
              ))}
            </div>
            {data.unassessed.length > 0 && (
              <details className="visual-unassessed">
                <summary>Değerlendirilmeyen görüntüler ({data.unassessed.length})</summary>
                {data.unassessed.map((item) => (
                  <article key={item.evidence_id}>
                    <code>{item.url}</code>
                    <p>{reasonLabels[item.reason] || 'Bu görüntü değerlendirilemedi.'}</p>
                    <EvidenceLinks ids={[item.evidence_id]} onEvidence={onEvidence} />
                  </article>
                ))}
              </details>
            )}
            <p className="small muted">
              Yöntem: <code>{data.method_version}</code> · EXIF yönü düzeltilir, sayfa kırpılmaz. En-boy oranı
              farkı %3 üzerinde olduğunda puan verilmez.
            </p>
            <Limitations items={data.limitations} />
          </>
        )
      )}
    </section>
  );
}

export function ObservationDetails({
  first,
  second,
  onEvidence,
}: {
  first?: Capture;
  second?: Capture;
  onEvidence: (id: string) => void;
}) {
  if (!first || !second)
    return <Empty title="İki farklı gözlem seçin">Kaydedilmiş görüntüler ayrı gözlem olarak korunur.</Empty>;
  const compatible =
    first.profile === second.profile &&
    first.viewport?.width === second.viewport?.width &&
    first.viewport?.height === second.viewport?.height;
  return (
    <section className="panel observation-details" aria-label="Gözlem farkları">
      <h3>Gözlem farkları</h3>
      <div className="visual-coverage">
        <span>
          Son URL:{' '}
          <strong>
            {(first.final_url || first.url) === (second.final_url || second.url) ? 'aynı' : 'farklı'}
          </strong>
        </span>
        <span>
          DOM metni:{' '}
          <strong>
            {!first.text || !second.text ? 'eksik gözlem' : first.text === second.text ? 'aynı' : 'farklı'}
          </strong>
        </span>
        <span>
          Form yapısı:{' '}
          <strong>
            {!first.forms || !second.forms
              ? 'eksik gözlem'
              : JSON.stringify(first.forms) === JSON.stringify(second.forms)
                ? 'aynı'
                : 'farklı'}
          </strong>
        </span>
      </div>
      {!compatible && (
        <p className="visual-profile-note">
          Farklı profil veya görünüm alanı: elle inceleme mümkündür; bütün sayfa için sayısal eşleşme
          çıkarılmaz.
        </p>
      )}
      <p className="small muted">
        Farklar bu iki gözleme aittir. Kaydedilmeyen içerik yokluk kanıtı değildir; DOM, form alanları ve OCR
        ayrı kaynaklardır.
      </p>
      <div className="observation-pair">
        {[first, second].map((capture, index) => (
          <article key={capture.id}>
            <header>
              <strong>{index + 1}. gözlem</strong>
              <Badge>{profileLabel(capture)}</Badge>
            </header>
            <p className="small">
              Gözlem: {date(capture.observed_at, true)}
              <br />
              Toplama: {capture.retrieved_at ? date(capture.retrieved_at, true) : 'Kaydedilmemiş'}
            </p>
            <p className="small">
              Görünüm:{' '}
              {capture.viewport
                ? `${capture.viewport.width} × ${capture.viewport.height}`
                : 'Eski kayıt · masaüstü varsayımı'}
            </p>
            <details>
              <summary>Tarayıcı kimliği</summary>
              <code>{capture.user_agent || 'Eski kayıtta tarayıcı kimliği yok'}</code>
            </details>
            <h4>Son URL</h4>
            <code>{capture.final_url || capture.url}</code>
            <h4>DOM metni</h4>
            <pre className="desk-text">{capture.text || 'Metin kaydedilmedi.'}</pre>
            <h4>DOM formları · {capture.forms?.length ?? 0}</h4>
            {capture.forms?.length ? (
              capture.forms.map((form, i) => (
                <div key={i} className="visual-form">
                  <code>
                    {(form.method || 'get').toUpperCase()} {form.action}
                  </code>
                  {form.inputs?.map((input, j) => (
                    <p key={j} className="small">
                      {input.name || input.id || 'Adsız alan'} · {input.type || input.tag} ·{' '}
                      {input.visible === false ? 'gizli' : 'görünür'}
                    </p>
                  ))}
                </div>
              ))
            ) : (
              <p className="small muted">Form kaydedilmedi.</p>
            )}
            <h4>Görüntüden OCR · {capture.ocr_status || 'bilinmiyor'}</h4>
            <pre className="desk-text">{capture.ocr_text || 'OCR metni kaydedilmedi.'}</pre>
            <EvidenceLinks ids={[capture.evidence_id]} onEvidence={onEvidence} />
          </article>
        ))}
      </div>
    </section>
  );
}
