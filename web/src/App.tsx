import { useEffect, useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  Building2,
  ChevronRight,
  FolderSearch,
  HelpCircle,
  Menu,
  Moon,
  Plus,
  Radio,
  Sun,
  Settings2,
  X,
} from 'lucide-react';
import { useResource } from './api/client';
import type { Health } from './api/types';
import { Badge, Modal } from './components/UI';
import Queue from './features/Queue';
import { Brands, NewInvestigation } from './features/NewInvestigation';
import Workspace from './features/Workspace';
import { JobsPage } from './features/Jobs';
import SettingsPage from './features/Settings';
export default function App() {
  const [route, setRoute] = useState(location.hash.slice(1) || '/'),
    [theme, setTheme] = useState(() => {
      try {
        return localStorage.getItem('belgu-theme') === 'light' ? 'light' : 'dark';
      } catch {
        return 'dark';
      }
    }),
    [newCase, setNewCase] = useState(false),
    [help, setHelp] = useState(false),
    [menu, setMenu] = useState(false);
  const health = useResource<Health>('/health');
  useEffect(() => {
    const onHash = () => {
      setRoute(location.hash.slice(1) || '/');
      setMenu(false);
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem('belgu-theme', theme);
    } catch {
      // Theme remains usable when browser storage is unavailable.
    }
  }, [theme]);
  const id = route.match(/^\/investigations\/([^/]+)/)?.[1];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        İçeriğe geç
      </a>
      <aside className={`sidebar ${menu ? 'open' : ''}`}>
        <a href="#/" className="brand-lockup" aria-label="Belgü ana sayfa">
          <span className="belgu-symbol">
            <i />
            <i />
            <i />
            <i />
          </span>
          <span className="wordmark">
            belgü<span>İŞARETTEN İSTİHBARATA</span>
          </span>
        </a>
        <span className="nav-label">ÇALIŞMA ALANI</span>
        <nav>
          <a href="#/" className={route === '/' || id ? 'active' : ''}>
            <FolderSearch size={18} />
            İncelemeler
            <span className="nav-dot" />
          </a>
          <a href="#/brands" className={route === '/brands' ? 'active' : ''}>
            <Building2 size={18} />
            Markalar
          </a>
          <a href="#/jobs" className={route === '/jobs' ? 'active' : ''}>
            <Activity size={18} />
            İş merkezi
          </a>
          <a href="#/settings" className={route === '/settings' ? 'active' : ''}>
            <Settings2 size={18} />
            Ayarlar
          </a>
        </nav>
        <button
          className="sidebar-new"
          onClick={() => {
            setNewCase(true);
            setMenu(false);
          }}
        >
          <Plus size={16} />
          Yeni inceleme
        </button>
        <div className="sidebar-bottom">
          <div className="local-status">
            <Radio size={16} />
            <div>
              {health.error ? 'Servis bağlantısı yok' : health.loading ? 'Bağlanıyor' : 'Servis bağlı'}
              <small>{health.data?.mode === 'demo' ? 'Kayıtlı demo ortamı' : 'Belgü çalışma alanı'}</small>
            </div>
            <span className={`status-dot ${health.error ? 'offline' : ''}`} />
          </div>
          <button className="help-button" onClick={() => setHelp(true)}>
            <HelpCircle size={16} />
            Belgü hakkında
            <ArrowUpRight size={14} />
          </button>
          <div className="sidebar-foot">
            ANALİST ODAKLI İSTİHBARAT<span>v0.5.0 · POC</span>
          </div>
        </div>
      </aside>
      {menu && <div className="sidebar-overlay" onClick={() => setMenu(false)} />}
      <div className="app-body">
        <header className="topbar">
          <div className="breadcrumb">
            <button className="icon-button mobile-menu" aria-label="Menüyü aç" onClick={() => setMenu(!menu)}>
              {menu ? <X size={18} /> : <Menu size={18} />}
            </button>
            <span>Çalışma alanı</span>
            <ChevronRight size={13} />
            <strong>
              {id
                ? 'İnceleme'
                : route === '/brands'
                  ? 'Markalar'
                  : route === '/jobs'
                    ? 'İş merkezi'
                    : route === '/settings'
                      ? 'Ayarlar'
                      : 'İncelemeler'}
            </strong>
          </div>
          <div className="topbar-actions">
            {health.data?.mode === 'demo' && (
              <Badge tone="demo">
                <span className="small-square" />
                Kurmaca demo verisi
              </Badge>
            )}
            <span className="topbar-divider" />
            <button
              className="icon-button"
              aria-label={theme === 'dark' ? 'Açık temaya geç' : 'Koyu temaya geç'}
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <span className="analyst-avatar" title="Analist">
              AN
            </span>
          </div>
        </header>
        <main id="main-content" className={id ? 'main-content investigation-page' : 'main-content'}>
          {id ? (
            <Workspace key={id} id={decodeURIComponent(id)} mode={health.data?.mode} />
          ) : route === '/brands' ? (
            <Brands />
          ) : route === '/jobs' ? (
            <JobsPage />
          ) : route === '/settings' ? (
            <SettingsPage onSaved={health.reload} />
          ) : (
            <Queue onNew={() => setNewCase(true)} />
          )}
        </main>
        <footer className="app-footer">
          <span>
            Belgü <span className="footer-separator">/</span> Finansal tehdit araştırması
          </span>
          <span>Gözlem → Bağlantı → Kanıt → Karar</span>
        </footer>
      </div>
      {newCase && <NewInvestigation onClose={() => setNewCase(false)} />}{' '}
      {help && (
        <Modal title="İşaretten istihbarata" onClose={() => setHelp(false)}>
          <p className="form-intro">
            Belgü, şüpheli finansal web sayfalarını kanıtlarıyla incelemek için tasarlanmış bir analist
            çalışma alanıdır.
          </p>
          <ol className="help-steps">
            <li>
              <strong>Bir inceleme açın.</strong>
              <span>Markayı, bildirimin kaynağını ve tam URL’yi kaydedin.</span>
            </li>
            <li>
              <strong>Bağlantıları araştırın.</strong>
              <span>Gözlemleri IP, sertifika veya JavaScript içeriğine göre daraltın.</span>
            </li>
            <li>
              <strong>Kanıtı değerlendirin.</strong>
              <span>Kaynak ve zaman bilgilerini, modelin atıflarını kontrol edin.</span>
            </li>
            <li>
              <strong>Kararınızı kaydedin.</strong>
              <span>Gerekçenizle birlikte değerlendirme geçmişini ve raporu oluşturun.</span>
            </li>
          </ol>
          <footer className="modal-footer">
            <button className="button primary" onClick={() => setHelp(false)}>
              Anladım
            </button>
          </footer>
        </Modal>
      )}
    </div>
  );
}
