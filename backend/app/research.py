"""OSM research adapted from owner's musteri-avcisi-ai; no messaging side effects."""
import json
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Public Overpass instances can be temporarily busy; keep requests low volume.
# All mirrors must cover Turkey (Swiss-only Overpass created false empty results).
OVERPASS_ENDPOINTS = (
    'https://overpass.private.coffee/api/interpreter',
    'https://overpass-api.de/api/interpreter',
    'https://lz4.overpass-api.de/api/interpreter',
)
DEFAULT_BBOX = '40.982,29.015,41.008,29.055'
CATEGORIES = {'car_wash': 'Oto yıkama', 'hairdresser': 'Kuaför/berber', 'beauty': 'Güzellik salonu'}


def bbox_parse(s):
    p = [float(v.strip()) for v in s.split(',')]
    if len(p) != 4 or not (-90 <= p[0] < p[2] <= 90 and -180 <= p[1] < p[3] <= 180):
        raise ValueError('SCAN_BBOX güney,batı,kuzey,doğu şeklinde olmalı')
    if p[2] - p[0] > .2 or p[3] - p[1] > .2:
        raise ValueError('Kamu sunucusuna aşırı geniş alan sorgulanamaz')
    return tuple(p)


def get_osm(bbox, opener=urlopen):
    box = ','.join(str(v) for v in bbox)
    query = ('[out:json][timeout:25];('
             f'nwr["amenity"="car_wash"]({box});'
             f'nwr["shop"="hairdresser"]({box});'
             f'nwr["shop"="beauty"]({box}););out center tags 200;')
    payload = urlencode({'data': query}).encode()
    had_empty_success = False
    for endpoint in OVERPASS_ENDPOINTS:
        req = Request(endpoint, data=payload, headers={
            'User-Agent': 'MusteriAvcisiAI/0.1 (small weekdays-only lead research)',
            'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with opener(req, timeout=25) as response:
                data = json.load(response)
            # Some mirrors send error remarks with HTTP 200; never count those
            # responses as a successful empty discovery.
            if not isinstance(data, dict) or data.get('remark'):
                continue
            elements = data.get('elements')
            if not isinstance(elements, list):
                continue
            if elements:
                return elements
            had_empty_success = True
        except HTTPError as exc:
            # Try another instance only for temporary failures.
            if exc.code not in (401, 403, 408, 429, 500, 502, 503, 504):
                raise RuntimeError(f'Overpass API HTTP {exc.code}') from None
        except (TimeoutError, URLError, OSError, ValueError, TypeError):
            # Limited sequential fallbacks only; do not retry indefinitely.
            pass
    if had_empty_success:
        # Confirmed an empty set on at least one healthy public source.
        return []
    raise RuntimeError('Overpass instances unavailable; no leads sent')


def lead_from_osm(row):
    tags = row.get('tags') or {}
    name = str(tags.get('name') or '').strip()
    typ, oid = row.get('type'), row.get('id')
    category = CATEGORIES.get(tags.get('amenity')) or CATEGORIES.get(tags.get('shop'))
    if not name or not category or typ not in ('node', 'way', 'relation') or not isinstance(oid, int):
        return None
    website = str(tags.get('website') or tags.get('contact:website') or '').strip()
    phone = str(tags.get('contact:phone') or tags.get('phone') or '').strip()
    address = ' '.join(str(tags.get(t) or '') for t in
                       ('addr:street', 'addr:housenumber', 'addr:district')).strip()
    return {'id': f'{typ}/{oid}', 'name': name[:100], 'category': category,
            'website': website[:200], 'phone': phone[:80], 'address': address[:150],
            'email': str(tags.get('contact:email') or tags.get('email') or '').strip()[:254],
            'score': 45 + (30 if not website else 0) + (15 if phone else 0) + (10 if address else 0)}


