import { ArrowUpRight, BookOpen, Maximize2, ImageOff } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Modal } from '../../components/UI';
export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(displayValue).join(', ');
  if (typeof value === 'object' && 'value' in value) return displayValue(value.value);
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}
export function DeskHeading({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="desk-heading">
      <div>
        <span className="eyebrow accent">{eyebrow}</span>
        <h2>{title}</h2>
        <p>{children}</p>
      </div>
      {action}
    </header>
  );
}
export function EvidenceLinks({ ids, onEvidence }: { ids: string[]; onEvidence: (id: string) => void }) {
  return (
    <div className="desk-evidence-links">
      {[...new Set(ids)].map((id, index) => (
        <button
          className="text-button"
          key={id}
          title={id}
          aria-label={`Kaynak kanıtı ${index + 1}`}
          onClick={() => onEvidence(id)}
        >
          <BookOpen size={12} />
          Kanıt {index + 1}
          <ArrowUpRight size={11} />
        </button>
      ))}
    </div>
  );
}
export function Limitations({ items }: { items: string[] }) {
  return items.length ? (
    <ul className="desk-limitations">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  ) : null;
}
export function EvidenceImage({ src, alt }: { src: string; alt: string }) {
  const [full, setFull] = useState(false),
    [failed, setFailed] = useState(false);
  if (failed)
    return (
      <div className="desk-image-error">
        <ImageOff size={24} />
        <p>Görsel yüklenemedi.</p>
        <button className="text-button" onClick={() => setFailed(false)}>
          Yeniden dene
        </button>
      </div>
    );
  return (
    <>
      <button
        className="desk-image-button"
        aria-label={`${alt} görselini büyüt`}
        onClick={() => setFull(true)}
      >
        <img src={src} alt={alt} onError={() => setFailed(true)} />
        <span>
          <Maximize2 size={13} />
          Büyüt
        </span>
      </button>
      {full && (
        <Modal title={alt} wide onClose={() => setFull(false)}>
          <img className="desk-full-image" src={src} alt={`${alt}, tam boyut`} />
        </Modal>
      )}
    </>
  );
}
