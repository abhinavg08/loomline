"""Rotate the exposed local demo DB password; preserve and verify its volume.

Never prints credentials. Explicitly refuses any other project/namespace.
"""
import asyncio
import json
import secrets
import subprocess
from backend.app.config import ROOT,Settings
from backend.app.db import Database
from .release_snapshot import snapshot


async def state(config):
    db=Database(config)
    try:return {'semantic':await snapshot(db,stable=True),'physical':await snapshot(db)}
    finally:await db.close()


def main():
    config=Settings()
    if config.loom_graph_namespace!='demo' or config.falkordb_host!='127.0.0.1' or config.falkordb_port!=6379:
        raise SystemExit('Refusing rotation outside the original loopback demo deployment')
    compose=['docker','compose','--project-name','loomline','--profile','app']
    container=subprocess.check_output(compose+['ps','-q','falkordb'],cwd=ROOT,text=True).strip()
    mounts=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Mounts}}',container],text=True))
    if not any(m['Type']=='volume' and m['Name']=='loomline_graph_data' and m['Destination']=='/var/lib/falkordb/data' for m in mounts):
        raise SystemExit('Unexpected demo data mount; rotation refused')
    envfile=ROOT/'.env';original=envfile.read_text();lines=original.splitlines()
    if sum(line.startswith('FALKORDB_PASSWORD=') for line in lines)!=1:raise SystemExit('Ambiguous password configuration')
    password=secrets.token_urlsafe(36)
    updated='\n'.join('FALKORDB_PASSWORD='+password if line.startswith('FALKORDB_PASSWORD=') else line for line in lines)+'\n'
    output=ROOT/'artifacts/release';output.mkdir(parents=True,exist_ok=True)
    with (output/'local-db-rotation.log').open('w') as log:
        def run(args):subprocess.run(compose+args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        run(['stop','router','gateway'])
        before=asyncio.run(state(config))
        try:
            envfile.write_text(updated)
            run(['up','-d','--build','--wait','gateway'])
            after=asyncio.run(state(config.model_copy(update={'falkordb_password':password})))
            assert before['semantic']==after['semantic'], 'Graph state changed; investigate private snapshots'
            run(['up','-d','--wait'])
        except Exception:
            run(['stop','router','gateway'])
            envfile.write_text(original)
            run(['up','-d','--wait'])
            raise RuntimeError('Rotation failed and previous configuration restored; inspect private log') from None
    report={'status':'PASS','password_rotated':True,'data_preserved':before['semantic']==after['semantic'],'physical_ids_changed':before['physical']!=after['physical'],'volume':'loomline_graph_data','graphs':after['semantic']}
    (output/'local-db-rotation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
