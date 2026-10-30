"""Side-effect-free Müşteri Avcısı -> LeadPilot import contract.

No database writes, SMTP, Telegram or network calls. Caller must authenticate the
organization and persist source identity + email history atomically.
"""
from dataclasses import dataclass
import hashlib
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class LeadImport:
    organization_id: str
    source_id: str
    name: str
    website: str | None
    email: str | None
    email_source: str | None
    delivery_state: str

    @property
    def idempotency_key(self):
        return hashlib.sha256((self.organization_id + ':musteri-avcisi:' + self.source_id).encode()).hexdigest()

    @property
    def may_send_automatically(self):
        # Import is never authorization to contact a business.
        return False


def public_https(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        raise ValueError('Invalid source URL')
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.port not in (None, 443):
            raise ValueError('Invalid source URL')
    except (ValueError, TypeError):
        raise ValueError('Invalid source URL') from None
    # This validates stored provenance only, never authorizes fetching the URL.
    return value


def parse_import(payload, organization_id):
    if not isinstance(payload, dict) or not isinstance(organization_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,36}', organization_id):
        raise ValueError('Invalid import envelope')
    if 'organization_id' in payload:
        raise ValueError('Organization must come from authenticated context')
    source_id = payload.get('id')
    if not isinstance(source_id, str) or not re.fullmatch(r'(?:node|way|relation)/[0-9]+|website/[a-f0-9]{24}', source_id):
        raise ValueError('Invalid source identity')
    name = payload.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 150 or any(ord(c) < 32 for c in name):
        raise ValueError('Invalid business name')
    email = payload.get('email') or None
    source = payload.get('email_source') or None
    if email is not None:
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ValueError('Invalid recipient')
        email = email.strip().lower()
        if not source:
            raise ValueError('Recipient provenance required')
    if source:
        source = public_https(source) if source != 'OSM business contact tag' else source
    website = public_https(payload['website']) if payload.get('website') else None
    state = payload.get('delivery_state', 'unknown')
    if state not in ('not_sent', 'accepted', 'sending', 'uncertain', 'rejected', 'deferred', 'unknown'):
        raise ValueError('Invalid delivery state')
    return LeadImport(organization_id, source_id, name.strip(), website, email, source, state)
