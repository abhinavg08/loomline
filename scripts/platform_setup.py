"""Local-only operator setup for four independently authenticated SDK agents."""
import asyncio
import json
import os
from types import SimpleNamespace
from backend.app.config import ROOT
from .provision_agent import provision

async def main():
    roles={'langchain':'investigator','langgraph':'verifier','crewai':'coordinator','custom':'verifier'}
    private=ROOT/'.secrets';tokens={}
    for framework,role in roles.items():
        agent='platform_'+framework;path=private/(agent+'.token')
        if not path.exists():await provision(SimpleNamespace(tenant='alpha',agent_id=agent,role=role,task=None))
        tokens[framework]=path.read_text().strip()
    target=private/'platform_tokens.json';target.write_text(json.dumps(tokens,indent=2))
    if os.name!='nt':target.chmod(0o600)
    print('Four private identities ready; SDK tokens saved to .secrets/platform_tokens.json, no secrets printed.')

if __name__=='__main__':asyncio.run(main())
