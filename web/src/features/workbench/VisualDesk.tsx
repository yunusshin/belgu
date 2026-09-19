import { useState, type FormEvent } from 'react';
import { Camera, ImagePlus, ScanText, TextCursorInput, Upload } from 'lucide-react';
import { api, casePath, useResource } from '../../api/client';
import type { Captures, WorkbenchProps } from '../../api/workbench';
import type { Job } from '../../api/types';
import { Badge, date, Empty, ErrorBox, Loading, Success } from '../../components/UI';
import { activeJob } from '../Jobs';
import { DeskHeading, EvidenceLinks, errorMessage, Limitations } from './Common';
import { ImageComparison } from './ImageComparison';
import { ObservationDetails, profileLabel, VisualSimilarity } from './VisualIntelligence';
const ocrLabels: Record<string, string> = {
  ok: 'Yerel OCR tamamlandı',
  completed: 'Yerel OCR tamamlandı',
  empty: 'OCR metin saptamadı',
  unavailable: 'Yerel OCR kurulu değil',
  error: 'OCR tamamlanamadı',
  cancelled: 'OCR iptal edildi',
};
export function VisualDesk({ inv, refresh, onChange, onJob, onEvidence }: WorkbenchProps) {
  const resource = useResource<Captures>(`${casePath(inv.id)}/captures`, refresh);
  const [url, setUrl] = useState(inv.submissions?.[0]?.target.raw_value || ''),
    [selected, setSelected] = useState(''),
    [reference, setReference] = useState(''),
    [profile, setProfile] = useState<'desktop' | 'mobile' | 'both'>('desktop'),
    [mode, setMode] = useState<'reference' | 'observations'>('reference'),
    [secondId, setSecondId] = useState(''),
    [busy, setBusy] = useState(''),
    [error, setError] = useState(''),
    [success, setSuccess] = useState('');
  const data = resource.data,
    capture = data?.items.find((item) => item.id === selected) || data?.items[0],
    brandImage = data?.references.find((item) => item.id === reference) || data?.references[0],
    second =
      data?.items.find((item) => item.id === secondId && item.id !== capture?.id) ||
      data?.items.find((item) => item.id !== capture?.id);
  async function collect(event: FormEvent) {
    event.preventDefault();
    setBusy('capture');
    setError('');
    setSuccess('');
    try {
      const profiles = profile === 'both' ? ['desktop', 'mobile'] : [profile];
      const results = await Promise.allSettled(
        profiles.map(async (selectedProfile) => {
          const job = await api.post<Job>(`${casePath(inv.id)}/captures`, {
            url: url.trim(),
            profile: selectedProfile,
          });
          onJob(job);
          return job;
        }),
      );
      const queued = results.filter((result) => result.status === 'fulfilled').length;
      if (queued)
        setSuccess(
          `${queued} bağımsız görsel yakalama işi sıraya alındı. Her iş ayrı izlenebilir ve iptal edilebilir.`,
        );
      const failed = results.find((result) => result.status === 'rejected');
      if (failed?.status === 'rejected') setError(errorMessage(failed.reason));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy('');
    }
  }
  async function upload(file: File) {
    setBusy('upload');
    setError('');
    setSuccess('');
    try {
      const body = new FormData();
      body.append('file', file);
      const saved = await api.request<{ id: string }>(
        `/brands/${encodeURIComponent(inv.brand_id)}/attachments`,
        { method: 'POST', body },
      );
      setReference(saved.id);
      resource.reload();
      onChange();
      setSuccess('Marka referansı kaydedildi.');
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy('');
    }
  }
  return (
    <>
      <DeskHeading eyebrow="GÖRÜNTÜDEN KAYNAĞA" title="Sayfayı olduğu gibi inceleyin.">
        Yakalanan sayfayı marka referansıyla karşılaştırın; metin, form alanları ve gözlem zamanı birlikte
        korunsun.
      </DeskHeading>
      <form className="desk-capture-form panel" onSubmit={collect}>
        <label>
          İncelenecek URL
          <input
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://incelenecek-adres.test/giris"
            list="capture-targets"
          />
        </label>
        <datalist id="capture-targets">
          {inv.submissions?.map((s) => (
            <option key={s.id} value={s.target.raw_value} />
          ))}
        </datalist>
        <label className="capture-profile-select">
          Yakalama profili
          <select
            aria-label="Yakalama profili"
            value={profile}
            onChange={(e) => setProfile(e.target.value as typeof profile)}
          >
            <option value="desktop">Masaüstü · 1365 × 900</option>
            <option value="mobile">Mobil · 390 × 844</option>
            <option value="both">Her iki profil</option>
          </select>
        </label>
        <button
          className="button primary"
          disabled={
            inv.demo ||
            !!busy ||
            !data ||
            data.capabilities.status !== 'ready' ||
            inv.jobs?.some((j) => j.kind === 'capture' && activeJob(j))
          }
        >
          <Camera size={15} />
          {busy === 'capture' ? 'Başlatılıyor…' : profile === 'both' ? 'İki profili yakala' : 'Görüntü al'}
        </button>
        <p className="small muted">
          {inv.demo
            ? 'Demo ortamında yeni ağ çalışması başlatılmaz.'
            : data?.capabilities.message || 'Tarayıcı durumu kontrol ediliyor.'}{' '}
          Formlar gönderilmez.
        </p>
      </form>
      {error && <ErrorBox message={error} />}
      {success && <Success>{success}</Success>}
      {resource.error && <ErrorBox message={resource.error} onRetry={resource.reload} />}
      {resource.loading ? (
        <Loading label="Görsel kanıtlar yükleniyor" />
      ) : (
        data && (
          <>
            {!!data.failures?.length && (
              <section className="panel capture-failures" aria-label="Başarısız yakalamalar">
                <h3>Yakalama tamamlanamadı</h3>
                {data.failures.map((failure) => (
                  <article key={failure.evidence_id}>
                    <Badge tone="amber">
                      {profileLabel(failure)} · {failure.status === 'cancelled' ? 'İptal' : 'Başarısız'}
                    </Badge>
                    <p>{failure.reason}</p>
                    <EvidenceLinks ids={[failure.evidence_id]} onEvidence={onEvidence} />
                  </article>
                ))}
              </section>
            )}
            <div className="visual-mode" role="group" aria-label="Görsel inceleme türü">
              <button
                type="button"
                className="button"
                aria-pressed={mode === 'reference'}
                onClick={() => setMode('reference')}
              >
                Marka referansıyla
              </button>
              <button
                type="button"
                className="button"
                aria-pressed={mode === 'observations'}
                onClick={() => setMode('observations')}
              >
                İki gözlem
              </button>
            </div>
            <div className="desk-image-grid comparison-source-grid">
              <section className="panel desk-image-pane">
                <header>
                  <div>
                    <span className="desk-pane-index">01</span>
                    <h3>Yakalanan sayfa</h3>
                  </div>
                  <Badge tone="accent">{data.items.length} kayıt</Badge>
                </header>
                {data.items.length > 0 && (
                  <select
                    className="desk-select"
                    aria-label="Görsel kanıt kaydı"
                    value={capture?.id || ''}
                    onChange={(e) => setSelected(e.target.value)}
                  >
                    {data.items.map((item) => (
                      <option key={item.id} value={item.id}>
                        {profileLabel(item)} · {date(item.observed_at, true)} · {item.final_url || item.url}
                      </option>
                    ))}
                  </select>
                )}
                {capture ? (
                  <>
                    <footer>
                      <code>{capture.final_url || capture.url}</code>
                      <span>
                        {profileLabel(capture)} · {date(capture.observed_at, true)} · HTTP{' '}
                        {capture.status_code ?? '—'}
                      </span>
                      <EvidenceLinks ids={[capture.evidence_id]} onEvidence={onEvidence} />
                    </footer>
                  </>
                ) : (
                  <Empty title="Henüz bir sayfa görüntüsü yok" icon={<Camera size={30} />}>
                    Başlangıç bulgusunun adresini seçip görüntü alarak başlayın.
                  </Empty>
                )}
              </section>
              {mode === 'observations' ? (
                <section className="panel desk-image-pane">
                  <header>
                    <h3>İkinci gözlem</h3>
                    <Badge>Analist seçimi</Badge>
                  </header>
                  <select
                    className="desk-select"
                    aria-label="İkinci gözlem"
                    value={second?.id || ''}
                    onChange={(e) => setSecondId(e.target.value)}
                  >
                    {!second && <option value="">İkinci bir yakalama gerekli</option>}
                    {data.items
                      .filter((item) => item.id !== capture?.id)
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {profileLabel(item)} · {date(item.observed_at, true)} · {item.final_url || item.url}
                        </option>
                      ))}
                  </select>
                  {second && (
                    <footer>
                      <code>{second.final_url || second.url}</code>
                      <EvidenceLinks ids={[second.evidence_id]} onEvidence={onEvidence} />
                    </footer>
                  )}
                </section>
              ) : (
                <section className="panel desk-image-pane">
                  <header>
                    <div>
                      <span className="desk-pane-index">02</span>
                      <h3>Marka referansı</h3>
                    </div>
                    <Badge>Analist seçimi</Badge>
                  </header>
                  {data.references.length > 0 && (
                    <select
                      className="desk-select"
                      aria-label="Marka referansı"
                      value={brandImage?.id || ''}
                      onChange={(e) => setReference(e.target.value)}
                    >
                      {data.references.map((item, index) => (
                        <option key={item.id} value={item.id}>
                          Referans {index + 1} · {date(item.created_at, true)}
                        </option>
                      ))}
                    </select>
                  )}
                  {!brandImage && (
                    <Empty title="Karşılaştırma için referans ekleyin" icon={<ImagePlus size={30} />}>
                      Markanın güvenilir sayfasına ait bir ekran görüntüsü yükleyin.
                    </Empty>
                  )}
                  <footer>
                    <label className={`button desk-upload ${busy ? 'disabled' : ''}`}>
                      <Upload size={14} />
                      {busy === 'upload' ? 'Yükleniyor…' : 'Referans yükle'}
                      <input
                        aria-label="Marka referansı yükle"
                        type="file"
                        accept="image/png,image/jpeg"
                        disabled={!!busy}
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) void upload(file);
                          e.target.value = '';
                        }}
                      />
                    </label>
                    <span>PNG veya JPEG · En fazla 10 MB</span>
                  </footer>
                </section>
              )}
            </div>
            <ImageComparison
              key={`${mode}:${capture?.id || ''}:${second?.id || ''}:${brandImage?.id || ''}`}
              capture={capture ? { src: capture.image_url, label: 'Yakalanan sayfa' } : undefined}
              reference={
                mode === 'observations'
                  ? second
                    ? { src: second.image_url, label: 'İkinci gözlem' }
                    : undefined
                  : brandImage
                    ? { src: brandImage.image_url, label: 'Marka referansı' }
                    : undefined
              }
            />
            <p className="desk-caption">
              <ScanText size={14} />
              Model analizinde sayfanın metin kanıtları kullanılır.
            </p>
            {mode === 'observations' && (
              <ObservationDetails first={capture} second={second} onEvidence={onEvidence} />
            )}
            <VisualSimilarity
              caseId={inv.id}
              referenceId={mode === 'reference' ? brandImage?.id : second?.id}
              refresh={refresh}
              onEvidence={onEvidence}
              onOpen={(id) => {
                if (mode === 'observations' && second) setSecondId(second.id);
                setSelected(id);
                document
                  .querySelector('.image-comparison')
                  ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
            />
            {capture && mode === 'reference' && (
              <div className="desk-evidence-grid">
                <section className="panel desk-detail">
                  <div className="section-title">
                    <ScanText size={17} />
                    <h3>Sayfanın metni</h3>
                    <Badge>Tarayıcı metni</Badge>
                  </div>
                  <pre className="desk-text">
                    {capture.text || 'Bu yakalamada görünür metin kaydedilmedi.'}
                  </pre>
                  {capture.text_truncated && (
                    <p className="small muted">Uzun sayfa metni toplama sınırında kısaltıldı.</p>
                  )}
                  <div className="desk-ocr">
                    <div className="section-title">
                      <h3>OCR metni</h3>
                      <Badge tone={['ok', 'completed'].includes(capture.ocr_status) ? 'accent' : 'amber'}>
                        {ocrLabels[capture.ocr_status] || capture.ocr_status || 'OCR durumu bilinmiyor'}
                      </Badge>
                    </div>
                    <p>
                      Görüntüden yerel OCR ile çıkarılmıştır. Okuma hataları olabilir; sayfa metninden ayrı
                      bir kaynaktır.
                    </p>
                    <p className="small muted">
                      {capture.ocr?.engine && `Motor: ${capture.ocr.engine}`}
                      {capture.ocr?.languages && ` · Dil: ${capture.ocr.languages}`}
                    </p>
                    <pre className="desk-text">{capture.ocr_text || 'OCR metni bulunmuyor.'}</pre>
                  </div>
                </section>
                <section className="panel desk-detail">
                  <div className="section-title">
                    <TextCursorInput size={17} />
                    <h3>Form ve giriş alanları</h3>
                    <Badge>{capture.forms.length} form</Badge>
                  </div>
                  {capture.forms.length ? (
                    capture.forms.map((form, index) => (
                      <article className="desk-form-record" key={index}>
                        <div>
                          <strong>Form {index + 1}</strong>
                          <Badge>{(form.method || 'get').toUpperCase()}</Badge>
                        </div>
                        <code>{form.action || 'Form hedefi belirtilmemiş'}</code>
                        {form.inputs?.length ? (
                          <div className="desk-input-list">
                            {form.inputs.map((input, i) => (
                              <div key={i}>
                                <code>{input.name || input.id || input.placeholder || `Alan ${i + 1}`}</code>
                                <Badge tone={input.type === 'password' ? 'amber' : 'neutral'}>
                                  {input.type || input.tag || 'text'}
                                </Badge>
                                <small>
                                  {[
                                    input.required ? 'Zorunlu' : '',
                                    input.disabled ? 'Devre dışı' : '',
                                    input.visible === false ? 'Gizli' : '',
                                  ]
                                    .filter(Boolean)
                                    .join(' · ')}
                                </small>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="muted small">Bu formda giriş alanı kaydedilmedi.</p>
                        )}
                      </article>
                    ))
                  ) : (
                    <p className="muted">
                      Bu yakalamada form saptanmadı. Bu sonuç sayfada hiçbir zaman form bulunmadığını
                      göstermez.
                    </p>
                  )}
                  <Limitations items={capture.limitations || []} />
                  {(capture.forms_truncated || capture.inputs_truncated) && (
                    <p className="callout amber">Alan listesi toplama sınırı nedeniyle kısaltıldı.</p>
                  )}
                  <p className="desk-caption">
                    Alanlar yalnızca gözlemlendi; herhangi bir bilgi girilmedi veya gönderilmedi.
                  </p>
                </section>
              </div>
            )}
          </>
        )
      )}
    </>
  );
}
