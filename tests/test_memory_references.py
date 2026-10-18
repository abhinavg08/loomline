import pytest
from .conftest import auth,memory

pytestmark=pytest.mark.integration

async def test_memory_reference_format_errors_are_actionable_without_scope_disclosure(client,tokens):
    created,_=await memory(client)
    ref='loom://task/incident_42/memory/'+created['memory_id']
    for path in ('/v1/resolve','/v1/trace'):
        result=await client.get(path,params={'reference':ref})
        assert result.status_code==200
        resolved=result.json()['memory'] if path.endswith('trace') else result.json()
        assert resolved['id']==created['memory_id']
        for invalid in (created['memory_id'],'loom://task/incident_42/evidence/evidence_known','loom://task/incident_42/turn/turn_known','https://invalid.example/memory'):
            bad=await client.get(path,params={'reference':invalid})
            assert bad.status_code==400 and bad.json()['error']['code']=='INVALID_MEMORY_REFERENCE'
            assert 'linked evidence' in bad.json()['error']['guidance']
            assert invalid not in str(bad.json())
        for unknown in ('loom://task/incident_42/memory/mem_nonexistent','loom://task/task_nonexistent/memory/'+created['memory_id']):
            assert (await client.get(path,params={'reference':unknown})).status_code==404
        for identity in ('beta:coordinator','alpha:unassigned'):
            denied=await client.get(path,params={'reference':ref},headers=auth(tokens,identity))
            assert denied.status_code==404 and denied.json()=={'error':{'code':'NOT_FOUND'}}
        assert (await client.get(path,params={'reference':ref},headers={'Authorization':'Bearer invalid'})).status_code==401
