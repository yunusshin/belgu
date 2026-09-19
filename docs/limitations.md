# Bilinen sınırlar

## Çalışma kapsamı

Belgü, tek analistin yerel ortamda teknik değerlendirmesi için bir POC'dir. Çok kullanıcılı yetkilendirme, SSO, müşteri portalı, otomatik engelleme veya kurumsal dağıtım yönetimi içermez. Komut satırı sunucusu loopback üzerinde çalışır.

## Kaynak ve kanıt kapsamı

- Sağlayıcı hatası, kota veya zaman aşımı kısmi sonuç üretebilir. Bir kaydın yeniden bulunmaması silindiği anlamına gelmez.
- Ortak IP, sertifika veya JavaScript içeriği tek başına aynı saldırganı/kampanyayı doğrulamaz.
- DNS yanıtı, HTTP durumu, tarama etiketi ve marka adı tek başına oltalama veya resmî erişim engeli kanıtı değildir.
- Kaynağın gözlem tarihi ile Belgü'nün kaydı aldığı tarih farklı olabilir.
- Keşif ve grafik bütçeleri tüm internetin veya bütün ilişkilerin tarandığı anlamına gelmez.

## Model yorumları

Analiz gönderilmiş hedeflerin kanıtlarına odaklanır. İlişkili başka hedeflerin kayıtları araştırma alanında kalır; onları hedef olarak eklemek ayrı bir değerlendirme gerektirebilir. Kanıt sayısı ve token/veri bütçesi nedeniyle bazı kayıtlar bağlam dışında kalabilir; dışlanan adetler gösterilir.

Şema ve atıf doğrulama, serbest metnin bütün olgusal hatalarını yakalayamaz. Bir form alanının bulunması veri çalındığını; bulunmaması ise sitenin güvenli olduğunu göstermez. OCR hataları ve tarihsel gözlemler de modelin yorumunu etkileyebilir. Kararı analist verir.

Bu sürümde modele ekran görüntüsü gönderilmez. Modelin görsel yeteneği olması Belgü'de görüntü analizi yapıldığı anlamına gelmez. Görsel benzerlik puanı ayrı bir yerel yöntemdir; zararlılık olasılığı veya logo tanıma doğruluğu değildir.

## Tarayıcı yakalama ve görsel karşılaştırma

Yakalama, Chromium'da sınırlı bir görünüm alanı kullanır. Form gönderimleri, ek gezinme ve bazı dinamik ağ istekleri engellenir. Bu nedenle yakalanan sayfa normal tarayıcı kullanımından farklı veya eksik görünebilir. Mobil profil fiziksel telefon veya Safari testi değildir.

Kaydırma, pencere boyutu, tema, çerez katmanı ve farklı en-boy oranları görsel puanları etkiler. Boş/bozuk veya uyumsuz görüntüler değerlendirilmeyebilir. Karşılaştırma sonucunu gerçek görüntü ve kaynak kaydıyla inceleyin.

## Gösterim ve test verileri

Demo, sentetik hedefler ve kayıtlı model yanıtları içerir; canlı tespit performansı göstermez. Test fixture'ları ve medya, gerçek müşteri incelemeleri değildir. Örnek veri kümelerinin sonuçlarından sektör geneline doğruluk veya performans oranı çıkarılamaz.
