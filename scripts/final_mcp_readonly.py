"""Read-only owner evidence/preservation check. Never launches a coding application."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from loomline import LoomlineClient
from loomline_mcp.config import load_profile
from .release_safety import ROOT,sensitive,configured_secrets

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def stable(value):
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in ('fetched_at','server_now_ms','server_time_ms','active')}
    if isinstance(value,list):return [stable(v) for v in value]
    return value

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['before','after'],required=True);parser.add_argument('--folder',required=True);parser.add_argument('--nl-root');args=parser.parse_args()
    folder=(ROOT/args.folder).resolve()
    if not folder.is_relative_to(ROOT/'artifacts/mcp'):raise SystemExit('Owned evidence directory required')
    raw=json.loads((folder/('owner-graph-'+args.phase+'.json')).read_text());graph=raw['graph_evidence']
    owner_task=raw['task_id'];checks=[];identities=[]
    for client in ('codex','antigravity'):
        p,token=load_profile(ROOT/'.secrets/mcp/mcp_demo'/(client+'.profile.json'))
        assert p.task_id==owner_task
        with LoomlineClient(p.base_url,token=token) as c:
            who=dict(c.whoami());c.get_context(owner_task,limit=1);identities.append(who)
            for cls in ('episodic','semantic','procedural'):
                memory=next(t['memory'] for t in graph['traces'] if t['memory']['class']==cls)
                assert c.resolve(memory['reference']).id==memory['id']
                assert c.trace(memory['reference'])['memory']['id']==memory['id']
                checks.append({'client_profile':client,'memory_class':cls,'resolve':'PASS','trace':'PASS','reference':memory['reference']})
    assert len({i['agent_id'] for i in identities})==2
    errors=[c for c in graph['calls'] if c['tool_name'] in ('loomline_resolve','loomline_trace') and c['outcome']=='error']
    metadata_fields=sorted(graph['calls'][0])
    assert 'arguments' not in metadata_fields
    files={}
    if args.nl_root:
        nl=Path(args.nl_root).resolve()
        for name in ('index.html','styles.css','script.js'):
            p=nl/name;files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((nl/'.qa').iterdir()):
            if p.is_file() and (p.suffix in ('.png','.cjs') or p.name in ('package.json','package-lock.json')):files[p.relative_to(nl).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    report={'status':'PASS','phase':args.phase,'scope':'read-only SDK/HTTP and file reads; no MCP tool invocation on owner task','owner_attestation':'User reports genuine Codex CLI + Antigravity CLI execution and fresh Codex recovery; not an automated software attestation','task_id':owner_task,'identities':identities,'same_authorized_task':True,'distinct_principals':True,'known_memories':checks,'observed_reference_errors':errors,'audit_fields':metadata_fields,'exact_original_arguments':'UNAVAILABLE in inspected task activity, explicit turns and NL QA files; arguments were not recorded','related_explicit_turns':[t for t in graph['history'] if 'evidence URI' in t.get('content','')],'memory_classes':dict(Counter(t['memory']['class'] for t in graph['traces'])),'handoff_versions':[{k:h[k] for k in ('id','from_agent_id','to_agent_id','status','version')} for h in graph['handoffs']],'owner_graph_hash':digest(stable(graph)),'nl_file_hashes':files,'nl_files_executed_or_modified':False,'coding_application_configs_read_or_modified':False}
    if args.phase=='after':
        before=json.loads((folder/'readonly-before.json').read_text())
        original_graph=json.loads((folder/'owner-graph-before.json').read_text())['graph_evidence']
        report['before_graph_normalized_hash']=digest(stable(original_graph))
        report['hash_scope']='bounded graph evidence excluding live server clock and derived lease activity; original baseline report retained'
        report['owner_graph_unchanged']=report['before_graph_normalized_hash']==report['owner_graph_hash']
        report['nl_files_unchanged']=before['nl_file_hashes']==files
        assert report['owner_graph_unchanged'] and report['nl_files_unchanged'],'Read-only evidence changed; inspect rather than reset'
    payload=json.dumps(report,indent=2)
    assert not sensitive(payload.encode(),configured_secrets()),'Evidence export refused: credential detected'
    target=folder/('readonly-'+args.phase+'.json')
    if target.exists():raise SystemExit('Refusing existing evidence')
    target.write_text(payload)
    print(json.dumps({'status':'PASS','phase':args.phase,'known_authorized_resolve_trace_checks':len(checks)*2,'identities':len(identities),'original_argument_availability':'UNAVAILABLE','nl_files_hashed':len(files),'owner_graph_unchanged':report.get('owner_graph_unchanged','after comparison pending')}))

if __name__=='__main__':main()
