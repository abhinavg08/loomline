"""Real HTTP/FalkorDB workload; never invokes NVIDIA inference."""
import asyncio
import json
import math
import os
from pathlib import Path
import platform
import statistics
import time
import uuid
import httpx


def uid():return 'load_'+uuid.uuid4().hex


async def main():
    from backend.app.config import settings
    import hashlib
    if not settings.loom_graph_namespace.startswith(('bench_','test_','release_')):
        raise SystemExit('Refusing benchmark in demo namespace. Use the isolated release/benchmark deployment.')
    tokens=json.loads(Path(os.environ.get('LOOM_TOKEN_FILE','.secrets/agent_tokens.json')).read_text())
    report_path=Path(os.environ.get('LOOM_BENCH_REPORT','artifacts/benchmark.json'));report_path.parent.mkdir(parents=True,exist_ok=True)
    base=os.environ.get('LOOM_URL','http://127.0.0.1:8000')
    async with httpx.AsyncClient(base_url=base,timeout=60,limits=httpx.Limits(max_connections=64,max_keepalive_connections=64)) as c:
        health=(await c.get('/health')).json()
        if health.get('namespace_id')!=hashlib.sha256(settings.loom_graph_namespace.encode()).hexdigest()[:16]:
            raise SystemExit('HTTP and database namespace mismatch; no workload executed')
        sources={};headers={};memories={}
        for tenant in ('alpha','beta'):
            h={'Authorization':'Bearer '+tokens[tenant+':investigator']};headers[tenant]=h
            s=await c.post('/v1/tasks/incident_42/sessions',headers=h,json={'operation_id':uid()});s.raise_for_status();sid=s.json()['session_id']
            t=await c.post(f'/v1/sessions/{sid}/turns',headers=h,json={'operation_id':uid(),'role':'tool','content':'Synthetic load-test source'});t.raise_for_status()
            sources[tenant]={'session_id':sid,'source_turn_id':t.json()['turn_id'],'class':'episodic','assertion_type':'observation','status':'active','content':'Synthetic load-test memory'}
            m=await c.post('/v1/tasks/incident_42/memories',headers=h,json={**sources[tenant],'operation_id':uid()});m.raise_for_status();memories[tenant]=m.json()['memory_id']
        report={'hardware':{'platform':platform.platform(),'logical_cpus':os.cpu_count()},'workloads':{}}
        async def run(name,count,concurrency,chooser):
            slots=asyncio.Semaphore(concurrency);samples={'read':[],'write':[]};statuses={};intent_ids=[];bad_payloads=[]
            async def one(i):
                tenant,kind=chooser(i);h=headers[tenant]
                async with slots:
                    started=time.perf_counter()
                    if kind=='read':
                        response=await c.get('/v1/tasks/incident_42/memories/'+memories[tenant],headers=h)
                        if response.status_code==200 and response.json()['created_by']!=('investigator' if tenant=='alpha' else 'beta_investigator'):bad_payloads.append(True)
                    else:
                        intent=uid();intent_ids.append((tenant,intent))
                        response=await c.post('/v1/tasks/incident_42/memories',headers=h,json={**sources[tenant],'operation_id':intent})
                    samples[kind].append((time.perf_counter()-started)*1000)
                    statuses[str(response.status_code)]=statuses.get(str(response.status_code),0)+1
            started=time.perf_counter();await asyncio.gather(*(one(i) for i in range(count)));elapsed=time.perf_counter()-started
            stats={}
            for kind,values in samples.items():
                if values:
                    ordered=sorted(values);stats[kind]={'count':len(values),'p50_ms':round(statistics.median(values),2),'p95_ms':round(ordered[math.ceil(len(ordered)*.95)-1],2)}
            errors=sum(n for code,n in statuses.items() if code not in ('200','201'))
            report['workloads'][name]={'requests':count,'concurrency':concurrency,'seconds':round(elapsed,3),'requests_per_second':round(count/elapsed,2),'statuses':statuses,'error_responses':errors,'429':statuses.get('429',0),'500':statuses.get('500',0),'tenant_payload_violations':len(bad_payloads),**stats}
            # Retain completed workload evidence even if a later workload fails.
            report_path.write_text(json.dumps(report,indent=2))
            return intent_ids
        await run('50_readers',1000,50,lambda i:('alpha','read'))
        await run('20_writers',200,20,lambda i:('alpha','write'))
        await run('mixed_70_30_two_tenants',1000,50,lambda i:('alpha' if i%2 else 'beta','read' if i%10<7 else 'write'))
        body={**sources['alpha'],'operation_id':uid()}
        storm=await asyncio.gather(*(c.post('/v1/tasks/incident_42/memories',headers=headers['alpha'],json=body) for _ in range(20)))
        assert all(r.status_code in (200,201) for r in storm),[r.text for r in storm]
        assert len({r.json()['memory_id'] for r in storm})==1 and len({r.json()['event_id'] for r in storm})==1
        report['duplicate_storm']={'attempts':20,'distinct_results':1,'created_responses':sum(r.status_code==201 for r in storm)}
        # Inspect the authoritative graph after HTTP writes; no missing outbox entries.
        from backend.app.db import Database
        from backend.app.auth import TokenAuthenticator
        db=Database()
        try:
            violations={}
            for tenant in ('alpha','beta'):
                p=TokenAuthenticator().authenticate(tokens[tenant+':investigator'])
                rows=await db.query(p,"MATCH (m:Memory) OPTIONAL MATCH (e:MemoryEvent {type:'MEMORY_CREATED'})-[:RECORDS]->(m) WITH m,count(e) AS n WHERE n<>1 RETURN count(m) AS violations")
                violations[tenant]=rows[0]['violations']
                assert violations[tenant]==0
            report['missing_or_duplicate_creation_events']=violations
        finally:await db.close()
        report['status']='FAIL' if any(w['error_responses'] or w['tenant_payload_violations'] for w in report['workloads'].values()) else 'PASS'
        report_path.write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        if report['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
