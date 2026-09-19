import { useEffect, useRef, type ReactNode } from 'react';
import { AlertCircle, ArrowRight, Check, ChevronLeft, ChevronRight, LoaderCircle, X } from 'lucide-react';
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon && <span className="empty-icon">{icon}</span>}
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}
export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          Yeniden dene <ArrowRight size={14} />
        </button>
      )}
    </div>
  );
}
export function Loading({ label = 'Veriler yükleniyor' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} />
      {label}
    </div>
  );
}
export function Pagination({
  page,
  next,
  onPrev,
  onNext,
  total,
  count,
  label = 'kayıt',
}: {
  page: number;
  next: boolean;
  onPrev: () => void;
  onNext: () => void;
  total: number;
  count: number;
  label?: string;
}) {
  return (
    <div className="pagination">
      <span>
        {total ? `${page * 25 + 1}–${page * 25 + count}` : '0'} / {total.toLocaleString('tr-TR')} {label}
      </span>
      <div>
        <button className="icon-button" aria-label="Önceki sayfa" disabled={!page} onClick={onPrev}>
          <ChevronLeft size={16} />
        </button>
        <span>{page + 1}</span>
        <button className="icon-button" aria-label="Sonraki sayfa" disabled={!next} onClick={onNext}>
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    el?.showModal();
    return () => el?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? 'modal wide' : 'modal'}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <header>
        <div>
          <span className="eyebrow">BELGÜ ÇALIŞMA ALANI</span>
          <h2>{title}</h2>
        </div>
        <button className="icon-button" aria-label="Kapat" onClick={onClose}>
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  );
}
export function Success({ children }: { children: ReactNode }) {
  return (
    <div className="success" role="status">
      <Check size={16} />
      {children}
    </div>
  );
}
export function date(value?: string | null, full = false) {
  if (!value) return '—';
  const d = new Date(
    /^\d{4}-\d{2}-\d{2}T/.test(value) && !/(Z|[+-]\d{2}:\d{2})$/.test(value) ? `${value}Z` : value,
  );
  return Number.isNaN(d.getTime())
    ? value
    : new Intl.DateTimeFormat('tr-TR', {
        day: '2-digit',
        month: 'short',
        ...(full ? { year: 'numeric', hour: '2-digit', minute: '2-digit' } : {}),
      }).format(d);
}
export const sourceLabel = (v?: string | null) =>
  ({
    customer_report: 'Müşteri bildirimi',
    analyst_discovery: 'Analist keşfi',
    automated_discovery: 'Otomatik keşif',
    analyst: 'Analist keşfi',
    automatic: 'Otomatik keşif',
  })[v || ''] ||
  v ||
  'Belirtilmedi';
export const decisionLabel = (v: string) =>
  ({
    unreviewed: 'İncelenmedi',
    confirmed_phishing: 'Oltalama doğrulandı',
    benign: 'Zararsız',
    needs_review: 'İnceleme gerekli',
  })[v] || v;
export const kindLabel = (v: string) =>
  ({
    domain: 'Alan adı',
    ip: 'IP adresi',
    url: 'URL',
    js_sha256: 'JS özeti',
    js_hash: 'JS özeti',
    cert: 'Sertifika',
    certificate: 'Sertifika gözlemi',
    loads_script: 'JS içerik eşleşmesi',
    resolves_to: 'DNS çözümlemesi',
    historically_observed_on: 'Geçmiş DNS kaydı',
    cert_sha256: 'Sertifika',
    observed_ip: 'Gözlenen IP',
  })[v] || v;
