import { useEffect, useState } from 'react';
import {
  Check,
  CheckCircle2,
  Cloud,
  Cpu,
  ExternalLink,
  KeyRound,
  LoaderCircle,
  Network,
  PlugZap,
  Save,
  Settings2,
  XCircle,
} from 'lucide-react';
import { api, useResource } from '../api/client';
import type { components } from '../api/generated';
import { Badge, ErrorBox, Loading } from '../components/UI';
import '../styles/settings.css';

type Schema = components['schemas'];
type View = Schema['IntegrationView'];
type Patch = Schema['IntegrationPatch'];
type LlmDraft = Schema['LlmDraft'];
type SourceDraft = Schema['SourceDraft'];
type Result = Schema['ConnectionResult'];
type Provider = View['active_llm'];
const providers: Provider[] = ['local', 'anthropic', 'openai', 'gemini', 'openrouter'];
const initials = { local: 'API', anthropic: 'C', openai: 'O', gemini: 'G', openrouter: 'OR' };

function ConnectionStatus({ result }: { result?: Result }) {
  if (!result) return null;
  return (
    <div
      className={`connection-result ${result.status}`}
      role={result.status === 'error' ? 'alert' : 'status'}
    >
      {result.status === 'ok' ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
      <span>
        {result.message}
        {result.elapsed_ms != null && <small> · {(result.elapsed_ms / 1000).toFixed(1)} sn</small>}
      </span>
    </div>
  );
}

function SecretField({
  label,
  value,
  configured,
  clearing,
  onChange,
  onClear,
}: {
  label: string;
  value: string;
  configured: boolean;
  clearing: boolean;
  onChange: (value: string) => void;
  onClear: () => void;
}) {
  return (
    <div className="settings-secret">
      <label>
        <span>
          {label}
          <small>
            {clearing ? 'Silinecek' : value ? 'Yeni anahtar' : configured ? 'Kaydedilmiş' : 'Eklenmemiş'}
          </small>
        </span>
        <div className="secret-input">
          <KeyRound size={15} />
          <input
            type="password"
            value={value}
            autoComplete="new-password"
            spellCheck={false}
            placeholder={
              clearing
                ? 'Kaydedince kaldırılacak'
                : configured
                  ? 'Değiştirmek için yeni anahtar girin'
                  : 'API anahtarını girin'
            }
            onChange={(e) => onChange(e.target.value)}
          />
        </div>
      </label>
      {(configured || clearing) && (
        <button type="button" className="text-button" onClick={onClear}>
          {clearing ? 'Silmeyi geri al' : 'Anahtarı kaldır'}
        </button>
      )}
    </div>
  );
}

export default function SettingsPage({ onSaved }: { onSaved: () => void }) {
  const resource = useResource<View>('/settings');
  const [saved, setSaved] = useState<View | null>(null);
  const [draft, setDraft] = useState<Patch>({});
  const [selected, setSelected] = useState<Provider>('local');
  const [tab, setTab] = useState<'llm' | 'sources'>('llm');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [results, setResults] = useState<Record<string, Result>>({});
  const [models, setModels] = useState<Record<string, Schema['ModelInfo'][]>>({});
  useEffect(() => {
    if (resource.data) {
      setSaved(resource.data);
      setSelected(resource.data.active_llm);
    }
  }, [resource.data]);
  const dirty = Object.keys(draft).length > 0;
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  if (resource.error) return <ErrorBox message={resource.error} onRetry={resource.reload} />;
  if (!saved) return <Loading label="Bağlantı ayarları yükleniyor" />;
  const locked = saved.read_only || !!busy;
  const active = draft.active_llm || saved.active_llm;
  const llm = { ...saved.llm[selected], ...draft.llm?.[selected] };
  const keyDraft = draft.llm?.[selected];
  const readyKey =
    selected === 'local' || !!keyDraft?.api_key || (llm.key_configured && !keyDraft?.clear_key);
  const clearFeedback = (key: string) => {
    setNotice('');
    setError('');
    setResults((current) => {
      const copy = { ...current };
      delete copy[key];
      return copy;
    });
  };
  function editLlm(value: LlmDraft) {
    clearFeedback('llm:' + selected);
    if ('api_key' in value || 'base_url' in value || 'backend' in value || 'clear_key' in value)
      setModels((current) => ({ ...current, [selected]: [] }));
    setDraft((current) => ({
      ...current,
      llm: { ...current.llm, [selected]: { ...current.llm?.[selected], ...value } },
    }));
  }
  function editSource(name: string, value: SourceDraft) {
    clearFeedback(name);
    setDraft((current) => ({
      ...current,
      sources: { ...current.sources, [name]: { ...current.sources?.[name], ...value } },
    }));
  }
  async function save() {
    setBusy('save');
    setError('');
    setNotice('');
    try {
      const response = await api.patch<View>('/settings', draft);
      setSaved(response);
      setDraft({});
      setNotice('Ayarlar kaydedildi. Yeni işlemler bu bağlantılarla çalışacak.');
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy('');
    }
  }
  async function testModel(list = false) {
    const key = 'llm:' + selected;
    setBusy(list ? 'models' : key);
    setError('');
    try {
      const body = { provider: selected, settings: draft.llm?.[selected] || {} };
      if (list) {
        const response = await api.post<Schema['AvailableModels']>('/settings/llm/models', body);
        if (response.status === 'error')
          setResults((current) => ({
            ...current,
            [key]: { status: 'error', message: response.message || 'Model listesi alınamadı.' },
          }));
        else {
          setModels((current) => ({ ...current, [selected]: response.items || [] }));
          setResults((current) => ({
            ...current,
            [key]: {
              status: 'ok',
              message: `${response.items?.length || 0} model bulundu. Listeden seçebilir veya model kimliğini yazabilirsiniz.`,
            },
          }));
        }
      } else {
        const response = await api.post<Result>('/settings/llm/test', body);
        setResults((current) => ({ ...current, [key]: response }));
      }
    } catch (e) {
      setResults((current) => ({ ...current, [key]: { status: 'error', message: (e as Error).message } }));
    } finally {
      setBusy('');
    }
  }
  async function testSource(name: string) {
    setBusy(name);
    setError('');
    try {
      const response = await api.post<Result>('/settings/sources/test', {
        provider: name,
        settings: draft.sources?.[name] || {},
      });
      setResults((current) => ({ ...current, [name]: response }));
    } catch (e) {
      setResults((current) => ({ ...current, [name]: { status: 'error', message: (e as Error).message } }));
    } finally {
      setBusy('');
    }
  }
  return (
    <div className="settings-page">
      <header className="settings-heading">
        <div>
          <span className="eyebrow accent">BELGÜ BAĞLANTILARI</span>
          <h1>Ayarlar</h1>
          <p>Modelinizi ve araştırma kaynaklarınızı bağlayın.</p>
        </div>
        <span className="settings-heading-icon">
          <Settings2 size={26} />
        </span>
      </header>
      <div className="settings-summary">
        <span>
          <Cpu size={16} /> Aktif model <strong>{saved.llm[saved.active_llm].label}</strong>
        </span>
        <span>
          <Network size={16} />
          <strong>{Object.values(saved.sources).filter((s) => s.enabled).length}</strong> kaynak açık
        </span>
      </div>
      {saved.read_only && (
        <p className="settings-demo">
          <Badge tone="demo">Kayıtlı demo</Badge> Bu ortam bağlantı ayarlarını önizler. Anahtar kaydetmez veya
          servis çağrısı yapmaz.
        </p>
      )}
      <div className="settings-tabs" role="tablist" aria-label="Ayar kategorileri">
        <button
          role="tab"
          id="llm-tab"
          aria-controls="llm-panel"
          aria-selected={tab === 'llm'}
          onClick={() => setTab('llm')}
        >
          <Cpu size={17} /> Yapay zekâ
        </button>
        <button
          role="tab"
          id="sources-tab"
          aria-controls="sources-panel"
          aria-selected={tab === 'sources'}
          onClick={() => setTab('sources')}
        >
          <Network size={17} /> Keşif kaynakları
        </button>
      </div>
      {tab === 'llm' ? (
        <section role="tabpanel" id="llm-panel" aria-labelledby="llm-tab" className="settings-llm">
          <div className="llm-provider-list" role="group" aria-label="Model sağlayıcısı">
            {providers.map((provider) => (
              <button
                key={provider}
                disabled={!!busy}
                aria-pressed={selected === provider}
                className={`llm-provider ${selected === provider ? 'selected' : ''}`}
                onClick={() => {
                  setSelected(provider);
                  setNotice('');
                  setError('');
                }}
              >
                <span className={`provider-monogram ${provider}`}>{initials[provider]}</span>
                <span>
                  <strong>{saved.llm[provider].label}</strong>
                  <small>
                    {provider === 'local'
                      ? 'Kendi model sunucunuz'
                      : provider === 'openrouter'
                        ? 'Tek API, farklı modeller'
                        : 'Bulut API'}
                  </small>
                </span>
                {active === provider && <Check size={16} aria-label="Aktif sağlayıcı" />}
              </button>
            ))}
          </div>
          <div className="settings-panel">
            <header className="settings-panel-heading">
              <div>
                <span className="eyebrow">MODEL BAĞLANTISI</span>
                <h2>{saved.llm[selected].label}</h2>
              </div>
              <a href={saved.llm[selected].docs_url} target="_blank" rel="noreferrer">
                Dokümantasyon <ExternalLink size={13} />
              </a>
            </header>
            <fieldset disabled={locked} className="settings-fields">
              <legend className="sr-only">{saved.llm[selected].label} bağlantı bilgileri</legend>
              {selected === 'local' ? (
                <div className="settings-field-row">
                  <label>
                    API türü
                    <select
                      value={llm.backend || 'openai_compatible'}
                      onChange={(e) => editLlm({ backend: e.target.value as LlmDraft['backend'] })}
                    >
                      <option value="sglang">SGLang</option>
                      <option value="llama.cpp">llama.cpp</option>
                      <option value="openai_compatible">OpenAI uyumlu API</option>
                    </select>
                  </label>
                  <label>
                    API adresi
                    <input
                      type="url"
                      value={llm.base_url || ''}
                      spellCheck={false}
                      placeholder="http://127.0.0.1:30000/v1"
                      onChange={(e) => editLlm({ base_url: e.target.value })}
                    />
                  </label>
                </div>
              ) : (
                <div className="settings-endpoint">
                  <Cloud size={15} />
                  <code>{llm.base_url}</code>
                </div>
              )}
              {selected === 'local' && (
                <p className="settings-hint">
                  LM Studio, Ollama ve vLLM için “OpenAI uyumlu API” seçin. Adres, modelin API kökü olmalı.
                </p>
              )}
              <SecretField
                label={selected === 'local' ? 'API anahtarı (isteğe bağlı)' : 'API anahtarı'}
                value={keyDraft?.api_key || ''}
                configured={llm.key_configured}
                clearing={!!keyDraft?.clear_key}
                onChange={(value) => editLlm({ api_key: value, clear_key: false })}
                onClear={() => editLlm({ clear_key: !keyDraft?.clear_key, api_key: '' })}
              />
              <div className="settings-model-row">
                <label>
                  Model kimliği
                  <input
                    list={`models-${selected}`}
                    value={llm.model_id || ''}
                    spellCheck={false}
                    placeholder="Model kimliğini yazın veya listeden seçin"
                    onChange={(e) => editLlm({ model_id: e.target.value })}
                  />
                  <datalist id={`models-${selected}`}>
                    {(models[selected] || []).map((m) => (
                      <option key={m.id} value={m.id} />
                    ))}
                  </datalist>
                </label>
                <button
                  type="button"
                  className="button secondary"
                  disabled={!readyKey || locked}
                  onClick={() => testModel(true)}
                >
                  {busy === 'models' ? <LoaderCircle className="spin" size={15} /> : <Network size={15} />}{' '}
                  Modelleri getir
                </button>
              </div>
              <div className="settings-field-row secondary-fields">
                <label>
                  Yanıt bekleme süresi (sn)
                  <input
                    type="number"
                    min={1}
                    max={3600}
                    value={llm.timeout_seconds ?? 300}
                    onChange={(e) => editLlm({ timeout_seconds: Number(e.target.value) })}
                  />
                </label>
                <label className="activate-provider">
                  <input
                    type="checkbox"
                    checked={active === selected}
                    onChange={(e) => {
                      if (e.target.checked) {
                        clearFeedback('');
                        setDraft((current) => ({ ...current, active_llm: selected }));
                      }
                    }}
                    disabled={locked || active === selected}
                  />
                  <span>Analizlerde bu sağlayıcıyı kullan</span>
                </label>
              </div>
              {selected !== 'local' && (
                <p className="settings-hint">
                  Bu sağlayıcıyı etkinleştirdiğinizde analiz ve yardımcı sorularındaki metinler seçtiğiniz
                  bulut servisine gönderilir.
                </p>
              )}
              <div className="settings-test-row">
                <button
                  type="button"
                  className="button secondary"
                  disabled={!readyKey || !llm.model_id || locked}
                  onClick={() => testModel()}
                >
                  {busy === 'llm:' + selected ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <PlugZap size={15} />
                  )}{' '}
                  Bağlantıyı dene
                </button>
                <span>Kısa bir JSON yanıtı istenir; inceleme verisi gönderilmez.</span>
              </div>
            </fieldset>
            <ConnectionStatus result={results['llm:' + selected]} />
          </div>
        </section>
      ) : (
        <section
          role="tabpanel"
          id="sources-panel"
          aria-labelledby="sources-tab"
          className="settings-sources"
        >
          {(['reverse', 'intel', 'public', 'local'] as const).map((group) => (
            <section className="settings-source-group" key={group}>
              <h2>
                {
                  {
                    reverse: 'Reverse IP ve pasif DNS',
                    intel: 'Tehdit istihbaratı',
                    public: 'Herkese açık kaynaklar',
                    local: 'Dosyadan aktarım',
                  }[group]
                }
              </h2>
              <div className="settings-source-grid">
                {Object.entries(saved.sources)
                  .filter(([, value]) => value.group === group)
                  .map(([name, original]) => {
                    const source = { ...original, ...draft.sources?.[name] };
                    const sourceDraft = draft.sources?.[name];
                    return (
                      <article
                        className={`settings-source-card ${source.enabled ? '' : 'disabled-source'}`}
                        key={name}
                        aria-label={source.label}
                      >
                        <header>
                          <div>
                            <h3>{source.label}</h3>
                            <p>{source.description}</p>
                          </div>
                          <label className="source-toggle">
                            <input
                              type="checkbox"
                              role="switch"
                              aria-label={`${source.label} etkin`}
                              checked={!!source.enabled}
                              disabled={locked}
                              onChange={(e) => editSource(name, { enabled: e.target.checked })}
                            />
                            <span />
                          </label>
                        </header>
                        <fieldset disabled={locked} className="settings-fields">
                          <legend className="sr-only">{source.label} ayarları</legend>
                          {name === 'threatfox' && (
                            <label>
                              Bağlantı türü
                              <select
                                value={source.mode || 'api'}
                                onChange={(e) =>
                                  editSource(name, { mode: e.target.value as SourceDraft['mode'] })
                                }
                              >
                                <option value="api">ThreatFox API</option>
                                <option value="local">Yerel JSON dosyası</option>
                              </select>
                            </label>
                          )}
                          {source.accepts_key && !(name === 'threatfox' && source.mode === 'local') && (
                            <SecretField
                              label={name === 'threatfox' ? 'Auth-Key' : 'API anahtarı (isteğe bağlı)'}
                              value={sourceDraft?.api_key || ''}
                              configured={source.key_configured}
                              clearing={!!sourceDraft?.clear_key}
                              onChange={(value) => editSource(name, { api_key: value, clear_key: false })}
                              onClear={() =>
                                editSource(name, { api_key: '', clear_key: !sourceDraft?.clear_key })
                              }
                            />
                          )}
                          {(name === 'sgb' || (name === 'threatfox' && source.mode === 'local')) && (
                            <label>
                              JSON dosyasının tam yolu
                              <input
                                value={source.file_path || ''}
                                placeholder="/veri/gostergeler.json"
                                spellCheck={false}
                                onChange={(e) => editSource(name, { file_path: e.target.value })}
                              />
                            </label>
                          )}
                          {name === 'sgb' && (
                            <p className="settings-hint">
                              Mevcut SGB entegrasyonu dosyadan okur. Her kayıt url, ioc veya value alanı
                              içerebilir.
                            </p>
                          )}
                          <footer>
                            <button
                              type="button"
                              className="button secondary small"
                              onClick={() => testSource(name)}
                            >
                              {busy === name ? (
                                <LoaderCircle className="spin" size={14} />
                              ) : (
                                <PlugZap size={14} />
                              )}{' '}
                              {name === 'sgb' || (name === 'threatfox' && source.mode === 'local')
                                ? 'Dosyayı kontrol et'
                                : 'Bağlantıyı dene'}
                            </button>
                            {source.docs_url && (
                              <a href={source.docs_url} target="_blank" rel="noreferrer">
                                Doküman <ExternalLink size={12} />
                              </a>
                            )}
                          </footer>
                        </fieldset>
                        <ConnectionStatus result={results[name]} />
                      </article>
                    );
                  })}
              </div>
            </section>
          ))}
        </section>
      )}
      <div className="settings-save-bar">
        <div>
          {error ? (
            <span className="settings-error" role="alert">
              {error}
            </span>
          ) : notice ? (
            <span className="settings-saved" role="status">
              <CheckCircle2 size={16} />
              {notice}
            </span>
          ) : (
            <span>
              {dirty
                ? 'Kaydedilmemiş değişiklikler var.'
                : 'Bağlantı bilgileri bu Belgü kurulumunda saklanır.'}
            </span>
          )}
        </div>
        <div>
          <button
            className="button secondary"
            disabled={!dirty || locked}
            onClick={() => {
              setDraft({});
              setNotice('');
              setError('');
              setResults({});
              setModels({});
            }}
          >
            Vazgeç
          </button>
          <button className="button primary" disabled={!dirty || locked} onClick={save}>
            {busy === 'save' ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />} Ayarları
            kaydet
          </button>
        </div>
      </div>
    </div>
  );
}
