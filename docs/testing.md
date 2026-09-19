# Geliştirme ve testler

Önce [kurulum](setup.md) adımlarını tamamlayın. Aşağıdaki komutlar depo kökünden çalıştırılır.

## Otomatik kontroller

```bash
.venv/bin/python -m pytest tests evals -q
npm --prefix web run generate:api
npm --prefix web run build
npm --prefix web run test:e2e
```

Python testleri kalıcılık, keşif, iş kuyruğu, analiz sözleşmeleri, sağlayıcı ayarları ve raporları kapsar. Tarayıcı testleri arayüz fixture'ları ve geçici API/veritabanları üzerinden kullanıcı akışlarını denetler. Chromium gerekir; `cd web` sonrasında `npx playwright install chromium` ile kurulabilir.

GitHub Actions aynı temel kontrolleri temiz Ubuntu ortamında yürütür. Geçerli sonuç için [son CI koşusuna](https://github.com/yunusshin/belgu/actions) bakın; bu belge sabit bir test sayısını bütün sürümler için başarı garantisi olarak kullanmaz.

Otomatik testler için model ağırlığı veya bulut API anahtarı gerekmez. Sağlayıcı testlerinde kontrollü HTTP yanıtları kullanılır; bunların geçmesi gerçek hesabın model erişimini/kotasını doğrulamaz. Görsel toplama testlerinin bir bölümü kurulu Chromium ve isteğe bağlı OCR kullanır.

## Arayüz geliştirme

Ayrı terminallerde:

```bash
bash scripts/run.sh demo
```

```bash
npm --prefix web run dev
```

Vite geliştirme sunucusu varsayılan olarak `http://localhost:5174` adresinde çalışır; `/api` isteklerini demo API'sinin 8765 portuna yönlendirir. Derlenmiş arayüz doğrudan FastAPI tarafından sunulur.

API tipleri, worker başlatmayan geçici bir backend uygulamasının OpenAPI şemasından üretilir. Python ortamı `.venv` altında bulunmalıdır. Tarayıcı testleri 8775/8776 portlarında geçici API profilleri açar. Bu portları testler için ayırın; mevcut kişisel veritabanını test hedefi olarak kullanmayın.

## Model değerlendirmesi

`evals/fixtures/` dizininde paylaşımlı altyapı, eksik kanıt, tarih/kapsam ayrımı, form/OCR ve gömülü talimat örnekleri bulunur. Bunlar kontrollü sentetik verilerdir. Gerçek bir model API'siyle çalıştırma ve sonuçları puanlama komutları [evals/README.md](../evals/README.md) dosyasındadır.

JSON şemasına uyum ve geçerli atıflar anlamsal doğruluk oranı değildir. Üretilen yorumları dayanaklarıyla ayrıca inceleyin. Değerlendirme çıktıları `.local` altında tutulur; kaynak veri kümesinin parçası değildir.

## Yerel görsel ve sorgu kontrolleri

```bash
.venv/bin/python evals/visual_similarity.py
.venv/bin/python scripts/benchmark_queries.py
```

İlki sentetik görsellerde aynı görüntü, yeniden boyutlandırma, yerleşim kayması ve geçersiz görüntü durumlarını ölçer. İkincisi geçici SQLite verileriyle sorgu sürelerini ölçer ve sonuçlarını `.local/validation/` altına yazar. Bu sonuçlar internet kaynaklarının performansı veya gerçek oltalama tespit doğruluğu değildir.
