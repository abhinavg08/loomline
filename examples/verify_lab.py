"""Verify framework output against authorized persisted state, not success badges."""
import argparse
import json
from pathlib import Path
from .runtime import client

def verify(report):
    assert report['status']=='PASS', 'Only completed runs can be verified'
    processes=[p for p in report['processes'] if p['status']=='PASS'];assert len(processes)==4
    assert len({p['agent_id'] for p in processes})==4 and len({p['session_id'] for p in processes})==4
    assert len({(p['host'],p['pid']) for p in processes})==4
    with client('crewai') as c:
        tenant_id=c.whoami().tenant_id
        task=report['task_id'];context=c.get_context(task,limit=20)
        memory=[*context['episodic'],*context['semantic'],*context['procedural']]
        hypothesis=next(m for m in memory if m['assertion_type']=='hypothesis')
        assert hypothesis['created_by']==report['identities']['langchain']
        if report['branch']=='upstream':assert hypothesis['status']=='disputed' and hypothesis['challenges']
        else:assert len(hypothesis['support'])>=2 and hypothesis['status']=='proposed'
        trace=c.trace(hypothesis['reference']);assert trace['source_turn']['id']==hypothesis['source_turn_id']
        assert any(h['status']=='done' and h['to_agent_id']==report['identities']['custom'] for h in context['handoffs'])
        decision=next(m for m in context['semantic'] if m['assertion_type']=='decision')
        assert decision['created_by']==report['identities']['crewai'] and decision['support']
        assert context['procedural'][0]['id'] in decision['content']
        for p in processes:
            body=p['body'];reply=body.get('model_reply') or body.get('reply')
            assert reply and reply['source_turn_id']
            turns=c.session_turns(p['session_id'])['items']
            assert any(t['id']==reply['source_turn_id'] for t in turns)
            if report['mode']=='live_nvidia':assert reply['mode']=='live_nvidia' and reply['model'] and reply['metrics']
            else:assert reply['mode']=='offline_framework_policy'
        lc=next(p for p in processes if p['framework']=='langchain')
        assert 'loomline_remember' in lc['body']['executed_tools'] and lc['body']['runtime']=='langchain.create_agent'
        lg=next(p for p in processes if p['framework']=='langgraph')
        assert lg['body']['stages']==['recall','analyze','publish_challenge' if report['branch']=='upstream' else 'publish_support']
        crew=next(p for p in processes if p['framework']=='crewai')
        assert crew['body']['runtime']=='crewai.Crew.kickoff' and 'loomline_handoff' in crew['body']['executed_tools']
        custom=next(p for p in processes if p['framework']=='custom')
        assert custom['body']['recovered_turns']>0 and len(custom['body']['recovered_classes'])==3 and custom['body']['handoff_status']=='done'
        page=c.changes_since(task,limit=100);seq=[e['seq'] for e in page['items']]
        assert seq==list(range(1,len(seq)+1)) and len({e['id'] for e in page['items']})==len(seq)
    folder=Path('artifacts/platform');folder.mkdir(parents=True,exist_ok=True)
    summary={'status':'PASS','task_id':task,'mode':report['mode'],'independent_authenticated_processes':4,'source_turns_verified':4,'hypothesis_status':hypothesis['status'],'handoff_status':'done','memory_count':len(memory),'event_count':len(seq),'storage':'real FalkorDB through public SDK'}
    (folder/('verified-'+task+'.json')).write_text(json.dumps(summary,indent=2))
    file=folder/'frameworks.json';gallery=json.loads(file.read_text()) if file.exists() else {}
    key='live' if report['mode']=='live_nvidia' else 'offline'
    for p in processes:gallery.setdefault(p['framework'],{}).update({key:'PASS','tenant_id':tenant_id,'version':p['framework_version'],key+'_task_id':task,'verification':'CLI runtime + authenticated graph provenance checks'})
    file.write_text(json.dumps(gallery,indent=2));return summary

def main():
    parser=argparse.ArgumentParser();parser.add_argument('report');args=parser.parse_args();print(json.dumps(verify(json.loads(Path(args.report).read_text())),indent=2))

if __name__=='__main__':main()
