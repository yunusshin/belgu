# Model değerlendirme araçları

Bu dizin, kanıta bağlı Türkçe analiz davranışını sınamak için sentetik vakalar ve bir model API'sine karşı çalıştırılabilen değerlendirme araçları içerir. Veri kümeleri sentetiktir; sonuçlar çalıştırma sırasında yerel dizine yazılır.

## Veri kümeleri

| Dosya | Kapsam |
| --- | --- |
| `fixtures/text-cases.jsonl` | Şüpheli/meşru örnekler, paylaşımlı altyapı, eksik kanıt ve gömülü talimatlar |
| `fixtures/scope-time-cases.jsonl` | Hedef kapsamı ve tarihsel gözlemler |
| `fixtures/form-modality-cases.jsonl` | Form alanları, metin ve görsel gözlem ayrımı |
| `fixtures/negative-dns-cases.jsonl` | NXDOMAIN, zaman aşımı ve tarihsel içerik |
| `fixtures/assistant-v1-grounding.json` | Asistan için kontrollü kaynak ve konuşma örnekleri |

Alan adları ve IP'ler test/dokümantasyon değerleridir. Bu veri kümeleri gerçek dünya tespit doğruluğu ölçmek için temsilî bir örneklem değildir.

## Çalıştırma

Kurulumu tamamlayın ve JSON Schema/token sayımı destekleyen bir model sunucusu başlatın. SGLang örneği:

```bash
BELGU_MODEL_BACKEND=sglang .venv/bin/python -m evals.run \
  --base-url http://localhost:30000/v1 \
  --cases evals/fixtures/text-cases.jsonl \
  --repeats 1 \
  --output .local/evals/results.jsonl
```

API kökünü kendi sunucunuza göre değiştirin. Model kimliği belirtilmezse sunucudan alınır; belirli model için `--model` ile sunucunun bildirdiği tam kimliği verin. llama.cpp için backend `llama.cpp` ve ilgili API kökü kullanılır. Bu komut gerçek model çıkarımı yapar; demo yanıtlarını puanlamaz ve model ağırlığı indirmez.

`--max-cases` vaka sayısını sınırlar. `--resume`, aynı çıktı dosyasındaki tamamlanmış vaka/tekrar çiftlerini atlar. Varsayılan tekrar sayısı ikidir; örnekte açıkça bir tur seçilmiştir.

## Sonuçları değerlendirme

```bash
.venv/bin/python -m evals.score \
  --input .local/evals/results.jsonl \
  --output .local/evals/summary.json
```

Skorlayıcı yapı geçerliliğini, snapshot dışı atıfları, beklenen ifade eşleşmelerini ve süreleri raporlar; aynı dizine Markdown matrisi de yazar. İfade eşleşmesi ve geçerli JSON, modelin doğru yorum yaptığı anlamına gelmez. Her iddiayı kanıtı ve gözlem zamanıyla ayrıca değerlendirin.

Çıktılar yerel çalışma dizininde tutulur. Farklı model, prompt ve kanıt kümelerinin süreleri kontrollü bir karşılaştırma yapılmadan birbirine denk kabul edilmemelidir.

Görsel benzerlik için `.venv/bin/python evals/visual_similarity.py`, paketlenmiş sentetik görüntüler üzerinde yerel kontrolleri çalıştırır; ağ/model çağrısı yapmaz.
