"""Safe offline provider; untrusted review text is never interpreted as instructions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Analysis:
    sentiment: str
    priority: str
    category: str
    language: str
    reply_draft: str


class RuleBasedProvider:
    def analyze(self, content: str, stars: int, tone: str = 'professional') -> Analysis:
        text = content.casefold()
        if any(w in text for w in ('geç', 'bekle', 'late', 'slow')):
            category = 'wait_time'
            subject = 'bekleme süresi'
        elif any(w in text for w in ('personel', 'çalışan', 'staff')):
            category = 'staff'
            subject = 'hizmet kalitesi'
        elif any(w in text for w in ('temiz', 'kirli', 'clean')):
            category = 'cleanliness'
            subject = 'temizlik'
        elif any(w in text for w in ('fiyat', 'pahalı', 'price')):
            category = 'pricing'
            subject = 'fiyatlandırma'
        else:
            category = 'other'
            subject = 'deneyiminiz'
        complaint = any(w in text for w in ('ama', 'fakat', 'kötü', 'berbat', 'geç', 'şikayet', 'slow', 'bad', 'however', 'but', 'disappointed'))
        language = 'en' if any(w in text for w in ('the ', 'service ', 'was ', 'very ', 'staff ', 'however ')) else 'tr'
        sentiment = 'mixed' if stars >= 4 and complaint else ('negative' if stars <= 2 or complaint else 'positive' if stars >= 4 else 'neutral')
        priority = 'high' if stars <= 2 or (complaint and stars <= 3) else 'medium' if complaint else 'low'
        if language == 'en':
            reply = ('Thank you for your feedback. We are sorry your experience did not meet expectations. '
                     'We would appreciate the opportunity to review your concerns privately.' if sentiment in ('negative','mixed')
                     else 'Thank you for taking the time to share your experience. We appreciate your feedback!')
        else:
            reply = (f'Geri bildiriminiz için teşekkür ederiz. {subject.capitalize()} konusunda yaşadığınız olumsuz deneyim için üzgünüz. '
                     'Konuyu daha ayrıntılı değerlendirmek için bizimle doğrudan iletişime geçebilirsiniz.' if sentiment in ('negative', 'mixed')
                     else 'Değerli değerlendirmeniz için teşekkür ederiz. Deneyiminizi paylaştığınız için memnun olduk!')
        if tone == 'short':
            reply = reply.split('. ')[0].rstrip('.') + '.'
        return Analysis(sentiment, priority, category, language, reply)
