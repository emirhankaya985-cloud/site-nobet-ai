import unittest
from app.lead_import import parse_import


class LeadImportTests(unittest.TestCase):
    def sample(self, **kw):
        return dict(id='node/1', name='Synthetic Business', email='info@example.invalid',
                    email_source='https://example.invalid/contact', **kw)

    def test_tenant_scoped_stable_identity(self):
        a = parse_import(self.sample(), 'org-a')
        self.assertEqual(a.idempotency_key, parse_import(self.sample(), 'org-a').idempotency_key)
        self.assertNotEqual(a.idempotency_key, parse_import(self.sample(), 'org-b').idempotency_key)

    def test_import_cannot_authorize_mail_and_preserves_terminal_states(self):
        for state in ('not_sent','accepted','sending','uncertain','rejected','deferred','unknown'):
            record = parse_import(self.sample(delivery_state=state), 'org-a')
            self.assertEqual(record.delivery_state, state)
            self.assertFalse(record.may_send_automatically)

    def test_no_tenant_override_or_contact_without_provenance(self):
        bad = [self.sample(organization_id='org-b'), {**self.sample(), 'email_source':None},
               {**self.sample(), 'name':'bad\nname'}, {**self.sample(), 'id':'website/invalid'},
               self.sample(delivery_state='sent-maybe')]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_import(payload, 'org-a')

    def test_website_identity_supported_and_missing_history_is_unknown(self):
        record = parse_import({**self.sample(), 'id':'website/'+'a'*24}, 'org-a')
        self.assertEqual(record.delivery_state,'unknown')
        self.assertFalse(record.may_send_automatically)
