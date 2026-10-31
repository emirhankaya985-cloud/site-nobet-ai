# İşletmePilot — ortak uygulama

Kapsam yalnızca dört modül: Müşteri Avcısı, LeadPilot, YorumPilot, SiteNöbet.

## Uygulanan parçalar

- Var olan kullanıcı/organization yetkilendirmesi altında kalıcı CRM ve yorum tabloları.
- Kaynak kimliği ile tekrar aktarım engeli; immutable geçmiş ve tenant izolasyonu.
- LeadPilot v0.1.8 kaynak paketinden ücretsiz niyet sınıflandırması.
- YorumPilot kaynak manifestinden ücretsiz Türkçe/İngilizce yorum analizi ve taslak.
- `/business` ortak paneli; CRM, yorum taslakları, izleme ve Telegram ayarlarına erişim.
- Günlük ortak pipeline: OSM araştırma → CRM → en fazla 5 SMTP denemesi → Telegram outbox → site izleme.
- SMTP öncesi kalıcı claim; alıcı başına unique kayıt; belirsiz/crash durumunda mail tekrar kapalı.
- Gönderilen mailin tam metni ortak bildirim outbox'ına yazılır. Telegram API makbuzu mevcut worker tarafından doğrulanır.
- Yedek slot aynı başarılı günlük mail batch'ini tekrar başlatmaz. Kaynak hatası SMTP öncesiyse güvenli tekrar mümkündür.
- Legacy geçmiş aktarımı kaynak DB'de READ ONLY transaction kullanır. Eski taslaklar otomatik mail iznine dönüşmez.

## Kaynak kökeni

LeadPilot-AI-v0.1.8-Sol-Ready(1).zip içindeki `leadpilot/engine.py` niyet kuralları;
`yorumpilot-source-manifest.jsonl` içindeki `backend/app/ai.py` yorum kuralları;
Müşteri Avcısı `leadhunter/core.py` araştırma fonksiyonları taşındı.
Özel müşteri verileri, tokenlar ve eski paketlerin bütün uygulama/veritabanları depoya taşınmadı.
Eski LeadPilot widget/billing/MFA sistemi bu ortak arayüzle entegre edilmiş sayılmaz.

## Aktivasyon sırası (henüz üretimde uygulanmadı)

1. Ana dal CI ve PostgreSQL migration testleri geçmeli.
2. Hedef mevcut uygulamada yeni migration uygulanmalı ve ortak panel açılmalı.
3. Sahip organization kimliği ve onaylı Telegram kanalı hedef DB'de mevcut olmalı.
4. Kaynak `LEGACY_REVIEW_DATABASE_URL` ve hedef `DATABASE_URL` yalnızca özel ortama tanımlanmalı.
5. `python -m app.history_import` çalıştırılmalı; aktarım sonuçları özel geçmişle karşılaştırılmalı.
6. Eski Müşteri Avcısı mail workflow'u kapatılmalı. Tek gönderici kuralı korunmalı.
7. Hedef repo Secrets: SITENOBET_DATABASE_URL, TELEGRAM_BOT_TOKEN, GMAIL_SENDER_ADDRESS, GMAIL_APP_PASSWORD.
8. Variables: BUSINESS_ORGANIZATION_ID ve kontrol sonrası BUSINESS_HISTORY_RECONCILED=true,
   LEGACY_MAIL_WORKFLOW_DISABLED=true, BUSINESS_AUTO_MAIL_ENABLED=true, BUSINESS_PIPELINE_ENABLED=true.
9. İlk gerçek schedule ve Telegram tam metin makbuzları ayrı doğrulanmalı.

`business-pipeline.yml` varsayılan kapalıdır; bu ayarlar mevcut olmadan müşteri maili göndermez.
Slotlar hafta içi 10:23 / 11:53 TRT; GitHub gecikebilir veya atlayabilir. 24/7 garanti yoktur.
SMTP kabulü gelen kutusuna teslim kanıtı değildir. Telegram outbox at-least-once'dır;
API kabulünden sonra DB commit çökerse bildirim tekrarı mümkündür.
Google resmi OAuth/işletme erişimi eski kaynakta da tamamlanmamıştır: gerçek Google
senkronizasyonu/yayınlama hâlâ kapalıdır. Yorumlar API/panel ile içe alınabilir, ücretsiz
taslak analizi çalışır. Bu sınıra rağmen tam Google otomasyonu iddia edilmez.


## 31 Ekim 2026 — güvenlik düzeltmesi ve geçiş koşulları

- İki Neon veritabanı salt-okunur sorgularla karşılaştırıldı: kaynakta 35 ve hedefte 35 kayıt; 15 accepted ve 20 unknown. Kaynak ID listesi ile 15 eski mailin alıcı, konu ve tam gövde parmak izleri eşleşiyor. Yeni mail gönderilmedi.
- Birleşik mail kodu artık kaynak workflow devre dışı onayı olmadan SMTP yapamaz. Gerçek geçiş kanıtı olmadan `LEGACY_MAIL_WORKFLOW_DISABLED=true` ayarlanmamalı.
- Günlük en fazla 5 mail claim oluşturulur (Türkiye takvim günü); PostgreSQL transaction advisory lock paralel runner'ların kotayı aşmasını engeller. Gönderimden önce commit edilir. SMTP timeout durumları `uncertain` kalır, otomatik mail tekrarına dönüşmez.
- Önceden aktarılmış mail geçmişi ve normalize edilmiş alıcı adresi ikinci gönderime engeldir. Import geçmişindeki `accepted`, `sending`, `uncertain`, `rejected` ve `deferred` durumları korunur.
- Alıcı, konu ve tam mail metnini içeren bildirim sadece doğrulanmış Telegram kanalına yazılır, ntfy'ye gönderilmez.
- Uzun Telegram raporları güvenli uzunlukta sıralı parçalara ayrılır. Her parça için `ok` ve pozitif `message_id` doğrulanır; hepsi başarıyla tamamlanınca mesaj ID'leri hedef DB'ye yazılır.
- Telegram gönderiminin ortasında bağlantı koparsa rapor tekrarında bazı parçalar iki kez görülebilir. SMTP yeniden gönderilmez; API makbuzu okundu bilgisi değildir.
- Panel DB'den Telegram doğrulama durumunu, CRM, mail geçmişi ve batch sayaçlarını gösterir. Gmail/Actions sırları API tarafından görülmediği için SMTP hazır durumunu doğrulandı gibi sunmaz.
- YorumPilot'un Google OAuth/API erişimi hâlâ yok; manuel taslaklar gerçek Google senkronizasyonu değildir.

### Kontrollü tek gönderici aktivasyonu (henüz gerçekleştirilmedi)

1. Ana repo PR CI, PostgreSQL migration, frontend test ve prod dağıtımı doğrulansın.
2. Hedef repo Actions Secrets ekranına kullanıcı mevcut Gmail + Telegram değerlerini doğrudan ve gizli şekilde girsin. Kayıtlı eski repo secret değerleri okunamaz.
3. Panelden owner login ile 10 dakika geçerli Telegram bağlantı kodu oluşturulup sahibin **özel** sohbetinde doğrulansın. Başka sohbet kaynak geçmişinden tahmin edilmesin.
4. Önceki depoda otomatik `lead-digest.yml`, manuel SMTP `execute-outreach.yml`, `verified-mail-batch.yml` ve Telegram butonundan SMTP üretebilen yol kontrol edilip tek göndericiye geçiş için engellensin. Yeni gönderici aynı anda açık olmasın.
5. Yeniden salt-okunur kaynak-hedef karşılaştırması ve geri dönüş kopyası sonrası, yalnızca gerçek kanıtla HISTORY_RECONCILED ve LEGACY_MAIL_WORKFLOW_DISABLED bayrakları açılabilir.
6. Yeni gerçek işletmelere SMTP gönderimi ancak ayrıca açık kullanıcı izniyle aktifleştirilsin. İlk gerçek schedule olayı, kalıcı claim ve Telegram receipt ID'leri ayrı ayrı kontrol edilsin.

Bu belgedeki geliştirmeler ve CI testleri canlı otomasyon kanıtı değildir.
