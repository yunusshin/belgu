import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import {
  Columns2,
  Focus,
  GripVertical,
  Hand,
  ImageOff,
  Layers2,
  RotateCcw,
  Scan,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import '../../styles/image-comparison.css';

type Side = 'capture' | 'reference';
type Point = { x: number; y: number };
type Region = Point & { width: number; height: number };
type Dimensions = { width: number; height: number };
type View = { zoom: number; center: Point };
type Source = { src: string; label: string };
type Geometry = Dimensions & { left: number; top: number };
type Drag =
  | { kind: 'pan'; start: Point; center: Point; geometry: Geometry }
  | { kind: 'region'; start: Point; geometry: Geometry; bounds: DOMRect; latest: Region | null }
  | { kind: 'divider'; bounds: DOMRect };
const startView = (): View => ({ zoom: 1, center: { x: 0.5, y: 0.5 } });
const clamp = (value: number, minimum: number, maximum: number) =>
  Math.max(minimum, Math.min(maximum, value));
function constrain(center: Point, zoom: number): Point {
  const edge = 0.5 / zoom;
  return { x: clamp(center.x, edge, 1 - edge), y: clamp(center.y, edge, 1 - edge) };
}
function fitted(size: Dimensions, image: Dimensions, view: View): Geometry {
  const scale = Math.min(size.width / image.width, size.height / image.height) * view.zoom;
  const width = image.width * scale,
    height = image.height * scale;
  return {
    width,
    height,
    left: size.width / 2 - view.center.x * width,
    top: size.height / 2 - view.center.y * height,
  };
}
function relative(point: Point, bounds: DOMRect, geometry: Geometry): Point {
  return {
    x: (point.x - bounds.left - geometry.left) / geometry.width,
    y: (point.y - bounds.top - geometry.top) / geometry.height,
  };
}
function retryUrl(src: string, attempt: number) {
  if (!attempt || src.startsWith('data:') || src.startsWith('blob:')) return src;
  const url = new URL(src, document.baseURI);
  url.searchParams.set('belgu_image_retry', String(attempt));
  return url.href;
}

export function ImageComparison({ capture, reference }: { capture?: Source; reference?: Source }) {
  const [mode, setMode] = useState<'split' | 'overlay'>('split');
  const [tool, setTool] = useState<'pan' | 'region'>('pan');
  const [view, setView] = useState<View>(startView);
  const [divider, setDivider] = useState(50);
  const [region, setRegion] = useState<Region | null>(null);
  const [dimensions, setDimensions] = useState<Record<Side, Dimensions | null>>({
    capture: null,
    reference: null,
  });
  const [failed, setFailed] = useState<Record<Side, boolean>>({ capture: false, reference: false });
  const [attempts, setAttempts] = useState<Record<Side, number>>({ capture: 0, reference: 0 });
  const drag = useRef<Drag | null>(null),
    instructions = useId();
  const sources = { capture, reference };
  const ready = {
    capture: !!capture && !!dimensions.capture && !failed.capture,
    reference: !!reference && !!dimensions.reference && !failed.reference,
  };
  const anyReady = ready.capture || ready.reference,
    bothReady = ready.capture && ready.reference;
  const differentRatio =
    bothReady &&
    Math.abs(
      dimensions.capture!.width / dimensions.capture!.height -
        dimensions.reference!.width / dimensions.reference!.height,
    ) > 0.01;

  function zoomTo(value: number) {
    const zoom = clamp(value, 1, 6);
    setView((current) => ({ zoom, center: constrain(current.center, zoom) }));
  }
  function reset() {
    setView(startView());
    setRegion(null);
    setDivider(50);
    setTool('pan');
    drag.current = null;
  }
  function focusRegion(selected: Region) {
    const zoom = clamp(Math.floor((1 / Math.max(selected.width, selected.height) + 0.005) * 4) / 4, 1, 6);
    setView({
      zoom,
      center: constrain({ x: selected.x + selected.width / 2, y: selected.y + selected.height / 2 }, zoom),
    });
    setRegion(selected);
    setTool('pan');
  }
  function loaded(side: Side, image: HTMLImageElement) {
    if (!image.naturalWidth || !image.naturalHeight) return;
    setDimensions((current) => ({
      ...current,
      [side]: { width: image.naturalWidth, height: image.naturalHeight },
    }));
    setFailed((current) => ({ ...current, [side]: false }));
  }
  function retry(side: Side) {
    setDimensions((current) => ({ ...current, [side]: null }));
    setFailed((current) => ({ ...current, [side]: false }));
    setAttempts((current) => ({ ...current, [side]: current[side] + 1 }));
  }
  function pointerDown(event: PointerEvent<HTMLDivElement>, side: Side, geometry: Geometry | null) {
    if (event.button !== 0 || !ready[side] || !geometry || (tool === 'pan' && view.zoom === 1)) return;
    if (tool === 'region' && !bothReady) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const point = { x: event.clientX, y: event.clientY };
    if (tool === 'region') {
      const start = relative(point, bounds, geometry);
      if (start.x < 0 || start.x > 1 || start.y < 0 || start.y > 1) return;
      drag.current = { kind: 'region', start, bounds, geometry, latest: null };
      setRegion(null);
    } else drag.current = { kind: 'pan', start: point, center: view.center, geometry };
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current) return;
    if (current.kind === 'divider') {
      setDivider(
        Math.round(clamp(((event.clientX - current.bounds.left) / current.bounds.width) * 100, 0, 100)),
      );
    } else if (current.kind === 'pan') {
      const center = {
        x: current.center.x - (event.clientX - current.start.x) / current.geometry.width,
        y: current.center.y - (event.clientY - current.start.y) / current.geometry.height,
      };
      setView((value) => ({ ...value, center: constrain(center, value.zoom) }));
    } else {
      const point = relative({ x: event.clientX, y: event.clientY }, current.bounds, current.geometry);
      const end = { x: clamp(point.x, 0, 1), y: clamp(point.y, 0, 1) };
      const selected = {
        x: Math.min(current.start.x, end.x),
        y: Math.min(current.start.y, end.y),
        width: Math.abs(current.start.x - end.x),
        height: Math.abs(current.start.y - end.y),
      };
      current.latest = selected;
      setRegion(selected);
    }
  }
  function end(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
    if (current?.kind === 'region') {
      if (current.latest && current.latest.width >= 0.02 && current.latest.height >= 0.02)
        focusRegion(current.latest);
      else setRegion(null);
    }
  }
  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!anyReady) return;
    if (event.key === 'Enter' && tool === 'region' && bothReady) {
      event.preventDefault();
      focusRegion({ x: 0.25, y: 0.25, width: 0.5, height: 0.5 });
      return;
    }
    if (event.key === 'Escape') {
      setRegion(null);
      setTool('pan');
      return;
    }
    const direction: Record<string, Point> = {
      ArrowLeft: { x: -0.05, y: 0 },
      ArrowRight: { x: 0.05, y: 0 },
      ArrowUp: { x: 0, y: -0.05 },
      ArrowDown: { x: 0, y: 0.05 },
    };
    if (direction[event.key]) {
      event.preventDefault();
      const delta = direction[event.key];
      setView((current) => ({
        ...current,
        center: constrain(
          { x: current.center.x + delta.x / current.zoom, y: current.center.y + delta.y / current.zoom },
          current.zoom,
        ),
      }));
    }
  }
  function startDivider(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    drag.current = { kind: 'divider', bounds: event.currentTarget.parentElement!.getBoundingClientRect() };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  const paneProps = {
    sources,
    dimensions,
    failed,
    attempts,
    view,
    region,
    mode,
    tool,
    divider,
    instructions,
    anyReady,
    onLoad: loaded,
    onError: (side: Side) => setFailed((current) => ({ ...current, [side]: true })),
    onRetry: retry,
    onPointerDown: pointerDown,
    onPointerMove: move,
    onPointerUp: end,
    onPointerCancel: () => {
      drag.current = null;
    },
    onKeyDown: keyDown,
    onDividerStart: startDivider,
  };
  return (
    <section className="panel image-comparison" aria-label="Görsel karşılaştırma">
      <header className="comparison-toolbar">
        <div className="comparison-mode" role="group" aria-label="Karşılaştırma görünümü">
          <button type="button" aria-pressed={mode === 'split'} onClick={() => setMode('split')}>
            <Columns2 size={15} />
            Yan yana
          </button>
          <button
            type="button"
            aria-pressed={mode === 'overlay'}
            disabled={!bothReady}
            onClick={() => setMode('overlay')}
          >
            <Layers2 size={15} />
            Üst üste
          </button>
        </div>
        <div className="comparison-zoom">
          <button
            type="button"
            aria-label="Birlikte uzaklaştır"
            disabled={!anyReady || view.zoom === 1}
            onClick={() => zoomTo(view.zoom - 0.25)}
          >
            <ZoomOut size={16} />
          </button>
          <input
            type="range"
            min="100"
            max="600"
            step="25"
            aria-label="Birlikte yakınlaştır"
            disabled={!anyReady}
            value={Math.round(view.zoom * 100)}
            onChange={(event) => zoomTo(Number(event.target.value) / 100)}
          />
          <output aria-live="polite">%{Math.round(view.zoom * 100)}</output>
          <button
            type="button"
            aria-label="Birlikte yakınlaştırmayı artır"
            disabled={!anyReady || view.zoom === 6}
            onClick={() => zoomTo(view.zoom + 0.25)}
          >
            <ZoomIn size={16} />
          </button>
        </div>
        <div className="comparison-tools" role="group" aria-label="Görüntü araçları">
          <button
            type="button"
            aria-pressed={tool === 'pan'}
            disabled={!anyReady}
            onClick={() => setTool('pan')}
          >
            <Hand size={15} />
            Taşı
          </button>
          <button
            type="button"
            aria-pressed={tool === 'region'}
            disabled={!bothReady}
            onClick={() => setTool('region')}
          >
            <Scan size={15} />
            Alan seç
          </button>
          <button type="button" aria-label="Görünümü sıfırla" disabled={!anyReady} onClick={reset}>
            <RotateCcw size={15} />
            <span>Sıfırla</span>
          </button>
        </div>
      </header>
      <div className="comparison-source-names">
        {(['capture', 'reference'] as Side[]).map((side) => (
          <div key={side}>
            <strong>
              <span>{side === 'capture' ? '01' : '02'}</span>
              {sources[side]?.label || (side === 'capture' ? 'Yakalanan sayfa' : 'Marka referansı')}
            </strong>
            <span>
              {dimensions[side] && !failed[side]
                ? `${dimensions[side]!.width} × ${dimensions[side]!.height} px`
                : !sources[side]
                  ? 'Görüntü seçilmedi'
                  : failed[side]
                    ? 'Boyut okunamadı'
                    : 'Özgün boyut bekleniyor'}
            </span>
          </div>
        ))}
      </div>
      <div className={`comparison-canvases ${mode}`}>
        {mode === 'split' ? (
          <>
            <ComparisonPane {...paneProps} sides={['capture']} name="capture" />
            <ComparisonPane {...paneProps} sides={['reference']} name="reference" />
          </>
        ) : (
          <ComparisonPane {...paneProps} sides={['capture', 'reference']} name="overlay" />
        )}
      </div>
      {mode === 'overlay' && (
        <label className="comparison-divider-control">
          <span>Yakalanan sayfa</span>
          <input
            type="range"
            min="0"
            max="100"
            value={divider}
            aria-label="Karşılaştırma ayırıcı"
            onChange={(event) => setDivider(Number(event.target.value))}
          />
          <span>{reference?.label || 'Marka referansı'}</span>
          <output>%{divider}</output>
        </label>
      )}
      <footer className="comparison-notes">
        <p id={instructions}>
          {tool === 'region'
            ? 'Görüntüde bir dikdörtgen çizin; aynı oransal alan iki görüntüde odaklanır. Klavyeyle: görüntüye odaklanıp Enter ile orta alanı seçin.'
            : 'Yakınlaştırıp bir görüntüyü sürükleyin; ikisi birlikte hareket eder. Görüntüye odaklanınca ok tuşlarıyla da taşıyabilirsiniz.'}
        </p>
        {region && (
          <div className="comparison-region-summary" role="status">
            <span>
              Seçili alan: %{Math.round(region.x * 100)}, %{Math.round(region.y * 100)} · genişlik %
              {Math.round(region.width * 100)}, yükseklik %{Math.round(region.height * 100)}
            </span>
            <button type="button" disabled={!bothReady} onClick={() => focusRegion(region)}>
              <Focus size={14} />
              Seçili alana odaklan
            </button>
            <button type="button" onClick={() => setRegion(null)}>
              İşareti kaldır
            </button>
          </div>
        )}
        {differentRatio && (
          <p className="comparison-limitation">
            En-boy oranları farklı. Görüntüler esnetilmeden sığdırılır; aynı oransal alan, aynı içerik veya
            birebir piksel eşleşmesi anlamına gelmez.
          </p>
        )}
        <p className="comparison-provenance">
          İşaretler analistin bu görünümdeki seçimidir; kaynak görüntülere yazılmaz. Bu görüntüleyici puan
          hesaplamaz; yerel sıralama ayrı panelde gösterilir.
        </p>
      </footer>
    </section>
  );
}

type PaneProps = {
  sides: Side[];
  name: Side | 'overlay';
  sources: Record<Side, Source | undefined>;
  dimensions: Record<Side, Dimensions | null>;
  failed: Record<Side, boolean>;
  attempts: Record<Side, number>;
  view: View;
  region: Region | null;
  mode: 'split' | 'overlay';
  tool: 'pan' | 'region';
  divider: number;
  instructions: string;
  anyReady: boolean;
  onLoad: (side: Side, image: HTMLImageElement) => void;
  onError: (side: Side) => void;
  onRetry: (side: Side) => void;
  onPointerDown: (event: PointerEvent<HTMLDivElement>, side: Side, geometry: Geometry | null) => void;
  onPointerMove: (event: PointerEvent<HTMLDivElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLDivElement>) => void;
  onPointerCancel: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
  onDividerStart: (event: PointerEvent<HTMLDivElement>) => void;
};
function ComparisonPane(props: PaneProps) {
  const { sides, name, sources, dimensions, failed, attempts, view, region, mode, tool, divider } = props;
  const container = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<Dimensions>({ width: 0, height: 0 });
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const bounds = entries[0].contentRect;
      // Hidden visited tabs keep their last useful geometry and image state.
      if (bounds.width && bounds.height) setSize({ width: bounds.width, height: bounds.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const geometry = (side: Side) => (dimensions[side] ? fitted(size, dimensions[side]!, view) : null);
  return (
    <div
      ref={container}
      className={`comparison-pane tool-${tool} ${view.zoom > 1 ? 'is-zoomed' : ''}`}
      data-testid={`comparison-${name}-pane`}
      tabIndex={props.anyReady ? 0 : -1}
      aria-label={
        name === 'overlay'
          ? 'Üst üste karşılaştırma alanı'
          : `${name === 'capture' ? 'Yakalanan sayfa' : 'Marka referansı'} karşılaştırma alanı`
      }
      aria-describedby={props.instructions}
      onPointerDown={(event) => {
        if ((event.target as HTMLElement).closest('button')) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        const side =
          name === 'overlay'
            ? event.clientX - bounds.left > (bounds.width * divider) / 100
              ? 'reference'
              : 'capture'
            : name;
        props.onPointerDown(event, side, geometry(side));
      }}
      onPointerMove={props.onPointerMove}
      onPointerUp={props.onPointerUp}
      onPointerCancel={props.onPointerCancel}
      onKeyDown={(event) => {
        if (event.target === event.currentTarget) props.onKeyDown(event);
      }}
    >
      {sides.map((side) => {
        const source = sources[side],
          bounds = geometry(side),
          label = source?.label || (side === 'capture' ? 'Yakalanan sayfa' : 'Marka referansı');
        const frame: CSSProperties = bounds
          ? { width: bounds.width, height: bounds.height, left: bounds.left, top: bounds.top }
          : { width: '100%', height: '100%', left: 0, top: 0 };
        return (
          <div
            className={`comparison-plane ${side}`}
            key={side}
            style={
              mode === 'overlay' && side === 'reference'
                ? { clipPath: `inset(0 0 0 ${divider}%)` }
                : undefined
            }
          >
            {!source ? (
              <div className="comparison-image-status">
                <ImageOff size={25} />
                <p>
                  {side === 'reference' ? 'Referans görüntüsü seçilmedi.' : 'Henüz yakalanan görüntü yok.'}
                </p>
              </div>
            ) : failed[side] ? (
              <div className="comparison-image-status" role="status">
                <ImageOff size={25} />
                <p>{label} yüklenemedi.</p>
                <button
                  type="button"
                  aria-label={`${label} görüntüsünü yeniden yükle`}
                  onClick={() => props.onRetry(side)}
                >
                  Yeniden dene
                </button>
              </div>
            ) : (
              <>
                {!dimensions[side] && (
                  <div className="comparison-image-status" role="status">
                    {label} yükleniyor…
                  </div>
                )}
                <div className="comparison-image-frame" style={frame}>
                  <img
                    key={attempts[side]}
                    src={retryUrl(source.src, attempts[side])}
                    alt={source.label}
                    draggable={false}
                    style={{ opacity: dimensions[side] ? 1 : 0 }}
                    onLoad={(event) => props.onLoad(side, event.currentTarget)}
                    onError={() => props.onError(side)}
                  />
                  {region && dimensions[side] && (
                    <div
                      className="comparison-selection"
                      data-testid={`comparison-${side}-selection`}
                      style={{
                        left: `${region.x * 100}%`,
                        top: `${region.y * 100}%`,
                        width: `${region.width * 100}%`,
                        height: `${region.height * 100}%`,
                      }}
                    />
                  )}
                </div>
              </>
            )}
          </div>
        );
      })}
      {name === 'overlay' && (
        <div
          className="comparison-divider"
          data-testid="comparison-divider"
          style={{ left: `${divider}%` }}
          aria-hidden="true"
          onPointerDown={props.onDividerStart}
          onPointerMove={props.onPointerMove}
          onPointerUp={props.onPointerUp}
          onPointerCancel={props.onPointerCancel}
        >
          <span>
            <GripVertical size={18} />
          </span>
        </div>
      )}
    </div>
  );
}
