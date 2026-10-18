"""Real SDK HTTP, restart, isolation and capacity proof on owned disposable graphs."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
from loomline import LoomlineClient,AsyncLoomlineClient,NotFoundError,ConflictError
from .isolation import temporary_runtime
from .restart_recovery_check import start

class TimeoutOnce(httpx.HTTPTransport):
    """Real socket transport. Force one short read deadline after a sent write."""
    timed_out=False
    lookups=0
    attempted=False
    def handle_request(self,request):
        if '/operations/' in request.url.path:self.lookups+=1
        if request.method=='POST' and request.url.path.endswith('/memories') and not self.attempted:
            self.attempted=True
            request.extensions['timeout']={**request.extensions['timeout'],'read':.000001}
            try:return super().handle_request(request)
            except httpx.ReadTimeout:self.timed_out=True;raise
        return super().handle_request(request)

def main():
    folder=Path('artifacts/platform');folder.mkdir(parents=True,exist_ok=True)
    report={'status':'IN_PROGRESS','storage':'real FalkorDB, generated disposable graphs','checks':{}}
    with temporary_runtime() as config:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}';tokens=json.loads(Path(os.environ['LOOM_TOKEN_FILE']).read_text())
        with (folder/'reliability-gateway.log').open('w') as log:
            process=start(port,log,'scripts.diagnostic_gateway:app')
            try:
                with LoomlineClient(url,token=tokens['alpha:investigator']) as a,LoomlineClient(url,token=tokens['alpha:verifier']) as b,LoomlineClient(url,token=tokens['beta:investigator']) as other,LoomlineClient(url,token=tokens['alpha:unassigned']) as unassigned:
                    with a.session('incident_42') as session:
                        episode=session.observe('Synthetic public SDK reliability observation')
                        memory=b.get_memory('incident_42',episode.id)
                        assert memory.created_by==a.whoami().agent_id
                        assert b.resolve(memory.reference).id==memory.id
                        for denied in (other,unassigned):
                            try:denied.resolve(memory.reference)
                            except NotFoundError:pass
                            else:raise AssertionError('Scope denial failed')
                        report['checks']['independent_identity_exchange']='PASS'
                        report['checks']['wrong_tenant_and_unassigned_uri_denial']='PASS'
                        cursor=b.changes_since('incident_42')['next_cursor']
                        old_pid=process.pid;process.terminate();process.wait(timeout=10)
                        if os.name=='nt':time.sleep(30.1)  # Abrupt termination must honor the existing gateway lease.
                        process=start(port,log,'scripts.diagnostic_gateway:app')
                        assert old_pid!=process.pid
                        resumed=b.resume_task('incident_42');assert resumed.session_id!=session.session_id
                        assert b.get_memory('incident_42',memory.id).source_turn_id==memory.source_turn_id
                        second=session.observe('Observation after gateway restart')
                        watcher=b.watch('incident_42',cursor=cursor,max_polls=1)
                        batch=next(watcher);assert any(e['target_id']==second.id for e in batch['items'])
                        redelivery=next(b.watch('incident_42',cursor=cursor,max_polls=1));assert redelivery['items']==batch['items']
                        batch.ack();saved_cursor=batch['next_cursor'];watcher.close()
                        assert not b.changes_since('incident_42',saved_cursor)['items']
                        report['checks']['sdk_session_and_ack_cursor_gateway_restart']='PASS'
                        transport=TimeoutOnce()
                        with LoomlineClient(url,token=tokens['alpha:investigator'],transport=transport) as recovering:
                            receipt=recovering.remember('incident_42',session_id=session.session_id,source_turn_id=memory.source_turn_id,memory_class='episodic',assertion_type='observation',status='active',content='Actual SDK socket timeout recovery',operation_id='platform_timeout_probe')
                            assert transport.timed_out and transport.lookups>=1
                            assert recovering.operation_status('incident_42','platform_timeout_probe').id==receipt.id
                        report['checks']['actual_sdk_http_timeout_lookup_and_same_intent_recovery']='PASS'
                        async def parity():
                            async with AsyncLoomlineClient(url,token=tokens['alpha:verifier']) as async_b:
                                assert (await async_b.get_memory('incident_42',memory.id)).model_dump()==b.get_memory('incident_42',memory.id).model_dump()
                                assert (await async_b.changes_since('incident_42'))['items']==b.changes_since('incident_42')['items']
                        asyncio.run(parity());report['checks']['sync_async_real_http_read_parity']='PASS'
                env={**os.environ,'LOOM_URL':url,'LOOM_BENCH_REPORT':str(folder/'benchmark.json')}
                with (folder/'benchmark.log').open('w') as output:subprocess.run([sys.executable,'-m','scripts.load_test'],env=env,stdout=output,stderr=subprocess.STDOUT,check=True,timeout=240)
                benchmark=json.loads((folder/'benchmark.json').read_text());assert benchmark['status']=='PASS'
                report.update(status='PASS',benchmark=benchmark,quota='No model calls; isolated gateway live inference disabled',limits='One gateway; modifying queries serialize within each tenant graph. Local bounded measurements are not a service-level promise.')
            finally:
                process.terminate();process.wait(timeout=10)
                (folder/'reliability.json').write_text(json.dumps(report,indent=2))
    report['owned_test_graphs_cleaned']=True;(folder/'reliability.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
