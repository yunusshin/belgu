# Model ve veri sağlayıcıları

## Model bağlantısı

Araştırma profilinde **Ayarlar → Yapay zekâ** bölümünü açın. Yerel API için sunucu adresini ve gerekiyorsa anahtarı girin. Bulut sağlayıcısı için API anahtarını girin; sağlayıcı adresi sabittir. **Modelleri getir** ile sunucunun listesinden seçim yapın veya tam model kimliğini yazın. **Bağlantıyı dene** inceleme içeriği içermeyen küçük bir yapılandırılmış yanıt ister. **Analizlerde bu sağlayıcıyı kullan** seçeneğiyle kaydedilen sağlayıcı hem analizde hem asistanda kullanılır.

| Bağlantı | Gerekenler | Belgü'nün kullandığı protokol |
| --- | --- | --- |
| SGLang | Çalışan sunucunun `/v1` API kökü, model kimliği; gerekiyorsa anahtar | Models, Tokenize, Chat Completions |
| llama.cpp | Çalışan sunucunun `/v1` API kökü, model kimliği; gerekiyorsa anahtar | Models, Input Tokens, Chat Completions |
| OpenAI uyumlu API | API kökü, model kimliği; gerekiyorsa anahtar | Models ve JSON Schema destekleyen Chat Completions |
| Claude | API anahtarı ve erişilebilir model | Messages ve token sayımı |
| OpenAI | API anahtarı ve erişilebilir model | Responses ve token sayımı |
| Gemini | API anahtarı ve erişilebilir model | Generate Content ve token sayımı |
| OpenRouter | API anahtarı ve JSON Schema destekleyen model/sağlayıcı | Chat Completions |

Model kimlikleri kodda belirli bir ağırlığa sabitlenmez. Seçilen modelin JSON Schema çıktısını ve kullanılan sağlayıcı protokolünü desteklemesi gerekir. Her OpenAI uyumlu sunucu bütün gerekli özellikleri sunmayabilir; bağlantı denemesini kullanın. Demo ayarları salt okunurdur.

### Yerel API örneği

Çalışan bir llama.cpp sunucusu için ortam değişkenleriyle başlangıç ayarı:

```bash
export BELGU_MODEL_BACKEND=llama.cpp
export BELGU_MODEL_URL=http://localhost:8080/v1
bash scripts/run.sh live
```

Gerekirse `BELGU_MODEL_ID` değerini sunucunun `/v1/models` yanıtındaki tam kimlikle ayarlayın. SGLang için backend değeri `sglang`, genel uyumlu API için `openai_compatible` olur; URL, kendi sunucunuzun API köküdür. Belgü bu bağlantı sırasında model sunucusunu başlatmaz veya ağırlık indirmez.

Mevcut GGUF dosyası ve kurulu `llama-server` ile sunucu başlatmak için yardımcı betik de bulunur:

```bash
export BELGU_LLAMA_SERVER=/path/to/llama-server
export BELGU_MODEL_PATH=/path/to/model.gguf
bash scripts/start-model.sh
```

Yolları kurulu dosyalarla değiştirin. Bu betik tek slot ve 8192 bağlamlı bir llama.cpp yapılandırması başlatır; GPU katman ayarlarının seçilen model ve donanıma uygunluğu ayrıca değerlendirilmelidir.

### Girdi ve çıktı kapsamı

SGLang, llama.cpp, OpenAI, Claude ve Gemini bağlantılarında sağlayıcı token sayımıyla 6144 giriş tokenı bütçesi uygulanır. Sayım başarısızsa işlem hata verir. Genel OpenAI uyumlu bağlantılar ve OpenRouter için mesajlar/şema 32 KiB seri hale getirilmiş giriş bütçesiyle sınırlanır; bu değer modelin token bağlamına eşdeğer değildir. Çıktı üst sınırı 1024 tokendır.

Bağlama alınmayan kayıtların sayısı korunur. Yapısal olarak eksik veya geçersiz yanıtlar başarı olarak kaydedilmez. Model yalnız metin, DOM/form alanları ve OCR kullanır; ekran görüntüsü gönderilmez.

## Veri kaynakları

**Ayarlar → Araştırma kaynakları** bölümünde kaynaklar etkinleştirilebilir ve bağlantıları denenebilir.

| Kaynak | Yapılandırma | Kullanım |
| --- | --- | --- |
| HackerTarget | İsteğe bağlı API anahtarı | Reverse-IP |
| mnemonic PassiveDNS | İsteğe bağlı Argus API anahtarı | Pasif DNS / reverse-IP |
| urlscan.io | İsteğe bağlı API anahtarı | Mevcut tarama kayıtlarını arama; yeni tarama göndermez |
| ThreatFox | API kipinde Auth-Key veya yerel JSON dosyası | IOC arama; IOC göndermez |
| OpenPhish Community | Etkinleştirme | Community feed üzerinden eşleşme |
| crt.sh | Etkinleştirme | Sertifika şeffaflığı kayıtları |
| SGB | Yerel JSON dosyası | Dosyadan hedef eşleşmesi |

DNS, sayfa ve favicon toplayıcıları keşif akışına dahildir. Kaynak kotaları ve yetkileri sağlayıcı hesabına bağlıdır. Kapatılan kaynak yeni keşiflerde kullanılmaz; eski kanıtlar korunur. Bağlantı denemeleri sağlayıcı kotasını kullanabilir.

SGB ve ThreatFox dosya kipi için örnek biçim:

```json
[{"url":"https://example.test/login","category":"phishing","first_seen":"2026-01-01T00:00:00Z"}]
```

`url`, `ioc` veya `value` hedef alanı; üst düzey liste veya `data` / `models` listesi kabul edilir. Dosya boyutu sınırı 20 MiB'dir. SGB için kurumsal API bağlantısı bulunmaz.

## Anahtarlar ve veri akışı

Sağlayıcı ayarları profilin `integrations.json` dosyasına atomik yazılır. Dosya izinleri `0600` olur; anahtarlar düz metin saklanır ve işletim sistemi hesabının erişim sınırına dayanır. API, anahtarın kendisi yerine yapılandırılmış olup olmadığını döndürür. Boş anahtar alanı kayıtlı değeri korur; silmek için **Anahtarı kaldır** seçeneği kaydedilir.

GUI'deki ayarlar ortam varsayılanlarından önceliklidir. Model için `BELGU_MODEL_BACKEND`, `BELGU_MODEL_URL`, `BELGU_MODEL_ID`, `BELGU_MODEL_TIMEOUT`; bulut anahtarları için `BELGU_OPENAI_KEY`, `BELGU_ANTHROPIC_KEY`, `BELGU_GEMINI_KEY`, `BELGU_OPENROUTER_KEY` kullanılabilir. Kaynak değişkenleri: `BELGU_URLSCAN_KEY`, `BELGU_HACKERTARGET_KEY`, `BELGU_MNEMONIC_KEY`, `BELGU_THREATFOX_KEY`, `BELGU_SGB_FILE`, `BELGU_THREATFOX_FILE`, `BELGU_OPENPHISH`.

`.env.example` örnek değerleri gösterir; uygulama `.env` dosyasını kendiliğinden yüklemez. Ortam değişkenlerini paneli başlatan terminal veya süreç için tanımlayın. Açıkça kaldırılan GUI anahtarı ortam değerine geri dönmez.

Araştırma hedefleri etkin veri kaynaklarına sorgu olarak gönderilir. Bulut modeli seçildiğinde seçilen kanıt metni ilgili sağlayıcıya iletilir. Anahtarlar model bağlamına veya raporlara eklenmez. OpenAI isteklerinde `store:false` kullanılması, diğer sağlayıcıların veri işleme koşullarını değiştirmez.

## Sağlayıcı belgeleri

- [SGLang](https://docs.sglang.ai/basic_usage/openai_api_completions.html) · [llama.cpp](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
- [Claude](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) · [OpenAI Responses](https://developers.openai.com/api/reference/resources/responses) · [Gemini](https://ai.google.dev/api/generate-content) · [OpenRouter](https://openrouter.ai/docs/guides/features/structured-outputs)
- [HackerTarget](https://hackertarget.com/ip-tools/) · [mnemonic](https://docs.mnemonic.no/service-integration-guides/passivedns/docs/public/01-public_api.html) · [urlscan.io](https://urlscan.io/docs/api/) · [ThreatFox](https://threatfox.abuse.ch/api/) · [OpenPhish](https://openphish.com/phishing_feeds.html) · [crt.sh](https://crt.sh/)
