import asyncio
import json
import time
import httpx
import pytest
from backend.app.config import Settings
from backend.app.errors import DomainError
from backend.app.nvidia import NvidiaInferenceService,RollingQuota,retry_after


def config(**values):
    return Settings(_env_file=None,nvidia_live_enabled=True,nvidia_model='test-model',nvidia_investigator_api_key='test-investigator',nvidia_verifier_api_key='test-verifier',nvidia_coordinator_api_key='test-coordinator',**values)


def completion():
    return {'id':'test','object':'chat.completion','created':1,'model':'test-model','choices':[{'index':0,'message':{'role':'assistant','content':'{"ok":true}','reasoning_content':'PRIVATE DO NOT SAVE'},'finish_reason':'stop'}]}


async def test_role_keys_one_manager_and_hidden_reasoning():
    seen=[];active=0;peak=0
    async def provider(request):
        nonlocal active,peak
        seen.append(request.headers['authorization']);active+=1;peak=max(peak,active)
        await asyncio.sleep(.01);active-=1
        payload=json.loads(request.content)
        assert payload['model']=='test-model' and payload['chat_template_kwargs']['enable_thinking'] is False
        return httpx.Response(200,json=completion())
    service=NvidiaInferenceService(config(),httpx.MockTransport(provider))
    try:
        results=await asyncio.gather(*(service.completion(r,{}) for r in ('investigator','verifier','coordinator')))
        assert set(seen)=={'Bearer test-investigator','Bearer test-verifier','Bearer test-coordinator'}
        assert all('PRIVATE' not in r for r in results) and peak<=3
        assert len(service.quota.starts)==3
    finally:await service.close()


async def test_429_retries_count_against_aggregate_budget():
    calls=0
    async def provider(request):
        nonlocal calls
        calls+=1
        if calls==1:return httpx.Response(429,headers={'Retry-After':'0'},json={'error':{'message':'quota'}})
        return httpx.Response(200,json=completion())
    service=NvidiaInferenceService(config(),httpx.MockTransport(provider))
    try:
        await service.completion('investigator',{})
        assert calls==2 and len(service.quota.starts)==2
        assert service.metrics[0]['http_status']==429 and service.metrics[1]['status']=='success'
    finally:await service.close()


@pytest.mark.parametrize('status',[401,402,403])
async def test_credential_and_credit_errors_not_retried(status):
    calls=0
    async def provider(request):
        nonlocal calls
        calls+=1
        return httpx.Response(status,json={'error':{'message':'private provider details'}})
    service=NvidiaInferenceService(config(),httpx.MockTransport(provider))
    try:
        with pytest.raises(DomainError) as error:await service.completion('verifier',{})
        assert error.value.code=='NIM_PROVIDER_'+str(status) and calls==1
    finally:await service.close()


async def test_rolling_quota_waits_and_retry_after():
    limiter=RollingQuota(2,.03)
    start=time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(3)))
    assert time.monotonic()-start>=.025
    assert retry_after({'retry-after':'5'})==5
