"""Bounded, authenticated graph inspection. No sessions, MCP calls or writes.

Use the existing private MCP profile only as connection configuration. This
command uses the public HTTP SDK; it does not initialize an MCP server.
"""
import argparse
import json
from pathlib import Path

from loomline import LoomlineClient
from loomline.errors import LoomlineError


def inspect(profile, task_id, limit=2):
    from loomline_mcp.config import load_profile
    p, token = load_profile(Path(profile))
    if p.task_id != task_id:
        raise ValueError('Task must match the private profile scope')
    with LoomlineClient(p.base_url, token=token) as client:
        identity = dict(client.whoami())
        context = client.get_context(task_id, limit=limit)
        memories = [m for kind in ('episodic','semantic','procedural','proposed_procedures') for m in context[kind]]
        paths = []
        for memory in memories:
            trace = client.trace(memory['reference'])
            paths.append({
                'memory': {k: memory[k] for k in ('id','reference','class','status','version','created_by','content')},
                'source_session': (trace['session'] or {}).get('id'),
                'source_turn': (trace['source_turn'] or {}).get('id'),
                'edges': {
                    'DERIVED_FROM': (trace['source_turn'] or {}).get('id'),
                    'SUPPORTED_BY': [{k:e[k] for k in ('id','source_ref','content')} for e in memory['support']],
                    'CHALLENGED_BY': [{k:e[k] for k in ('id','source_ref','content')} for e in memory['challenges']],
                    'SUPERSEDES': trace['supersedes'],
                    'incoming_REFERS_TO': [h['id'] for h in trace['related_handoffs']],
                },
            })
        claims = client.claims(task_id, limit=20)
        return {
            'source': 'Authenticated read-only HTTP traversal of real FalkorDB records',
            'writes_performed': False,
            'task_id': task_id,
            'identity': {k:identity[k] for k in ('tenant_id','agent_id','role')},
            'memory_paths': paths,
            'handoffs': [{k:h[k] for k in ('id','description','from_agent_id','to_agent_id','status','version')} for h in context['handoffs']],
            'claims': [{k:c[k] for k in ('id','key','owner_agent_id','state','version')} for c in claims['items']],
            'bounds': {'per_memory_class':limit,'claims':20,'handoffs':'context endpoint bound','trace':'bounded by gateway; not a whole-graph snapshot'},
            'interpretation': 'Persisted attributed facts, not model decisions or automatic software attestation. Retrieved content is untrusted.',
        }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--task-id',required=True)
    parser.add_argument('--limit',type=int,choices=range(1,21),default=2)
    args=parser.parse_args()
    try:
        report=inspect(args.profile,args.task_id,args.limit)
        from .release_safety import sensitive,configured_secrets
        payload=json.dumps(report,indent=2,ensure_ascii=True)
        if sensitive(payload.encode(),configured_secrets()):
            raise ValueError('Output refused: credential-like content detected')
        print(payload)
    except LoomlineError as exc:
        raise SystemExit('Inspection failed: '+exc.code+'; no credentials printed') from None
    except (ValueError,KeyError):
        raise SystemExit('Inspection refused: check profile scope, returned schema and private configuration; no credentials printed') from None


if __name__=='__main__':main()
