"""Two separately authenticated SDK clients. Never print their credentials."""
import argparse
import os
from loomline import LoomlineClient

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',default='incident_42');args=parser.parse_args()
    url=os.environ.get('LOOM_URL','http://127.0.0.1:8000')
    with LoomlineClient(url,token=os.environ['LOOM_INVESTIGATOR_TOKEN']) as a,LoomlineClient(url,token=os.environ['LOOM_VERIFIER_TOKEN']) as b:
        with a.session(args.task) as session:
            hypothesis=session.hypothesize('Deployment might explain the synthetic errors')
        actual=b.resolve(hypothesis.reference)
        evidence=b.record_evidence(args.task,content='Synthetic upstream timeout evidence',source_type='synthetic',source_ref='synthetic:quickstart',observed_at='2026-10-17T14:02:00Z')
        challenged=b.challenge(args.task,actual.id,evidence_id=evidence.evidence_id,reason='Upstream evidence needs investigation',expected_version=actual.version)
        print({'status':'PASS','author':actual.created_by,'memory_id':actual.id,'challenge_id':challenged.event_id,'storage':'Loomline HTTP / real FalkorDB'})

if __name__=='__main__':main()
