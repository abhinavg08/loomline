import React,{useEffect,useRef,useState} from 'react';
import {Code,RecordId} from './StudioRecords';

const asData=result=>result?.data??result;
const mergeById=(before,after)=>[...new Map([...before,...after].map(item=>[item.id,item])).values()];
const eventKey=item=>item.type+':'+item.id;
const mergeEvents=(before,after)=>[...new Map([...before,...after].map(item=>[eventKey(item),item])).values()];
const statusClass=value=>String(value||'unknown').toLowerCase().replace(/[^a-z0-9_-]/g,'_');
const human=value=>String(value||'Unknown').replaceAll('_',' ').replace(/\b\w/g,char=>char.toUpperCase());
const localTime=value=>{const parsed=new Date(value);return value&&!Number.isNaN(parsed.getTime())?parsed.toLocaleString():'Time not recorded'};
const dateValue=value=>value&&!Number.isNaN(new Date(value).getTime())?value:undefined;
const safeError=error=>({
 UNAUTHENTICATED:'The identity is no longer authenticated. Reconnect with an enabled private credential.',
 NOT_FOUND:'This project is absent or unavailable to your identity. Choose an authorized project.',
 TASK_SCOPED_PRINCIPAL:'This credential is restricted to existing projects. Ask the local operator to create the new project.',
 FORBIDDEN:'This operation is not permitted for your identity.',
 READ_ONLY_IDENTITY:'This is a read-only identity. Ask your operator for the permitted working identity.',
 IDEMPOTENCY_CONFLICT:'This intent already has different recorded input. Restore the original input to retry, or start a deliberate new project.',
 INVALID_CURSOR:'The page cursor no longer matches this view. Refresh the list and try again.',
 INVALID_INPUT:'Check the project name, description and selected identities.',
}[error?.message]||'The request could not finish. Check the gateway, then retry. Retrying unchanged project input keeps the same intent ID.');

function Badge({value,children}){
 return <span className={'st-stamp '+statusClass(value)}>{children||String(value||'unknown').replaceAll('_',' ')}</span>;
}

function Failure({message,onRetry}){
 return message?<div role="alert" className="st-alert"><span>{message}</span>{onRetry&&<button type="button" onClick={onRetry}>Retry</button>}</div>:null;
}

export function Projects({tasks=[],selected,agents=[],me,api,onSelect,onCreated}){
 const apiRef=useRef(api);apiRef.current=api;
 const generation=useRef(0),intent=useRef(null);
 const [projects,setProjects]=useState(tasks),[next,setNext]=useState(null),[loading,setLoading]=useState(false),[listError,setListError]=useState('');
 const [search,setSearch]=useState(''),[status,setStatus]=useState('all'),[showCreate,setShowCreate]=useState(!tasks.length);
 const [name,setName]=useState(''),[description,setDescription]=useState(''),[projectStatus,setProjectStatus]=useState('active'),[assigned,setAssigned]=useState([]);
 const [creating,setCreating]=useState(false),[createError,setCreateError]=useState(''),[notice,setNotice]=useState('');
 const canCreate=me?.role==='coordinator'&&me?.can_create_projects!==false;
 const availableAgents=[...new Map(agents.filter(agent=>agent.id!==me?.agent_id).map(agent=>[agent.id,agent])).values()];

 async function fetchProjects(append=false){
  const version=++generation.current;setLoading(true);setListError('');
  const params=new URLSearchParams({limit:'20'});
  if(append&&next)params.set('after',next);
  try{
   const result=asData(await apiRef.current('/tasks?'+params));
   if(version!==generation.current)return;
   setProjects(old=>append?mergeById(old,result.items):result.items);setNext(result.next_cursor);
  }catch(error){if(version===generation.current)setListError(safeError(error))}
  finally{if(version===generation.current)setLoading(false)}
 }
 useEffect(()=>{intent.current=null;fetchProjects();return()=>{generation.current++}},[me?.tenant_id,me?.agent_id]);

 async function createProject(event){
  event.preventDefault();if(!canCreate||creating)return;
  setCreating(true);setCreateError('');setNotice('');
  const input={title:name.trim(),...(description.trim()?{description:description.trim()}:{}),status:projectStatus,
   assigned_agent_ids:[...new Set([me.agent_id,...assigned])].sort(),synthetic:false,template:'blank'};
  const signature=JSON.stringify(input);
  if(intent.current?.signature!==signature)intent.current={signature,body:{operation_id:'studio_project_'+crypto.randomUUID(),...input}};
  let committed;
  try{
   committed=asData(await apiRef.current('/tasks',{method:'POST',body:intent.current.body}));
  }catch(error){setCreateError(safeError(error));setCreating(false);return}
  intent.current=null;setName('');setDescription('');setAssigned([]);setCreating(false);
  setNotice('Project created. Its own tenant and task permissions are enforced by the server.');
  await fetchProjects();
  try{await onCreated?.(committed.task_id)}catch{setNotice('Project created, but the workspace could not refresh. Select it from the refreshed list or reconnect.');}
 }

 const term=search.trim().toLocaleLowerCase();
 const visible=projects.filter(project=>(status==='all'||project.status===status)&&(!term||[project.title,project.description,project.id].some(value=>String(value||'').toLocaleLowerCase().includes(term))));
 const knownStatuses=[...new Set(['open','active','completed','archived',...projects.map(project=>project.status).filter(Boolean)])];

 return <div className="ll-project-experience">
  <section className="st-panel ll-project-welcome"><div><span className="st-number">YOUR SHARED WORK</span><h2>Projects, with a memory.</h2><p>Open a project to see what your agents learned, where that knowledge came from and what happens next.</p></div>{canCreate&&<button className="st-primary" type="button" aria-expanded={showCreate} aria-controls="new-project-form" onClick={()=>setShowCreate(value=>!value)}>{showCreate?'Close project form':'+ New project'}</button>}</section>
  {me?.role==='viewer'&&<p className="st-viewer-note">Read-only access. You can explore your authorized projects, shared memories and handoffs.</p>}
  {me?.role==='coordinator'&&me?.can_create_projects===false&&<p className="st-help">This coordinator identity is project-scoped. The local operator creates new projects and grants access.</p>}
  {notice&&<p role="status" className="st-notice">{notice}</p>}
  {canCreate&&showCreate&&<section className="st-panel ll-project-create" id="new-project-form"><h2>Create a named project</h2><p>Start with a blank shared record. Connect each contributing agent with its own scoped identity.</p><Failure message={createError}/><form onSubmit={createProject}>
   <label htmlFor="project-name">Project name</label><input id="project-name" value={name} maxLength={200} disabled={creating} required placeholder="Website collaboration" onChange={event=>setName(event.target.value)}/>
   <label htmlFor="project-description">What are you working toward?</label><textarea id="project-description" value={description} maxLength={1000} disabled={creating} rows={3} placeholder="Shared objective and the evidence your team will preserve" onChange={event=>setDescription(event.target.value)}/>
   <label htmlFor="project-status">Project status</label><select id="project-status" value={projectStatus} disabled={creating} onChange={event=>setProjectStatus(event.target.value)}>{['open','active','completed','archived'].map(value=><option key={value} value={value}>{human(value)}</option>)}</select>
   {!!availableAgents.length&&<details><summary>Authorize existing identities</summary><p>Your own identity is included. Choose up to 19 additional identities already visible in the selected project; this is not a directory of another tenant.</p><div className="ll-project-assignments">{availableAgents.map(agent=><label key={agent.id}><input type="checkbox" checked={assigned.includes(agent.id)} disabled={creating||(!assigned.includes(agent.id)&&assigned.length>=19)} onChange={event=>setAssigned(old=>event.target.checked?[...old,agent.id]:old.filter(id=>id!==agent.id))}/><span>{agent.name||agent.id}<small>{agent.role}</small></span></label>)}</div></details>}
   <div className="st-actions"><button type="submit" className="st-primary" disabled={creating||!name.trim()}>{creating?'Creating project…':'Create project'}</button></div><p className="st-help">You can provision new, task-restricted agent identities afterward in Connect Your Agent. Unchanged retries use the same intent; changing fields starts a new intent.</p>
  </form></section>}
  <section className="st-panel ll-project-browser" aria-busy={loading}>
   <div className="st-panel-heading"><h2>Choose a project</h2><button type="button" disabled={loading} onClick={()=>fetchProjects()}>Refresh projects</button></div>
   <div className="ll-project-search"><label>Find a project<input type="search" aria-label="Search projects" value={search} placeholder="Search name or description" onChange={event=>setSearch(event.target.value)}/></label><label>Status<select aria-label="Filter project status" value={status} onChange={event=>setStatus(event.target.value)}><option value="all">All statuses</option>{knownStatuses.map(value=><option key={value} value={value}>{human(value)}</option>)}</select></label></div>
   <Failure message={listError} onRetry={()=>fetchProjects()}/>
   {!projects.length&&loading&&<p role="status">Reading authorized projects…</p>}
   {!projects.length&&!loading&&!listError&&<div className="st-empty"><h3>Your first shared project starts here.</h3><p>{canCreate?'Give it a useful name, then connect an agent and record the first memory.':'No projects are assigned to this identity yet. Ask your operator to authorize the intended project.'}</p>{canCreate&&<button type="button" onClick={()=>setShowCreate(true)}>Create your first project</button>}</div>}
   {!!projects.length&&!visible.length&&<div className="st-empty"><h3>No loaded projects match.</h3><p>Try another name or status. Search applies to loaded pages; more authorized projects may be available below.</p><button type="button" onClick={()=>{setSearch('');setStatus('all')}}>Clear filters</button></div>}
   <div className="ll-project-grid">{visible.map(project=><article key={project.id} className={'ll-project-card'+(project.id===selected?' current':'')}><div className="ll-project-card-heading"><Badge value={project.status}/>{project.synthetic||project.demo_run?<Badge value="synthetic">Explicit synthetic project</Badge>:null}</div><h3><button type="button" className="st-text-button" onClick={()=>onSelect?.(project.id)}>{project.title||'Untitled project'} <span aria-hidden="true">→</span></button></h3><p>{project.description||'A shared workspace for source-linked knowledge and coordinated work.'}</p><small>Created <time dateTime={dateValue(project.created_at)}>{localTime(project.created_at)}</time></small><details><summary>Project details</summary><RecordId value={project.id} label="Copy project identifier"/><p>The API calls this project a Task. Its identifier and existing memory references remain unchanged.</p></details></article>)}</div>
   <div className="ll-project-pagination"><small>{projects.length} authorized projects loaded. Filters apply to these pages.</small>{next&&<button type="button" disabled={loading} onClick={()=>fetchProjects(true)}>{loading?'Loading…':'Load more projects'}</button>}</div>
  </section>
 </div>;
}

const toolTitles={loomline_get_context:'Retrieved shared context',loomline_recall:'Searched shared memories',loomline_trace:'Inspected memory provenance',loomline_resolve:'Resolved a shared memory',loomline_resume_task:'Requested fresh-session recovery',loomline_get_history:'Retrieved explicit history',loomline_remember:'Recorded typed memory',loomline_record_turn:'Recorded an explicit turn',loomline_handoff:'Created a handoff',loomline_accept_handoff:'Accepted a handoff',loomline_complete_handoff:'Completed a handoff',loomline_challenge:'Challenged a claim',loomline_support:'Added supporting evidence',loomline_add_evidence:'Recorded evidence',loomline_claim_work:'Requested a work claim',loomline_release_work:'Released a work claim'};
const eventTitles={MEMORY_CREATED:'Created a shared memory',MEMORY_CHALLENGED:'Challenged a hypothesis',MEMORY_SUPPORTED:'Added supporting evidence',MEMORY_STATUS_CHANGED:'Changed memory status',HANDOFF_CREATED:'Created a handoff',HANDOFF_UPDATED:'Updated a handoff',WORK_CLAIMED:'Claimed a work area',WORK_RELEASED:'Released a work claim'};
function eventTitle(item){
 const properties=item.properties||{};
 if(item.type==='Memory')return 'Recorded '+(properties.assertion_type==='hypothesis'?'a hypothesis':properties.assertion_type==='decision'?'a decision':properties.class==='procedural'?'a procedure':properties.class==='episodic'?'an observation':'a semantic memory');
 if(item.type==='MCPCall')return properties.outcome==='error'?'Unsuccessful tool call · '+human(properties.tool_name):(toolTitles[properties.tool_name]||'Called '+human(properties.tool_name));
 if(item.type==='Session')return 'Started a recorded session';
 if(properties.type==='HANDOFF_UPDATED')return ({accepted:'Accepted a handoff',done:'Completed a handoff',cancelled:'Cancelled a handoff'}[properties.new_status]||'Updated a handoff');
 return eventTitles[properties.type]||item.title||human(item.type);
}
const diagnostic=item=>item.type==='MCPCall'&&!toolTitles[item.properties?.tool_name];

export function CollaborationOverview({task,projectName,api,onTrace,onConnect,onGraph,refreshKey}){
 const apiRef=useRef(api);apiRef.current=api;
 const generation=useRef(0),previousScope=useRef('');
 const [data,setData]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[actor,setActor]=useState(''),[origin,setOrigin]=useState('all'),[diagnostics,setDiagnostics]=useState(false);
 async function fetchOverview(append=false){
  if(!task)return;
  const version=++generation.current;setLoading(true);setError('');
  const params=new URLSearchParams({limit:'30'});if(actor)params.set('agent_id',actor);if(append&&data?.next_cursor)params.set('before',data.next_cursor);
  try{
   const result=asData(await apiRef.current('/tasks/'+encodeURIComponent(task)+'/collaboration?'+params));
   if(version!==generation.current)return;
   setData(old=>append&&old?{...result,timeline:mergeEvents(old.timeline,result.timeline)}:result);
  }catch(failure){if(version===generation.current)setError(safeError(failure))}
  finally{if(version===generation.current)setLoading(false)}
 }
 useEffect(()=>{setData(null);setActor('');setOrigin('all');setDiagnostics(false);return()=>{generation.current++}},[task]);
 useEffect(()=>{const scope=JSON.stringify([task,actor]);if(previousScope.current!==scope){setData(null);previousScope.current=scope}fetchOverview();return()=>{generation.current++}},[task,actor,refreshKey]);
 const contributors=data?.contributors||[],authorized=data?.authorized_agents||[];
 const actorOptions=[...new Set([...authorized.map(agent=>agent.id),...contributors.map(agent=>agent.id),actor].filter(Boolean))];
 const events=(data?.timeline||[]).filter(item=>(origin==='all'||(origin==='test')===(item.classification==='explicit_synthetic_or_test'))&&(diagnostics||!diagnostic(item)));
 const recordedCount=(data?.timeline||[]).filter(item=>item.classification!=='explicit_synthetic_or_test').length;
 const testCount=(data?.timeline||[]).length-recordedCount;
 const name=data?.task?.title||projectName||'Shared project';
 return <div className="ll-project-experience ll-collaboration" aria-busy={loading}>
  <section className="st-panel ll-collaboration-hero"><div><span className="st-number">COLLABORATION OVERVIEW</span><h2>{name}</h2><p>{data?.task?.description||'Follow the knowledge your agents recorded and the work they coordinated.'}</p><div className="st-actions"><Badge value={data?.task?.status||'open'}/>{data?.task?.synthetic||data?.task?.demo_run?<Badge value="synthetic">Explicit synthetic project</Badge>:null}</div></div><div className="st-actions"><button className="st-primary" type="button" onClick={onGraph}>Explore Memory Graph →</button>{onConnect&&<button type="button" onClick={onConnect}>Connect an agent</button>}</div></section>
  <Failure message={error} onRetry={()=>fetchOverview()}/>
  {!data&&loading&&<section className="st-panel"><p role="status">Reading persisted collaboration records…</p></section>}
  {data&&<>
   <section className="ll-collaboration-metrics" aria-label="Recorded collaboration facts"><article><strong>{data.counts.contributors}</strong><h3>Contributors</h3><p>Recorded turns, memories, tool calls or changes.</p></article><article><strong>{data.counts.authorized_agents}</strong><h3>Authorized identities</h3><p>Allowed to access this project; some may not have contributed.</p></article><article><strong>{data.counts.sessions}</strong><h3>Historical sessions</h3><p>Persisted executions, not a live presence count.</p></article></section>
   {data.bounds?.aggregates_truncated&&<p className="st-notice">Identity aggregates reached their limit of {data.bounds.agent_aggregate_limit}. Counts describe the returned bounded aggregate, not an entire tenant.</p>}
   <section className="st-panel ll-contributor-section"><div className="st-panel-heading"><div><span className="st-number">PEOPLE BEHIND THE RECORDS</span><h2>Who has contributed?</h2></div><button type="button" disabled={loading} onClick={()=>fetchOverview()}>Refresh activity</button></div>
    {contributors.length?<div className="ll-contributor-grid">{contributors.map(agent=><article key={agent.id} className="ll-contributor"><h3>{authorized.find(member=>member.id===agent.id)?.name||agent.id}</h3><p>{agent.counts.memories} memories · {agent.counts.turns} explicit turns · {agent.counts.mcp_calls} tool calls</p><small>{agent.currently_authorized?'Currently authorized':'Historical contributor; not currently authorized'}</small><small>Last recorded: <time dateTime={dateValue(agent.counts.last_activity_at)}>{localTime(agent.counts.last_activity_at)}</time></small><button type="button" onClick={()=>setActor(agent.id)}>Show recorded activity</button></article>)}</div>:<div className="st-empty"><h3>The shared story is ready to begin.</h3><p>No contribution is recorded yet. Connecting an identity alone does not create shared memories.</p>{onConnect&&<button type="button" onClick={onConnect}>Connect your first agent</button>}</div>}
    <details><summary>Authorized identities ({authorized.length})</summary><p>Assignment grants access; it does not prove that an agent contributed or is connected now.</p><div className="ll-authorized-identities">{authorized.map(agent=><article key={agent.id}><div><strong>{agent.name||agent.id}</strong><small>{agent.role} · {agent.contributor?'Recorded contributor':'No contribution recorded'}</small></div><Badge value={agent.contributor?'active':'authorized'}>{agent.contributor?'Has recorded activity':'Authorized only'}</Badge></article>)}</div></details>
    <p className="st-help">Identity names and framework metadata do not attest a coding application. A real-client verification is separate from these persisted records.</p>
   </section>
   <section className="st-panel ll-collaboration-timeline"><div className="st-panel-heading"><div><span className="st-number">THE EVOLVING SHARED RECORD</span><h2>Collaboration timeline</h2><p>Latest first. Expand an event to inspect its source and evidence basis.</p></div><button type="button" onClick={onGraph}>Follow graph paths →</button></div>
    <div className="ll-timeline-filters"><label>Agent<select aria-label="Timeline agent" value={actor} onChange={event=>setActor(event.target.value)}><option value="">All recorded authors</option>{actorOptions.map(id=><option key={id} value={id}>{id}</option>)}</select></label><label>Activity origin<select aria-label="Timeline activity origin" value={origin} onChange={event=>setOrigin(event.target.value)}><option value="all">All stored records</option><option value="recorded">Not explicitly marked test</option><option value="test">Explicit synthetic / test records</option></select></label><label className="ll-diagnostics-toggle"><input type="checkbox" checked={diagnostics} onChange={event=>setDiagnostics(event.target.checked)}/>Include other protocol diagnostics</label></div>
    <p className="st-help">Origin uses stored synthetic project markers or explicit TEST-CLIENT text. “Not marked test” is not proof of a real application. {recordedCount} unmarked and {testCount} explicitly marked records in the loaded pages.</p>
    {!events.length&&<div className="st-empty"><h3>{data.timeline.length?'No loaded events match these filters.':'No timeline events yet.'}</h3><p>{data.timeline.length?'Change the filter, include diagnostics or load another page.':'Ask an authorized agent to record a source-linked observation, then inspect its graph.'}</p></div>}
    <ol className="ll-timeline-list">{events.map(item=><li key={eventKey(item)} className={'ll-timeline-item '+(item.classification==='explicit_synthetic_or_test'?'test-record':'')}><div className="ll-timeline-marker" aria-hidden="true">{item.type==='Memory'?'◇':item.type==='Session'?'↺':item.type==='MCPCall'?'↗':'•'}</div><article><div className="ll-timeline-meta"><strong>{item.actor_id||'Actor not recorded'}</strong><time dateTime={dateValue(item.at)} title={item.at||undefined}>{localTime(item.at)}</time>{item.classification==='explicit_synthetic_or_test'&&<Badge value="synthetic">Explicit test / synthetic</Badge>}</div><h3>{eventTitle(item)}</h3>{item.summary&&<p className="ll-timeline-summary">{item.summary.length>450?item.summary.slice(0,450)+'…':item.summary}</p>}{item.type==='Memory'&&<div className="st-actions"><Badge value={item.properties.class}/><Badge value={item.properties.status}/></div>}{item.properties.new_status&&<p className="ll-timeline-transition">{item.properties.old_status?human(item.properties.old_status)+' → ':''}{human(item.properties.new_status)}{item.properties.new_version?' · version '+item.properties.new_version:''}</p>}
      <div className="st-actions">{item.memory_id&&<button type="button" onClick={()=>onTrace?.({id:item.memory_id,reference:item.provenance_ref||`loom://task/${task}/memory/${item.memory_id}`})}>Inspect memory provenance →</button>}</div>
      <details><summary>Inspect the recorded evidence</summary>{item.summary&&<p className="ll-timeline-full-text">{item.summary}</p>}<p className="st-help">{item.evidence_basis}</p><dl className="ll-record-facts"><dt>Record type</dt><dd>{human(item.type)}</dd><dt>Record ID</dt><dd><RecordId value={item.record_id||item.id}/></dd>{item.session_id&&<><dt>Session</dt><dd><RecordId value={item.session_id}/></dd></>}{item.provenance_ref&&<><dt>Memory reference</dt><dd><RecordId value={item.provenance_ref} label="Copy timeline memory reference"/></dd></>}</dl><details><summary>Technical record properties</summary><Code>{JSON.stringify(item.properties,null,2)}</Code></details></details>
    </article></li>)}</ol>
    <div className="ll-timeline-pagination"><small>{data.timeline.length} stored records loaded. Each request reads at most 30 timeline items.</small>{data.next_cursor&&<button type="button" disabled={loading} onClick={()=>fetchOverview(true)}>{loading?'Reading older records…':'Load older activity'}</button>}</div>
    <details className="ll-collaboration-interpretation"><summary>What this timeline can establish</summary><p>{data.interpretation}</p><p>A successful context tool call records a retrieval operation, not its full returned payload. An agent's explanation of how it used prior work is author-reported unless further evidence supplies the link. Source, evidence and handoff relationships can be inspected directly in Memory Graph.</p><p>Session-only identities are excluded from contributor counts. Contributor totals include recorded MCP calls, even read operations; they do not measure code output or productivity.</p></details>
   </section>
  </>}
 </div>;
}
