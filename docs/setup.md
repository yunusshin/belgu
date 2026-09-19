# Kurulum

## Gereksinimler

- Linux; kurulum betikleri Bash kullanır. Otomatik testler Ubuntu üzerinde çalışır.
- Python 3.12 veya üzeri ve `venv` modülü.
- Node.js 22 ve npm.
- Git, internet bağlantısı ve Playwright Chromium'un sistem kitaplıkları.
- İsteğe bağlı OCR için Tesseract; model analizi için çalışan bir model API'si.

Demo için GPU gerekmez. Yerel modelin bellek ve GPU ihtiyacı kullanılan modele aittir; Belgü belirli bir model ağırlığı sağlamaz. macOS ve yerel Windows kurulumu bu projenin otomatik test kapsamına dahil değildir.

Ubuntu 24.04 üzerinde Python ve Git için:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv
```

[Node.js indirme sayfasından](https://nodejs.org/en/download) 22.x sürümünü, işletim sisteminizi ve işlemci mimarinizi seçerek Node.js ile npm'yi kurun. Ardından sürümleri doğrulayın:

```bash
python3 --version
node --version
npm --version
```

## Kaynak koddan kurulum

```bash
git clone https://github.com/yunusshin/belgu.git
cd belgu
bash scripts/setup.sh
```

`setup.sh`, `.venv` içinde `requirements.lock` bağımlılıklarını kurar, Belgü paketini yükler, `web/package-lock.json` ile npm paketlerini kurar, Chromium'u indirir ve arayüzü derler. Sistem Python ortamına paket yüklemez. İlk kurulumda internet gerekir; model ağırlıkları indirilmez.

Ubuntu/Debian üzerinde Chromium'un sistem kitaplıklarını da kurun:

```bash
.venv/bin/python -m playwright install-deps chromium
```

Bu komut sistem paketleri için yönetici yetkisi isteyebilir; [Playwright sistem bağımlılıkları](https://playwright.dev/python/docs/browsers#install-system-dependencies) belgesine bakın. Python ortamı ya da tarayıcı indirmesi başarısız olursa betik hata ile durur; sonraki adıma geçmeden hata çıktısını giderin.

## Demo profili

```bash
bash scripts/run.sh demo
```

Komut çalışırken aynı bilgisayardaki tarayıcıda `http://localhost:8765` adresini açın. Demo, kayıtlı örnek incelemeler ve model yanıtlarıyla çalışır; keşif/model servisi çağırmaz. Demo ayarları salt okunurdur.

Terminalde `Ctrl+C` sunucuyu durdurur. Aynı veri diziniyle yeniden başlatmak kayıtları sıfırlamaz.

## Araştırma profili

```bash
bash scripts/run.sh live
```

Komut çalışırken `http://localhost:8766` adresini açın. Bu profilde kendi incelemelerinizi oluşturabilir, dış kaynaklardan veri toplayabilir ve model API'si kullanabilirsiniz. **Ayarlar** bölümünde bağlantıları kaydedin ve bir marka/inceleme oluşturun. [Bağlantı kılavuzu](integrations.md), gerekli sağlayıcı alanlarını açıklar.

Her iki profilin varsayılan dinleme adresi loopback'tir. Belgü bir barındırılan demo hizmeti sağlamaz; bu adresler yalnız çalışan yerel kurulumlara aittir.

## Veri dizinleri

| İçerik | Betiklerin varsayılan yolu |
| --- | --- |
| Demo veritabanı | `.local/data/demo/belgu.db` |
| Araştırma veritabanı | `.local/data/operational/belgu.db` |
| Kanıt dosyaları | ilgili profilin `evidence/` dizini |
| Sağlayıcı ayarları | ilgili profilin `integrations.json` dosyası |

Profiller birbirinin kayıtlarını kullanmaz. Özel bir üst dizin ve port seçilebilir:

```bash
BELGU_DATA_DIR="$PWD/.local/alternate-data" BELGU_PORT=8876 bash scripts/run.sh live
```

Belgü CLI'si doğrudan kullanılırsa `--data-dir` varsayılanı `.belgu` olur; `run.sh` betiği ise `.local/data` kullanır. API süreci iş kuyruğunu kendisi başlatır; standart kurulumda ayrıca worker çalıştırılması gerekmez.

Araştırma profilinin veritabanı ve model bağlantısını kontrol etmek için:

```bash
bash scripts/run.sh doctor
```

Özel veri dizini kullanılıyorsa aynı `BELGU_DATA_DIR` değeriyle çalıştırın. Model henüz yapılandırılmadıysa model durumunun kullanılamaz olması demo kurulumunu engellemez.

## İsteğe bağlı OCR

Ubuntu/Debian üzerinde:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-tur
export BELGU_OCR_LANG=tur+eng
```

Alternatif olarak `bash scripts/install-ocr-local.sh`, desteklenen Ubuntu/Debian sistemlerinde OCR paketlerini projenin `.local` dizinine kurabilir. Mevcut Tesseract kurulumu bulunduğunda onu kullanır. Özel kurulumlar için `BELGU_TESSERACT_PATH` tanımlanabilir. OCR olmadan ekran görüntüsü ve DOM toplama kullanılabilir; OCR durumu ayrıca gösterilir.

## Güncelleme ve yedekleme

1. Panel süreçlerini `Ctrl+C` ile durdurun.
2. Her profilin bütün dizinini, veritabanı ve kanıt dosyalarıyla birlikte yedekleyin.
3. Kaynak kodu güncelleyin ve bağımlılık/arayüz kurulumunu yeniden çalıştırın.
4. Kullanılan profillerin veritabanlarına şema geçişlerini uygulayın.

```bash
git pull --ff-only
bash scripts/setup.sh
BELGU_DB_URL="sqlite:///$PWD/.local/data/operational/belgu.db" .venv/bin/alembic upgrade head
```

Demo profilini de kullanıyorsanız onun `demo/belgu.db` yoluna ayrı geçiş uygulayın. Özel veri dizini kullanılıyorsa örnekteki yolu değiştirin. Yeni veritabanlarında ilk şema uygulama tarafından oluşturulur.

## Sorun giderme

| Belirti | Kontrol |
| --- | --- |
| `venv` oluşturulamıyor | Python sürümünü ve dağıtımın `python3-venv` paketini kontrol edin. |
| Chromium başlatılamıyor | `.venv/bin/python -m playwright install chromium` ve Linux'ta `install-deps chromium` komutlarını çalıştırın. |
| Port kullanımda | Başka süreç seçili portu kullanıyor olabilir; `BELGU_PORT` ile farklı port seçin. |
| Arayüz bulunamıyor | Depo kökünde `npm --prefix web run build` çalıştırın. |
| Model kullanılamıyor | Ayarlar'daki API kökü, model kimliği, protokol ve anahtarı kontrol edip bağlantı denemesini çalıştırın. |
| Kaynak kota/erişim hatası | İş ayrıntısındaki sağlayıcı yanıtını inceleyin; sağlayıcı erişimini ve kotasını kontrol edin. |

Model ve API anahtarları için [bağlantı kılavuzuna](integrations.md), geliştirme ortamı için [test rehberine](testing.md) bakın.
