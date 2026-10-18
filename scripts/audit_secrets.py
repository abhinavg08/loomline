"""Check publishable files for configured secrets without displaying matches."""
import json
from pathlib import Path
import re
import subprocess
from backend.app.config import settings


def main():
    paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],text=True).splitlines()
    tokens=json.loads(Path('.secrets/agent_tokens.json').read_text())
    secrets=[settings.falkordb_password,settings.nvidia_api_key,settings.nvidia_investigator_api_key,settings.nvidia_verifier_api_key,settings.nvidia_coordinator_api_key,*tokens.values()]
    findings=[];checked=0
    for name in paths:
        file=Path(name)
        if file.suffix.lower() in ('.png','.jpg','.jpeg','.webp'):continue
        try:text=file.read_text(encoding='utf-8')
        except (UnicodeError,IsADirectoryError):continue
        checked+=1
        if any(s and s in text for s in secrets) or re.search(r'nvapi-[A-Za-z0-9_-]{30,}',text):findings.append(name)
    report={'status':'FAIL' if findings else 'PASS','publishable_text_files_checked':checked,'files_with_secret_matches':findings}
    Path('artifacts/secret_audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    if findings:raise SystemExit(1)


if __name__=='__main__':main()
