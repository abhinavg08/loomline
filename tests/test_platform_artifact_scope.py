import json
import pytest
from backend.app import config
from .conftest import auth

@pytest.mark.integration
async def test_operator_proof_does_not_disclose_other_tenant_task_ids(client,tokens,tmp_path,monkeypatch):
    folder=tmp_path/'artifacts/platform';folder.mkdir(parents=True)
    (folder/'frameworks.json').write_text(json.dumps({'langchain':{'tenant_id':'alpha','live':'PASS','live_task_id':'incident_42','version':'1.4.6'}}))
    monkeypatch.setattr(config,'ROOT',tmp_path)
    own=await client.get('/v1/verification');assert own.status_code==200
    assert own.json()['results']['frameworks']['langchain']['live_task_id']=='incident_42'
    other=await client.get('/v1/verification',headers=auth(tokens,'beta:investigator'));assert other.status_code==200
    proof=other.json()['results']['frameworks']['langchain']
    assert 'live_task_id' not in proof and 'tenant_id' not in proof and proof['live']=='not available in your task scope'
