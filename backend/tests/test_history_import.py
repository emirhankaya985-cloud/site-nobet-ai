from app.history_import import convert


def test_legacy_frozen_recipient_and_uncertainty_preserved():
    record=convert('node/1',{'name':'Synthetic','email':'changed@example.invalid',
        '_auto_mail':{'recipient':'original@example.invalid','state':'uncertain'}},'review','org-a')
    assert record.email=='original@example.invalid'
    assert record.delivery_state=='uncertain'
    assert record.may_send_automatically is False


def test_legacy_drafts_never_become_sendable():
    record=convert('node/1',{'name':'Synthetic','_auto_mail':{'state':'draft'}},'review','org-a')
    assert record.delivery_state=='unknown'
    assert convert('node/1',{'name':'Synthetic'},'rejected','org-a').delivery_state=='rejected'


def test_legacy_delivery_feedback_preserved_as_suppressed_states():
    for state in ('failed', 'delayed'):
        record = convert('node/14', {'name':'Synthetic', '_auto_mail':{
            'recipient':'contact@example.invalid', 'state':'accepted',
            'delivery_feedback':{'state':state, 'smtp_code':'550'}}},
            'email_sent', 'org-a')
        assert record.delivery_state == state
        assert record.may_send_automatically is False


def test_legacy_reply_stops_new_contact():
    record = convert('node/15', {'name':'Synthetic', '_auto_mail':{
        'recipient':'contact@example.invalid', 'state':'accepted',
        'reply_feedback':{'state':'sender_matched_reply'}}},
        'email_sent', 'org-a')
    assert record.delivery_state == 'replied'
    assert record.may_send_automatically is False
