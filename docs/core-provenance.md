# Kaynak kökeni ve lisanslar

Belgü'nün keşif bağdaştırıcıları, Yunus Sahin'in MIT lisanslı Yelme projesindeki bazı algoritmalardan uyarlanmıştır. Kaynak sürüm: `65f3104bdb318085e12210c9c09dd31393926d7e`. Telif ve lisans bildirimi [LICENSE](../LICENSE) ve [NOTICE](../NOTICE) içinde korunur. Belgü başka bir Yelme çalışma dizinine veya veritabanına çalışma zamanı bağımlılığı taşımaz.

| Kaynak modül | Belgü bileşeni | Uyarlama |
| --- | --- | --- |
| `enrich/rdns.py` | `core/providers/dns.py` | A/AAAA/PTR gözlemleri ve zaman/kaynak bilgileri |
| `enrich/reverseip.py` | `core/providers/reverse_ip.py` | Ayrı HackerTarget ve mnemonic kaynak atfı |
| `enrich/crtsh.py` | `core/providers/crtsh.py` | Sertifika kaydı kimliği, zamanı ve hedef kapsamı |
| `enrich/urlscan.py` | `core/providers/urlscan.py` | Mevcut tarama verileri ve tam ana hedef eşleşmesi |
| `enrich/favicon.py` | `core/providers/favicon.py` | İçeriğin SHA-256 gözlemi |
| `verify/kitsig.py` | `core/signals/kit.py` | Sayfa/betik sinyalleri; otomatik saldırgan atfı yok |
| `seeds/openphish.py` | `core/feeds/openphish.py` | Hedefe bağlı feed eşleşmesi |
| `seeds/{sgb,threatfox}.py` | `core/feeds/local.py` | Yerel JSON kaynakları; ThreatFox için ayrıca API bağdaştırıcısı |
| `graph/builder.py` | `core/discovery.py` | İş başına bütçeli keşif ve kanıtlı ilişkiler |

Arayüzde kullanılan Manrope fontunun ve Lucide ikonlarının lisans metinleri [web/public/licenses](../web/public/licenses) dizinindedir. Python ve JavaScript bağımlılıkları kendi lisanslarına tabidir.
