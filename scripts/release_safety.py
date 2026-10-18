"""Fail-closed source export and redacted scanning, independent of local packages."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE_DIRS={'agents','backend','scripts','tests','mcp_tests','examples','docs','packages/loomline-sdk','packages/loomline-mcp'}
ROOT_FILES={'LICENSE','.gitignore','.dockerignore','.env.example','Dockerfile','Dockerfile.integrations','Dockerfile.mcp','docker-compose.yml','environment.yml','pytest.ini','requirements.txt','requirements.lock.txt','requirements.frameworks.lock.txt','requirements.mcp.lock.txt'}
FRONT_FILES={'package.json','package-lock.json','index.html','vite.config.js'}
PROVIDER=re.compile(rb'nvapi-[A-Za-z0-9_-]{30,}')
PRODUCT_MANUALS={'README.md','START_HERE.md','FINAL_USER_ACCEPTANCE_REPORT.md','SDK_REFERENCE.md','MCP_TOOLS_REFERENCE.md','INTEGRATIONS.md'}
PRODUCT_DOCS={'AGENT_SETUP.md','STUDIO_AUTH.md','GRAPH_MODEL.md','MEMORY_GRAPH_GUIDE.md','LOOMLINE_MEMORY_CONTRACT_V0_1.md'}
PUBLIC_IMAGES={'studio-memory-graph-desktop.png','studio-collaboration-mobile.png'}


def product_allowed(name):
    """The portable product excludes historical prompts and laptop audit reports."""
    if not allowed(name):return False
    parts=PurePosixPath(name).parts
    if len(parts)==1 and name.endswith('.md'):return name in PRODUCT_MANUALS
    if parts[0]=='docs':return (len(parts)==2 and parts[1] in PRODUCT_DOCS) or (len(parts)==3 and parts[1]=='images' and parts[2] in PUBLIC_IMAGES)
    return True


def allowed(name):
    if '\\' in name or ':' in name:return False
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts:return False
    if any(part in ('.env','.secrets','.conda','.venv','node_modules','__pycache__','.git','artifacts','release','.pytest_cache') for part in p.parts):return False
    if len(p.parts)==1:return p.name in ROOT_FILES or p.suffix=='.md'
    if p.parts[0]=='docs':return p.suffix=='.md' or (len(p.parts)==3 and p.parts[1]=='images' and p.name in PUBLIC_IMAGES)
    if p.parts[0]=='packages':
        package={'loomline-sdk':'loomline','loomline-mcp':'loomline_mcp'}.get(p.parts[1])
        return package is not None and ((len(p.parts)==3 and p.name in ('pyproject.toml','README.md')) or (p.parts[2:4]==('src',package) and (p.suffix=='.py' or p.name=='py.typed')))
    if p.parts[:2]==('examples','mcp_collaboration'):return p.suffix in ('.py','.md')
    if p.parts[0] in SOURCE_DIRS:return p.suffix=='.py'
    return p.parts[0]=='frontend' and ((len(p.parts)==2 and p.name in FRONT_FILES) or (p.parts[1]=='src' and p.suffix in ('.js','.jsx','.css','.svg')))


def source_paths(root=ROOT,product=False):
    # Walk only approved trees; never traverse Conda/node_modules to discover files.
    paths=[p for p in root.iterdir() if p.is_file() and allowed(p.name)]
    for directory in (*SOURCE_DIRS,'frontend/src'):
        folder=root/directory
        if folder.exists():paths.extend(p for p in folder.rglob('*') if p.is_file() and allowed(p.relative_to(root).as_posix()))
    for name in FRONT_FILES:
        p=root/'frontend'/name
        if p.exists():paths.append(p)
    return sorted({p for p in paths if not product or product_allowed(p.relative_to(root).as_posix())})


def configured_secrets(root=ROOT):
    values=[]
    env=root/'.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            key,sep,value=line.partition('=')
            if sep and (key=='FALKORDB_PASSWORD' or key.endswith('API_KEY')) and value.strip():
                values.append(value.strip().strip('"\''))
    for name in ('agent_tokens.json','platform_tokens.json'):
        tokens=root/'.secrets'/name
        if tokens.exists():values+=json.loads(tokens.read_text()).values()
    for token in (root/'.secrets').rglob('*.token'):values.append(token.read_text().strip())
    return [s.encode() for s in values if s and len(s)>=8]


def sensitive(data,secrets):
    return bool(PROVIDER.search(data) or any(value in data for value in secrets))


def scan_source(root=ROOT,product=False):
    secrets=configured_secrets(ROOT)  # Also check original credentials in fresh exports.
    files=source_paths(root,product=product);findings=[]
    for path in files:
        if path.is_symlink() or sensitive(path.read_bytes(),secrets):findings.append(path.relative_to(root).as_posix())
    return {'status':'FAIL' if findings else 'PASS','files_checked':len(files),'sensitive_paths':findings}


def audit_runtime():
    """Scan private text evidence and built bundles; report paths/counts only.

    Provisioning files themselves are expected secret holders and excluded.
    Historical values from the known unsafe ZIP are checked without exposure.
    Screenshot contents require separate visual review, not a binary text scan.
    """
    secrets=configured_secrets();legacy=ROOT.parent/'loomline.zip'
    if legacy.exists():
        with zipfile.ZipFile(legacy) as archive:
            for entry in ('loomline/.env','loomline/.secrets/agent_tokens.json'):
                if entry not in archive.namelist():continue
                data=archive.read(entry).decode('utf-8-sig')
                if entry.endswith('.json'):secrets.extend(str(s).encode() for s in json.loads(data).values())
                else:
                    for line in data.splitlines():
                        key,sep,value=line.partition('=')
                        if sep and (key=='FALKORDB_PASSWORD' or key.endswith('API_KEY')) and len(value.strip())>=8:secrets.append(value.strip().strip('"\'').encode())
    for folder in [*(ROOT/'artifacts/release').glob('fresh_*'),*(ROOT/'artifacts/release').glob('portable install *')]:
        if folder.is_dir():secrets.extend(configured_secrets(folder))
    files=[p for p in source_paths() if p.is_file()]
    for folder in (ROOT/'artifacts',ROOT/'frontend/dist'):
        if folder.exists():files.extend(p for p in folder.rglob('*') if p.is_file() and p.suffix in ('.json','.log','.xml','.js','.css','.html') and '.secrets' not in p.parts)
    findings=[p.relative_to(ROOT).as_posix() for p in files if sensitive(p.read_bytes(),secrets)]
    return {'status':'FAIL' if findings else 'PASS','text_files_checked':len(files),'sensitive_paths':findings,'screenshots':'separate visual review required','secrets_printed':False}


def inspect_zip(path,secrets=None,product=False):
    secrets=secrets if secrets is not None else configured_secrets()
    prohibited=[];matches=[];count=0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():continue
            count+=1
            name=info.filename
            # An old whole-directory export may have one containing root folder.
            parts=PurePosixPath(name).parts
            candidates=(name,'/'.join(parts[1:])) if len(parts)>1 else (name,)
            predicate=product_allowed if product else allowed
            if not any(predicate(candidate) for candidate in candidates):prohibited.append(name)
            with archive.open(info) as stream:
                tail=b'';found=False
                while block:=stream.read(1024*1024):
                    block=tail+block
                    if sensitive(block,secrets):found=True;break
                    tail=block[-256:]
            if found:matches.append(name)
    return {'path':str(path),'status':'FAIL' if prohibited or matches else 'PASS','members':count,'prohibited_member_count':len(prohibited),'sensitive_member_count':len(matches),'sensitive_member_paths':matches,'prohibited_categories':sorted({next((part for part in PurePosixPath(n).parts if part in ('.env','.secrets','.conda','node_modules','artifacts')),PurePosixPath(n).suffix or 'other') for n in prohibited})}


def export_source(destination,product=False):
    report=scan_source(product=product)
    if report['status']!='PASS':raise RuntimeError('Source export refused: sensitive content detected; inspect redacted audit')
    destination=Path(destination).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():raise RuntimeError('Refusing to overwrite an existing export')
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in source_paths(product=product):archive.write(path,path.relative_to(ROOT).as_posix())
    result=inspect_zip(destination,product=product)
    if result['status']!='PASS':raise RuntimeError('Archive scan failed; do not distribute')
    return {**result,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'bytes':destination.stat().st_size}


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--inspect-zip');parser.add_argument('--export');parser.add_argument('--runtime',action='store_true');parser.add_argument('--product',action='store_true');args=parser.parse_args()
    report=audit_runtime() if args.runtime else inspect_zip(Path(args.inspect_zip),product=args.product) if args.inspect_zip else export_source(args.export,product=args.product) if args.export else scan_source(product=args.product)
    print(json.dumps(report,indent=2))
    if report['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
