"""Read-only evidence of demo graph state; emit counts/hashes, never contents."""
import asyncio
import hashlib
import json
from pathlib import Path
from backend.app.config import TENANTS
from backend.app.db import Database


async def snapshot(db,names=None,stable=False):
    existing=await db.client.list_graphs();report={}
    for name in (names or TENANTS).values():
        if name not in existing:report[name]={'exists':False};continue
        graph=db.client.select_graph(name)
        nodes=await graph.ro_query('MATCH (n) RETURN '+('n.id' if stable else 'ID(n)')+',labels(n),properties(n) ORDER BY '+('n.id' if stable else 'ID(n)'))
        edges=await graph.ro_query('MATCH (a)-[r]->(b) RETURN '+('a.id,type(r),b.id,properties(r)' if stable else 'ID(a),type(r),ID(b)')+' ORDER BY '+('a.id,type(r),b.id' if stable else 'ID(a),type(r),ID(b)'))
        canonical=[nodes.result_set,edges.result_set]
        if stable:canonical=[sorted(json.dumps(row,sort_keys=True,default=str) for row in rows) for rows in canonical]
        report[name]={'nodes':len(nodes.result_set),'relationships':len(edges.result_set),'content_sha256':hashlib.sha256(json.dumps(canonical,sort_keys=True,default=str).encode()).hexdigest()}
    return report


async def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('output');parser.add_argument('--release',action='store_true');args=parser.parse_args()
    db=Database()
    try:
        if args.release:
            if not db.config.loom_graph_namespace.startswith('release_'):raise RuntimeError('Release namespace required')
            config=await db.redis.config_get('appendonly','appendfsync','dir')
            assert config=={'appendonly':'yes','appendfsync':'always','dir':'/var/lib/falkordb/data'}
            result={'persistence':config,'graphs':await snapshot(db,db.tenants)}
        else:result=await snapshot(db)
    finally:await db.close()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':asyncio.run(main())
