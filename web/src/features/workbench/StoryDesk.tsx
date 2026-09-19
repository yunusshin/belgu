import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { EvidenceOrderList } from '../EvidenceBoard';
import { evidenceIds, useCaseStoredState, useCaseWorkspace } from '../workspaceState';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  Eye,
  LockKeyhole,
  Presentation,
  ShieldCheck,
  Maximize2,
  Pin,
  X,
} from 'lucide-react';
import { api, casePath, query, useResource } from '../../api/client';
import type { Collection, Evidence } from '../../api/types';
import type { Story, StoryRequest, WorkbenchProps } from '../../api/workbench';
import { Badge, date, Empty, ErrorBox, Loading } from '../../components/UI';
import { DeskHeading, displayValue, errorMessage } from './Common';
export function StoryDesk({ inv, refresh, onEvidence }: WorkbenchProps) {
  const [cursor, setCursor] = useState<string | null>(null),
    [previous, setPrevious] = useState<(string | null)[]>([]),
    [redact, setRedact] = useState(true),
    [story, setStory] = useState<Story | null>(null),
    [storyRequest, setStoryRequest] = useState<StoryRequest | null>(null),
    [step, setStep] = useState(0),
    [busy, setBusy] = useState(''),
    [error, setError] = useState(''),
    [focus, setFocus] = useState(false);
  const [selected, setSelected] = useCaseStoredState<string[]>(inv.id, 'story-selection', [], evidenceIds);
  const { pinnedEvidence } = useCaseWorkspace();
  const records = useResource<Collection<Evidence>>(
    `${casePath(inv.id)}/evidence?${query({ limit: 25, cursor })}`,
    refresh,
  );
  function invalidate() {
    setStory(null);
    setStoryRequest(null);
    setError('');
  }
  function choose(ids: string[]) {
    invalidate();
    setSelected(ids);
  }
  function toggle(id: string) {
    invalidate();
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((value) => value !== id) : prev.length < 12 ? [...prev, id] : prev,
    );
  }
  async function preview() {
    setBusy('preview');
    setError('');
    setStory(null);
    setStoryRequest(null);
    const payload = { evidence_ids: [...selected], redact };
    try {
      const value = await api.post<Story>(`${casePath(inv.id)}/story/preview`, payload);
      setStory(value);
      setStoryRequest(payload);
      setStep(0);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy('');
    }
  }
  async function download() {
    if (!storyRequest || !story?.preview_id) return;
    setBusy('export');
    setError('');
    try {
      const response = await fetch(`/api${casePath(inv.id)}/story/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...storyRequest, preview_id: story.preview_id }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error?.message || 'Sunum indirilemedi.');
      }
      const blob = await response.blob(),
        url = URL.createObjectURL(blob),
        link = document.createElement('a');
      link.href = url;
      link.download = `belgu-sunum-${storyRequest.redact ? 'maskeli' : 'acik'}.html`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy('');
    }
  }
  const current = story?.steps[step];
  return (
    <>
      <DeskHeading eyebrow="KANITI BİR ANLATIYA DÖNÜŞTÜRÜN" title="Seçin. Gözden geçirin. Paylaşın.">
        En fazla 12 kanıttan yerel bir sunum oluşturun. Önce aynı içerikle önizleyin, ardından tek HTML
        dosyası olarak indirin.
      </DeskHeading>
      <div className="desk-story-layout">
        <section className="panel desk-story-picker">
          <header>
            <div>
              <h3>Kanıt kartları</h3>
              <p>
                {selected.length
                  ? `${selected.length} / 12 kart seçildi`
                  : 'Seçim yapmazsanız en fazla 6 ilgili kayıt kullanılır.'}
              </p>
            </div>
            <Badge>{selected.length}/12</Badge>
          </header>
          <button
            className="button story-board-import"
            disabled={!!busy || !pinnedEvidence.length}
            onClick={() => choose([...pinnedEvidence])}
          >
            <Pin size={14} /> Panodan aktar <span className="count">{pinnedEvidence.length}</span>
          </button>
          {selected.length > 0 && (
            <button
              className="text-button desk-clear-selection"
              disabled={!!busy}
              onClick={() => {
                setSelected([]);
                invalidate();
              }}
            >
              Seçimi temizle
            </button>
          )}
          {records.error ? (
            <ErrorBox message={records.error} onRetry={records.reload} />
          ) : records.loading ? (
            <Loading label="Kanıt kartları yükleniyor" />
          ) : !records.data?.items.length ? (
            <Empty title="Sunum için kanıt bulunmuyor">
              Keşif veya görsel yakalama sonrasında kayıtlar burada seçilebilir.
            </Empty>
          ) : (
            <>
              <div className="desk-story-records">
                {records.data.items.map((record) => (
                  <article key={record.id} className={selected.includes(record.id) ? 'selected' : ''}>
                    <label>
                      <input
                        type="checkbox"
                        aria-label={`Kanıtı seç: ${record.provider} · ${record.subject.value}`}
                        checked={selected.includes(record.id)}
                        disabled={!!busy || (selected.length >= 12 && !selected.includes(record.id))}
                        onChange={() => toggle(record.id)}
                      />
                      <span>
                        <span className="desk-record-provider">{record.provider}</span>
                        <strong>{record.subject.value}</strong>
                        <small>{date(record.observed_at || record.retrieved_at, true)}</small>
                      </span>
                    </label>
                    <button
                      className="icon-button"
                      title="Kaynak kaydı"
                      aria-label={`${record.provider} kaynak kaydını aç`}
                      onClick={() => onEvidence(record.id)}
                    >
                      <Eye size={14} />
                    </button>
                  </article>
                ))}
              </div>
              <div className="desk-record-pagination">
                <span>
                  {records.data.total_unique} kayıt · Sayfa {previous.length + 1}
                </span>
                <button
                  className="icon-button"
                  aria-label="Önceki kanıt sayfası"
                  disabled={!previous.length || !!busy}
                  onClick={() => {
                    setCursor(previous.at(-1) ?? null);
                    setPrevious((prev) => prev.slice(0, -1));
                  }}
                >
                  <ArrowLeft size={14} />
                </button>
                <button
                  className="icon-button"
                  aria-label="Sonraki kanıt sayfası"
                  disabled={!records.data.next_cursor || !!busy}
                  onClick={() => {
                    setPrevious((prev) => [...prev, cursor]);
                    setCursor(records.data!.next_cursor);
                  }}
                >
                  <ArrowRight size={14} />
                </button>
              </div>
            </>
          )}
        </section>
        <div className="desk-story-main">
          {selected.length > 0 && (
            <section className="panel story-selection-order" role="region" aria-label="Sunum sırası">
              <header>
                <div>
                  <span className="eyebrow accent">SUNUM SIRASI</span>
                  <h3>Önce hangi dayanak?</h3>
                </div>
                <span className="small muted">Sürükleyin veya okları kullanın</span>
              </header>
              <EvidenceOrderList
                investigationId={inv.id}
                ids={selected}
                onChange={choose}
                onEvidence={onEvidence}
                disabled={!!busy}
              />
            </section>
          )}
          <section className="panel desk-story-settings">
            <div className="desk-redaction">
              <ShieldCheck size={21} />
              <label>
                <strong>Kimlikleri maskele</strong>
                <span>
                  Alan adları, IP’ler, kaynak adresleri, özgün metinler ve görüntüler dosyaya alınmaz.
                </span>
              </label>
              <input
                type="checkbox"
                aria-label="Kimlikleri maskele"
                checked={redact}
                disabled={!!busy}
                onChange={(e) => {
                  setRedact(e.target.checked);
                  invalidate();
                }}
              />
            </div>
            {!redact && (
              <p className="callout amber">
                Açık sunum seçili kanıtların adreslerini, özgün metnini ve varsa görüntülerini içerir.
              </p>
            )}
            <footer>
              <span className="small muted">
                <LockKeyhole size={12} />
                Yalnızca bu cihazda hazırlanır
              </span>
              <button
                className="button primary"
                disabled={!!busy || !records.data?.total_unique}
                onClick={preview}
              >
                <Eye size={14} />
                {busy === 'preview' ? 'Hazırlanıyor…' : 'Önizlemeyi oluştur'}
              </button>
            </footer>
          </section>
          {error && <ErrorBox message={error} />}
          {busy === 'preview' ? (
            <Loading label="Sunum önizlemesi hazırlanıyor" />
          ) : story && current ? (
            <section className="panel desk-story-preview" aria-label="Sunum önizlemesi">
              <header>
                <span className="eyebrow">BELGÜ / İNCELEME SUNUMU</span>
                <Badge tone={story.redacted ? 'accent' : 'amber'}>
                  {story.redacted ? 'Maskelenmiş' : 'Açık içerik'}
                </Badge>
              </header>
              <div className="desk-story-slide">
                <span className="desk-slide-number">{String(step + 1).padStart(2, '0')}</span>
                <span className="eyebrow accent">{current.subtitle}</span>
                <h2>{current.title}</h2>
                <p>{current.body}</p>
                {current.image_url && !story.redacted && (
                  <img className="desk-story-image" src={current.image_url} alt="Seçili kanıtın görüntüsü" />
                )}
                <dl>
                  {current.fields.map((field, i) => (
                    <div key={i}>
                      <dt>{field.label}</dt>
                      <dd>{displayValue(field.value)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <footer>
                <span>
                  {step + 1} / {story.steps.length} kart
                </span>
                <div>
                  <button
                    className="icon-button"
                    aria-label="Önceki kart"
                    disabled={step === 0}
                    onClick={() => setStep((s) => s - 1)}
                  >
                    <ArrowLeft size={16} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label="Sonraki kart"
                    disabled={step >= story.steps.length - 1}
                    onClick={() => setStep((s) => s + 1)}
                  >
                    <ArrowRight size={16} />
                  </button>
                </div>
              </footer>
            </section>
          ) : (
            <div className="panel desk-story-placeholder">
              <Empty
                title={story ? 'Sunumda gösterilecek kart yok' : 'Anlatınız burada şekillenecek'}
                icon={<Presentation size={34} />}
              >
                {story
                  ? 'Farklı kanıtlar seçerek yeniden önizleyin.'
                  : 'Kanıtları ve maskeleme seçimini gözden geçirip önizlemeyi oluşturun.'}
              </Empty>
            </div>
          )}
          {story?.redacted && !!story.steps.length && (
            <button
              className="button presentation-launch"
              disabled={!!busy || !story.preview_id}
              onClick={() => setFocus(true)}
            >
              <Maximize2 size={16} /> Maskeli sunumu aç
            </button>
          )}
          <div className="desk-story-download">
            <span>
              <Check size={14} />
              Çevrimdışı açılır · Önceki / sonraki · Yazdırılabilir
            </span>
            <button
              className="button"
              disabled={!story?.steps.length || !story.preview_id || !!busy}
              onClick={download}
            >
              <Download size={15} />
              {busy === 'export' ? 'İndiriliyor…' : 'HTML sunumunu indir'}
            </button>
          </div>
        </div>
      </div>
      {focus && story?.redacted && <MaskedPresentation story={story} onClose={() => setFocus(false)} />}
    </>
  );
}

function MaskedPresentation({ story, onClose }: { story: Story; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const [slide, setSlide] = useState(0);
  useEffect(() => {
    const prior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.classList.add('belgu-presentation-focus');
    dialog.current?.showModal();
    close.current?.focus();
    return () => {
      document.body.classList.remove('belgu-presentation-focus');
      dialog.current?.close();
      prior?.focus({ preventScroll: true });
    };
  }, []);
  const current = story.steps[slide];
  return createPortal(
    <dialog
      ref={dialog}
      className="masked-presentation"
      aria-label="Maskeli sunum"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === 'ArrowRight') {
          event.preventDefault();
          setSlide((value) => Math.min(story.steps.length - 1, value + 1));
        }
        if (event.key === 'ArrowLeft') {
          event.preventDefault();
          setSlide((value) => Math.max(0, value - 1));
        }
      }}
    >
      <header>
        <span className="presentation-brand">
          belgü<span> / İNCELEME SUNUMU</span>
        </span>
        <div>
          <Badge tone="accent">
            <LockKeyhole size={12} /> Maskelenmiş
          </Badge>
          <button ref={close} className="icon-button" aria-label="Sunumu kapat" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
      </header>
      <article className="masked-presentation-slide" aria-live="polite">
        <span className="presentation-index">{String(slide + 1).padStart(2, '0')}</span>
        <span className="eyebrow accent">{current.subtitle}</span>
        <h1>{current.title}</h1>
        <p>{current.body}</p>
        {!!current.fields.length && (
          <dl>
            {current.fields.map((field, index) => (
              <div key={index}>
                <dt>{field.label}</dt>
                <dd>{displayValue(field.value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </article>
      <footer>
        <span>
          {slide + 1} / {story.steps.length} kart
        </span>
        <div>
          <button
            className="button"
            aria-label="Önceki kart"
            disabled={!slide}
            onClick={() => setSlide((value) => value - 1)}
          >
            <ArrowLeft size={18} /> Önceki
          </button>
          <button
            className="button primary"
            aria-label="Sonraki kart"
            disabled={slide >= story.steps.length - 1}
            onClick={() => setSlide((value) => value + 1)}
          >
            Sonraki <ArrowRight size={18} />
          </button>
        </div>
      </footer>
    </dialog>,
    document.body,
  );
}
