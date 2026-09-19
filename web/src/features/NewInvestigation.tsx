import { useState, type FormEvent } from 'react';
import { ArrowRight, Building2, Link2, Plus } from 'lucide-react';
import { api, casePath, useResource } from '../api/client';
import type { Brand, Collection, Investigation } from '../api/types';
import { ErrorBox, Modal, Success } from '../components/UI';
export function NewInvestigation({ onClose }: { onClose: () => void }) {
  const brands = useResource<Collection<Brand>>('/brands');
  const [brandId, setBrandId] = useState(''),
    [newBrand, setNewBrand] = useState(false),
    [brandName, setBrandName] = useState(''),
    [domains, setDomains] = useState(''),
    [title, setTitle] = useState(''),
    [urls, setUrls] = useState(''),
    [source, setSource] = useState('customer_report'),
    [note, setNote] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [saved, setSaved] = useState<Investigation | null>(null),
    [failures, setFailures] = useState<{ url: string; message: string }[]>([]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      let selected = brandId || brands.data?.items[0]?.id;
      if (newBrand && !saved) {
        const brand = await api.post<Brand>('/brands', {
          name: brandName,
          official_domains: domains.split(/[\s,]+/).filter(Boolean),
        });
        selected = brand.id;
        setBrandId(brand.id);
        setNewBrand(false);
        brands.reload();
      }
      if (!selected && !saved) throw new Error('Lütfen bir marka ekleyin.');
      const inv = saved || (await api.post<Investigation>('/investigations', { brand_id: selected, title }));
      setSaved(inv);
      const remaining: typeof failures = [];
      for (const url of urls
        .split('\n')
        .map((v) => v.trim())
        .filter(Boolean)) {
        try {
          await api.post(`${casePath(inv.id)}/submissions`, { value: url, source, note });
        } catch (err) {
          remaining.push({ url, message: err instanceof Error ? err.message : String(err) });
        }
      }
      setFailures(remaining);
      if (remaining.length) {
        setUrls(remaining.map((v) => v.url).join('\n'));
        setError(
          'İnceleme oluşturuldu. Aşağıdaki URL’ler kaydedilemedi; düzelterek yeniden deneyebilirsiniz.',
        );
      } else {
        location.hash = `/investigations/${inv.id}`;
        onClose();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Yeni inceleme" onClose={onClose} wide>
      <form onSubmit={submit}>
        <p className="form-intro">
          Şüpheli bir adresle başlayın. Bildirimin kaynağı ve tam URL, inceleme boyunca korunur.
        </p>
        <div className="form-section-label">
          <Building2 size={16} />
          01 <span>İnceleme bağlamı</span>
        </div>
        <label>
          İnceleme başlığı
          <input
            autoFocus
            required
            disabled={!!saved}
            placeholder="Örn. Marka adına açılan şüpheli giriş sayfaları"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <div className="field-row">
          <label>
            İlgili marka
            {!newBrand ? (
              <select
                disabled={!!saved}
                value={brandId || brands.data?.items[0]?.id || ''}
                onChange={(e) => setBrandId(e.target.value)}
              >
                <option value="" disabled>
                  Marka seçin
                </option>
                {brands.data?.items.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                required
                placeholder="Marka adı"
                value={brandName}
                onChange={(e) => setBrandName(e.target.value)}
              />
            )}
          </label>
          {!saved && (
            <button type="button" className="button" onClick={() => setNewBrand(!newBrand)}>
              <Plus size={15} />
              {newBrand ? 'Mevcut marka' : 'Marka ekle'}
            </button>
          )}
        </div>
        {newBrand && (
          <label>
            Resmî alan adları
            <input
              placeholder="marka.test, marka.com.tr"
              value={domains}
              onChange={(e) => setDomains(e.target.value)}
            />
            <small>Birden fazla alan adını virgülle ayırın.</small>
          </label>
        )}
        <div className="form-section-label">
          <Link2 size={16} />
          02 <span>Başlangıç bulguları</span>
        </div>
        <label>
          Tam URL veya alan adı
          <textarea
            required
            rows={3}
            className="mono"
            placeholder={'https://supheli-adres.test/oturum?ref=bildirim\nHer satıra bir adres'}
            value={urls}
            onChange={(e) => setUrls(e.target.value)}
          />
          <small>Yol ve sorgu parametreleri özgün bildirimde saklanır.</small>
        </label>
        <label>
          Bildirim kaynağı
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="customer_report">Müşteri bildirimi</option>
            <option value="analyst_discovery">Analist keşfi</option>
            <option value="automated_discovery">Otomatik keşif</option>
          </select>
        </label>
        <label>
          Analist notu <span className="muted">· isteğe bağlı</span>
          <textarea
            rows={2}
            placeholder="Bildirimin bağlamı veya ilk gözleminiz…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        {error && <ErrorBox message={error} />}{' '}
        {failures.map((f) => (
          <div className="failed-row" key={f.url}>
            <code>{f.url}</code>
            <span>{f.message}</span>
          </div>
        ))}
        <footer className="modal-footer">
          {saved ? (
            <a className="text-button" href={`#/investigations/${saved.id}`} onClick={onClose}>
              İncelemeye geç
            </a>
          ) : (
            <button type="button" className="button" onClick={onClose}>
              Vazgeç
            </button>
          )}
          <button className="button primary" disabled={busy}>
            {busy ? 'Kaydediliyor…' : saved ? 'Başarısız URL’leri yeniden kaydet' : 'İncelemeyi oluştur'}
            <ArrowRight size={16} />
          </button>
        </footer>
      </form>
    </Modal>
  );
}
export function Brands() {
  const { data, error, reload } = useResource<Collection<Brand>>('/brands');
  const [adding, setAdding] = useState(false),
    [name, setName] = useState(''),
    [domains, setDomains] = useState(''),
    [err, setErr] = useState(''),
    [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post('/brands', { name, official_domains: domains.split(/[\s,]+/).filter(Boolean) });
      setAdding(false);
      setName('');
      setDomains('');
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ARAŞTIRMA BAĞLAMI</span>
          <h1>Markalar</h1>
          <p>İncelemeleriniz için resmî marka referansları.</p>
        </div>
        <button className="button primary" onClick={() => setAdding(true)}>
          <Plus size={16} />
          Marka ekle
        </button>
      </div>
      {error && <ErrorBox message={error} />}
      <div className="brand-grid">
        {data?.items.map((b) => (
          <article className="panel brand-card" key={b.id}>
            <span className="brand-avatar">{b.name.slice(0, 1)}</span>
            <h2>{b.name}</h2>
            <span className="eyebrow">RESMÎ ALAN ADLARI</span>
            <div className="domain-list">
              {b.official_domains.length ? (
                b.official_domains.map((d) => <code key={d}>{d}</code>)
              ) : (
                <p className="muted">Referans alan adı eklenmemiş.</p>
              )}
            </div>
          </article>
        ))}
      </div>
      {adding && (
        <Modal title="Marka ekle" onClose={() => setAdding(false)}>
          <form onSubmit={save}>
            <label>
              Marka adı
              <input autoFocus required value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              Resmî alan adları
              <textarea
                rows={3}
                placeholder="marka.test"
                value={domains}
                onChange={(e) => setDomains(e.target.value)}
              />
              <small>Virgül veya yeni satırla ayırın.</small>
            </label>
            {err && <ErrorBox message={err} />}
            <footer className="modal-footer">
              <button type="button" className="button" onClick={() => setAdding(false)}>
                Vazgeç
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? 'Kaydediliyor…' : 'Markayı kaydet'}
              </button>
            </footer>
          </form>
        </Modal>
      )}
    </>
  );
}
