# İşletmePilot AI — dört modül

Kapsam: LeadPilot CRM, YorumPilot yorum taslakları, SiteNöbet izleme,
Müşteri Avcısı araştırma ve aday aktarımı. Diğer projeler dahil değildir.

SiteNöbet kullanıcı/organization/notification altyapısı ortak temel olarak seçildi.
Bu değişiklik yalnızca aktarım sözleşmesidir; canlı entegrasyon değildir.

`app.lead_import.parse_import` saf doğrulayıcıdır; ağa bağlanmaz, veritabanına
veya dosyaya kişisel veri yazmaz. Organization kimliği yalnızca kimliği doğrulanmış
API bağlamından gelmelidir. Kaynak kimliği + organization için sabit aktarım anahtarı
üretir. Mail geçmişindeki accepted/sending/uncertain/rejected/deferred durumlarını
korur; geçmiş bilinmiyorsa unknown kullanır. Aktarım mail gönderim izni oluşturmaz.
Kalıcı CRM katmanı ayrıca organization + source_id unique constraint ve alıcı
tekrar kontrolünü uygulamalıdır. URL doğrulaması URL'yi indirme yetkisi değildir;
indirme gerektiğinde mevcut SSRF korumaları kullanılmalıdır.

## Kalan uygulama

1. CRM tabloları ve geriye uyumlu migration; tenant izolasyonlu import API.
2. Müşteri Avcısı tarafında kimliği doğrulanmış aktarım/outbox adaptörü.
3. YorumPilot taslakları ve insan onayı; gerçek Google bağlantısı ayrı doğrulanır.
4. Ortak panel ve tenant'a bağlı Telegram olayları; mail yalnızca tek göndericiye ait.
5. PostgreSQL, API, panel ve Telegram uçtan uca kanıtları.

30 Ekim kaynak kontrolü: LeadPilot AFK hesabı bağlantısıyla 404 döndü;
YorumPilot deposu boş. Eski uygulamalar henüz taşınmadı. SiteNöbet canlı üretim
kabulü bu belgeyle verilmez. Mevcut Müşteri Avcısı mail akışı değiştirilmez.

Doğrulama: `PYTHONPATH=backend python -m unittest discover -s backend/tests -p test_lead_import.py -v`
Dört sentetik test; gerçek mesaj yok, ücretli hizmet yok.
