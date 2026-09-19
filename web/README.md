# Belgü arayüzü

React, TypeScript ve Vite tabanlı analist arayüzü. Fontlar ve ikonlar yerel paketlenir; ilgili lisanslar `public/licenses/` altındadır.

Depo kökünden:

```bash
npm --prefix web ci
npm --prefix web run generate:api
npm --prefix web run build
```

Geliştirme için önce demo API'sini `bash scripts/run.sh demo` ile başlatın; ayrı terminalde `npm --prefix web run dev` çalıştırın. Vite varsayılan olarak `http://localhost:5174` üzerinde çalışır ve `/api` isteklerini 8765 portuna yönlendirir. Üretim build'i FastAPI tarafından sunulur.

`generate:api`, depo kökündeki `.venv` Python ortamını ve geçici bir backend uygulamasını kullanır. Test komutları, geçici veritabanları ve tarayıcı gereksinimleri [test rehberinde](../docs/testing.md) açıklanır.
