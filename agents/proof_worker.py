import json
import os
import sys
from .shared_client import AgentClient


def main():
    role=sys.argv[1]
    c=AgentClient(role)
    sid=c.session()
    if len(sys.argv)>2:
        m=c.request('GET',c.task_path+'/memories/'+sys.argv[2])
        assert m['created_by'] != role and m['source_turn_id'] and m['class']=='episodic'
    tid=c.turn(sid,'Synthetic '+role+' observation','tool')
    result,body=c.remember(sid,tid,'Synthetic '+role+' shared memory')
    assert c.request('POST',c.task_path+'/memories',json=body)==result
    print(json.dumps({'pid':os.getpid(),'role':role,'session_id':sid,**result}),flush=True)
    if role=='investigator':
        reply=json.loads(sys.stdin.readline())
        m=c.request('GET',c.task_path+'/memories/'+reply['memory_id'])
        assert m['created_by']=='verifier'
        print(json.dumps({'pid':os.getpid(),'read_reply':True}),flush=True)


if __name__=='__main__':
    main()
