import pytest
from .conftest import source,uid,auth

pytestmark=pytest.mark.integration


async def test_cross_session_cursor_and_secret_redaction(client,tokens):
    s1,t1=await source(client)
    s2,t2=await source(client)
    secret='test_'+('x'*38)  # Synthetic bearer-shaped value, never an active credential.
    response=await client.post(f'/v1/sessions/{s2}/turns',json=dict(operation_id=uid(),role='tool',content='Synthetic nvapi-example-secret Bearer opaque '+secret))
    assert response.status_code==201
    turns=(await client.get(f'/v1/sessions/{s2}/turns')).json()['items']
    assert secret not in turns[-1]['content'] and 'nvapi-example' not in turns[-1]['content']
    first=(await client.get('/v1/tasks/incident_42/turns',params={'limit':2})).json()
    second=(await client.get('/v1/tasks/incident_42/turns',params={'limit':2,'before':first['next_cursor']})).json()
    assert first['items'][0]['id']==response.json()['turn_id']
    assert first['items'][1]['id']==t2 and second['items'][0]['id']==t1
    assert not ({u['id'] for u in first['items']}&{u['id'] for u in second['items']})
    assert (await client.get('/v1/tasks/incident_42/turns',params={'before':'bad cursor'})).status_code==400
    assert (await client.get('/v1/tasks/incident_42/turns',headers=auth(tokens,'alpha:unassigned'))).status_code==404
