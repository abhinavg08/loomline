import React,{useEffect,useRef,useState} from 'react';
import cytoscape from 'cytoscape';
import {Code,RecordId} from './StudioRecords';

const kind=n=>n.type==='Memory'?(n.properties.class||'Memory'):n.type;
const nodeKey=n=>n.key||n.id;
const colors={Task:'#506f7d',Agent:'#208975',Session:'#508bb2',Turn:'#8b79b2',episodic:'#677fd0',semantic:'#b99138',procedural:'#9660a8',Evidence:'#b0783e',Handoff:'#ba6e65',WorkClaim:'#68837b',Entity:'#6d974b',MemoryEvent:'#7d878e',MCPCall:'#7d878e'};
const label=n=>String(n.label||n.properties.title||n.properties.content||n.properties.name||n.type);
const humanType=n=>n.type==='Memory'?`${n.properties.class} memory`:n.type.replace(/([a-z])([A-Z])/g,'$1 $2').toLowerCase();
const excerpt=(value,max=58)=>{const text=String(value||'').replace(/\s+/g,' ').trim();return text.length>max?text.slice(0,max-1)+'…':text};
function displayLabel(n){
 const p=n.properties;
 if(n.type==='Agent')return excerpt(p.name||n.id.replace(/^mcp_.+_(codex|claude|antigravity)$/,'$1').replaceAll('_',' '),32)+'\nAgent identity';
 if(n.type==='Session')return 'Session\n'+(p.started_at?new Date(p.started_at).toLocaleString():'Recorded execution');
 const heading={Memory:humanType(n),Turn:'Source turn',Evidence:'Evidence',Handoff:'Handoff',Task:'Project',WorkClaim:'Work claim',MemoryEvent:'Recorded change',MCPCall:'MCP call',Entity:'Entity'}[n.type]||n.type;
 return heading+'\n'+excerpt(p.content||p.description||p.title||p.name||p.tool_name||p.type||n.label);
}
function merge(previous,incoming){
 const nodes=[...new Map([...(previous?.nodes||[]),...incoming.nodes].map(n=>[nodeKey(n),n])).values()].slice(0,250),ids=new Set(nodes.map(nodeKey));
 const edges=[...new Map([...(previous?.edges||[]),...incoming.edges].map(e=>[e.id,e])).values()].filter(e=>ids.has(e.source)&&ids.has(e.target)).slice(0,400);
 return {...incoming,nodes,edges,memory_page_ids:[...new Set([...(previous?.memory_page_ids||[]),...incoming.memory_page_ids])],queries:[...(previous?.queries||[]),...incoming.queries].slice(-60)};
}

function pathView(graph){
 // Display the loaded memory page and its actual source/evidence/handoff links.
 // Traversing back through an author must not pull every unrelated author record
 // into a small provenance view. All-project mode still exposes the full result.
 const keys=new Set(graph.memory_page_ids.map(id=>'Memory:'+id));
 const memoryLinks=new Set(['CREATED','DERIVED_FROM','SUPPORTED_BY','CHALLENGED_BY','ABOUT','REFERS_TO','SUPERSEDES']);
 graph.edges.filter(e=>memoryLinks.has(e.type)&&(keys.has(e.source)||keys.has(e.target))).forEach(e=>{keys.add(e.source);keys.add(e.target)});
 const turns=new Set(graph.nodes.filter(n=>keys.has(nodeKey(n))&&n.type==='Turn').map(nodeKey));
 graph.edges.filter(e=>e.type==='HAS_TURN'&&turns.has(e.target)).forEach(e=>keys.add(e.source));
 const sessions=new Set(graph.nodes.filter(n=>keys.has(nodeKey(n))&&n.type==='Session').map(nodeKey));
 graph.edges.filter(e=>e.type==='HAS_SESSION'&&sessions.has(e.target)&&e.source_type==='Agent').forEach(e=>keys.add(e.source));
 const handoffs=new Set(graph.nodes.filter(n=>keys.has(nodeKey(n))&&n.type==='Handoff').map(nodeKey));
 graph.edges.filter(e=>e.type==='ASSIGNED_TO'&&handoffs.has(e.source)).forEach(e=>keys.add(e.target));
 return graph.nodes.filter(n=>keys.has(nodeKey(n))&&!['Task','MemoryEvent','MCPCall','WorkClaim'].includes(n.type));
}

export default function MemoryGraph({task,projectName,agents,api,onTrace,theme}){
 const [graph,setGraph]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[selected,setSelected]=useState(null),[mode,setMode]=useState('paths'),[filters,setFilters]=useState({agent_id:'',memory_class:'',relationship:'',since:''}),[applied,setApplied]=useState({}),[zoom,setZoom]=useState(100),[queryOpen,setQueryOpen]=useState(false);
 const container=useRef(null),cy=useRef(null),generation=useRef(0),selectedRef=useRef(null);
 const displayed=graph?(mode==='all'?graph.nodes:pathView(graph)):[],displayedKeys=new Set(displayed.map(nodeKey)),displayedEdges=graph?.edges.filter(e=>displayedKeys.has(e.source)&&displayedKeys.has(e.target))||[];
 const filterKey=JSON.stringify(applied);
 async function fetchGraph({before='',focus=null,append=false}={}){
  const version=++generation.current;setLoading(true);setError('');
  const params=new URLSearchParams({limit:'2',...Object.fromEntries(Object.entries(applied).filter(([,v])=>v))});
  if(before)params.set('before',before);
  if(focus){params.set('focus',focus.id);params.set('focus_type',focus.type)}
  try{const result=(await api('/tasks/'+encodeURIComponent(task)+'/graph?'+params)).data;if(version!==generation.current)return;setGraph(old=>append?merge(old,focus?{...result,next_cursor:old?.next_cursor}:result):result);if(!append)setSelected(null)}catch(e){if(version===generation.current)setError(e.message)}finally{if(version===generation.current)setLoading(false)}
 }
 useEffect(()=>{setGraph(null);fetchGraph();return()=>{generation.current++}},[task,filterKey]);
 useEffect(()=>{
  if(!container.current||!graph)return;
  const visible=mode==='all'?graph.nodes:pathView(graph),ids=new Set(visible.map(nodeKey));
  const edges=graph.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));
  const groups={};visible.forEach(n=>{const k=n.type;(groups[k]||=[]).push(n)});
  const columns={Task:0,Agent:1,Session:2,Turn:3,Memory:4,Evidence:5,Handoff:6,Entity:6,WorkClaim:1,MemoryEvent:5,MCPCall:3};
  const positions={};Object.entries(groups).forEach(([type,items])=>items.forEach((n,i)=>{positions[nodeKey(n)]={x:(columns[type]??7)*225,y:(i-(items.length-1)/2)*130+(type==='Entity'?300:0)}}));
  const dark=theme==='dark';
  const instance=cytoscape({container:container.current,elements:[...visible.map(n=>({data:{id:nodeKey(n),title:displayLabel(n),kind:kind(n),recordType:n.type,color:colors[kind(n)]||'#68837b'},position:positions[nodeKey(n)]})),...edges.map(e=>({data:{id:'edge:'+e.id,source:e.source,target:e.target,title:e.type}}))],layout:{name:'preset',fit:true,padding:42},minZoom:.15,maxZoom:3,wheelSensitivity:.18,style:[
   {selector:'node',style:{'shape':'round-rectangle','width':180,'height':92,'background-color':'data(color)','label':'data(title)','color':'#fff','text-wrap':'wrap','text-max-width':158,'font-size':15,'font-family':'system-ui','text-valign':'center','text-halign':'center','border-width':2,'border-color':dark?'#294a40':'#fff','overlay-opacity':0}},
   {selector:'node[recordType="Agent"]',style:{shape:'ellipse',width:138,height:84}},
   {selector:'node[recordType="Evidence"]',style:{shape:'hexagon',width:185,height:100,'text-max-width':145}},
   {selector:'edge',style:{width:1.6,'line-color':dark?'#7d9e90':'#adbeb5','target-arrow-color':dark?'#7d9e90':'#adbeb5','target-arrow-shape':'triangle','curve-style':'bezier',label:'data(title)','font-size':10,'text-rotation':'autorotate','text-background-color':dark?'#142b24':'#f7faf8','text-background-opacity':.92,'text-background-padding':3,color:dark?'#c4ded0':'#49655a','overlay-opacity':0}},
   {selector:'.faded',style:{opacity:.16}},
   {selector:'node.connected',style:{'border-width':4,'border-color':dark?'#e4f8d8':'#173f32'}},
   {selector:'edge.connected',style:{'line-color':'#39946e','target-arrow-color':'#39946e','width':3}},
   {selector:'node:selected',style:{'border-width':5,'border-color':dark?'#efffe3':'#102f24'}},
   {selector:'edge:selected',style:{'line-color':'#188461','target-arrow-color':'#188461','width':3}}
  ]});
  cy.current=instance;
  instance.on('tap','node',e=>{const item=visible.find(n=>nodeKey(n)===e.target.id());if(item)setSelected({kind:'node',id:nodeKey(item)})});
  instance.on('tap','edge',e=>{setSelected({kind:'edge',id:e.target.id().slice(5)})});
  instance.on('tap',e=>{if(e.target===instance)setSelected(null)});
  instance.on('zoom',()=>setZoom(Math.round(instance.zoom()*100)));
  const observer=new ResizeObserver(()=>{instance.resize()});observer.observe(container.current);
  setZoom(Math.round(instance.zoom()*100));
  if(selectedRef.current){const id=selectedRef.current.kind==='edge'?'edge:'+selectedRef.current.id:selectedRef.current.id;const item=instance.getElementById(id);if(item.length)item.select()}
  return()=>{observer.disconnect();instance.destroy();cy.current=null};
 },[graph,mode,theme]);
 useEffect(()=>{selectedRef.current=selected;const instance=cy.current;if(!instance)return;instance.elements().removeClass('faded connected').unselect();if(!selected)return;const id=selected.kind==='edge'?'edge:'+selected.id:selected.id,node=instance.getElementById(id);if(!node.length)return;const neighborhood=node.isNode()?node.closedNeighborhood():node.connectedNodes().union(node);instance.elements().not(neighborhood).addClass('faded');neighborhood.addClass('connected');node.select()},[selected,graph,mode]);
 const node=selected?.kind==='node'?graph?.nodes.find(n=>nodeKey(n)===selected.id):null,edge=selected?.kind==='edge'?graph?.edges.find(e=>e.id===selected.id):null;
 const related=node?graph.edges.filter(e=>e.source===nodeKey(node)||e.target===nodeKey(node)):[];
 const visibleTypes=[...new Set(displayed.map(kind))];
 function choose(value){if(value&&!cy.current?.getElementById(value).length)setMode('all');setSelected(value?{kind:'node',id:value}:null);if(value){const found=cy.current?.getElementById(value);if(found?.length)cy.current.center(found)}}
 function chooseEdge(value){if(value&&!cy.current?.getElementById('edge:'+value).length)setMode('all');setSelected(value?{kind:'edge',id:value}:null)}
 function zoomBy(factor){const instance=cy.current;if(instance)instance.zoom({level:instance.zoom()*factor,renderedPosition:{x:instance.width()/2,y:instance.height()/2}})}
 return <div className="ll-graph-explorer">
  <section className="st-panel ll-graph-intro"><div><span className="st-number">REAL FALKORDB RECORDS</span><h2>See how knowledge connects.</h2><p>Explore {projectName}. Select a record or relationship to follow its meaning. Every line below comes from a stored edge.</p></div><div className="ll-graph-summary"><b>{displayed.length}</b> visible records <span>·</span> <b>{displayedEdges.length}</b> relationships</div></section>
  <section className="st-panel ll-graph-workspace">
   <form className="ll-graph-filters" onSubmit={e=>{e.preventDefault();setApplied({...filters,since:filters.since?new Date(filters.since).toISOString():''})}}>
    <label>Author<select aria-label="Graph author" value={filters.agent_id} onChange={e=>setFilters({...filters,agent_id:e.target.value})}><option value="">All authorized authors</option>{agents.map(a=><option key={a.id} value={a.id}>{a.id}</option>)}</select></label>
    <label>Memory class<select aria-label="Graph memory class" value={filters.memory_class} onChange={e=>setFilters({...filters,memory_class:e.target.value})}><option value="">All three classes</option>{['episodic','semantic','procedural'].map(v=><option key={v}>{v}</option>)}</select></label>
    <label>Relationship<select aria-label="Graph relationship" value={filters.relationship} onChange={e=>setFilters({...filters,relationship:e.target.value})}><option value="">All relationships</option>{Object.keys(graph?.relationship_types||{}).map(v=><option key={v}>{v}</option>)}</select></label>
    <label>Recorded since<input type="datetime-local" aria-label="Graph recorded since" value={filters.since} onChange={e=>setFilters({...filters,since:e.target.value})}/></label>
    <button type="submit" disabled={loading}>Apply filters</button><button type="button" onClick={()=>{setFilters({agent_id:'',memory_class:'',relationship:'',since:''});setApplied({});setMode('paths')}}>Reset</button>
   </form>
   {error&&<p role="alert" className="st-alert">Graph could not load ({error}). <button onClick={()=>fetchGraph()}>Retry</button></p>}
   <div className="ll-graph-toolbar"><div className="st-client-tabs" role="group" aria-label="Graph detail level"><button aria-pressed={mode==='paths'} onClick={()=>setMode('paths')}>Memory paths</button><button aria-pressed={mode==='all'} onClick={()=>setMode('all')}>All project records</button></div><div className="st-actions"><button aria-label="Zoom out graph" onClick={()=>zoomBy(.8)}>−</button><span aria-live="polite">{zoom}%</span><button aria-label="Zoom in graph" onClick={()=>zoomBy(1.25)}>+</button><button onClick={()=>cy.current?.fit(cy.current.elements(),42)}>Fit graph</button><button disabled={!selected} onClick={()=>setSelected(null)}>Clear selection</button></div></div>
   <div className="ll-graph-canvas-wrap"><div ref={container} className="ll-graph-canvas" role="img" aria-label="Interactive FalkorDB memory graph. Use the record and relationship selectors below for keyboard access."/>{loading&&<div className="ll-graph-loading" role="status">Reading authorized graph relationships…</div>}{graph&&!graph.nodes.some(n=>n.type==='Memory')&&!loading&&<div className="ll-graph-empty"><h3>No shared memories match this view.</h3><p>Connect an agent and invoke a Loomline memory tool, or reset the filters. Authorized identities alone do not create memories.</p></div>}</div>
   <div className="ll-graph-legend">{visibleTypes.map(t=><span key={t}><i style={{background:colors[t]||'#68837b'}}/>{t.replace(/([a-z])([A-Z])/g,'$1 $2')}</span>)}</div>
   <p className="ll-graph-hint">Drag the background to pan; scroll or pinch to zoom. Drag records to arrange your view. “Memory paths” follows the loaded memories through their source, author, evidence and handoff links; “All project records” exposes them without inventing connections.</p>
   <div className="ll-graph-accessible"><label>Jump to a record<select aria-label="Select graph record" value={node?nodeKey(node):''} onChange={e=>choose(e.target.value)}><option value="">Select a record…</option>{graph?.nodes.map(n=><option key={nodeKey(n)} value={nodeKey(n)}>{humanType(n)} · {label(n).slice(0,110)}</option>)}</select></label><label>Inspect a relationship<select aria-label="Select graph relationship" value={edge?.id||''} onChange={e=>chooseEdge(e.target.value)}><option value="">Select a relationship…</option>{graph?.edges.map(e=><option key={e.id} value={e.id}>{e.type} · {label(graph.nodes.find(n=>nodeKey(n)===e.source)||{properties:{},type:e.source}).slice(0,40)} → {label(graph.nodes.find(n=>nodeKey(n)===e.target)||{properties:{},type:e.target}).slice(0,40)}</option>)}</select></label></div>
   <div className="ll-graph-pagination"><span>{graph?.nodes.length||0} records loaded. {graph?.bounds?.truncated?'Bounded result: more records may exist.':'A bounded project view, not an entire tenant graph.'} At most 250 records / 400 relationships in this browser view.</span><button disabled={loading||!graph?.next_cursor} onClick={()=>fetchGraph({before:graph.next_cursor,append:graph.nodes.length<250})}>{graph?.nodes.length>=250?'Next memory page · reset view':'Load older memories'}</button></div>
  </section>
  {node&&<section className="st-panel ll-graph-inspector" aria-label="Selected graph record"><div className="st-panel-heading"><div><span className="st-number">{humanType(node)}</span><h2>{node.type==='Memory'?'A memory with a trace':label(node).slice(0,100)}</h2></div><div className="st-actions"><button disabled={loading} onClick={()=>{setMode('all');fetchGraph({focus:node,append:true})}}>Expand connected records</button>{node.type==='Memory'&&<button className="st-primary" onClick={()=>onTrace({reference:node.uri||`loom://task/${task}/memory/${node.id}`})}>Open full provenance →</button>}</div></div><p className="ll-graph-content">{node.properties.content||node.properties.description||label(node)}</p><dl className="ll-record-facts"><dt>Project</dt><dd>{projectName}</dd><dt>Recorded by</dt><dd>{node.properties.created_by||node.properties.agent_id||node.properties.actor_id||node.properties.from_agent_id||'See connected records'}</dd><dt>Recorded</dt><dd>{node.properties.created_at||node.properties.started_at||node.properties.observed_at?new Date(node.properties.created_at||node.properties.started_at||node.properties.observed_at).toLocaleString():'Not recorded on this node'}</dd><dt>Status</dt><dd>{node.properties.status||node.properties.state||'Not applicable'}</dd><dt>Identifier</dt><dd><RecordId value={node.id}/></dd></dl><h3>Stored connections</h3>{related.map(e=><button className="ll-edge-row" key={e.id} onClick={()=>chooseEdge(e.id)}><b>{e.type}</b><span>{e.meaning}</span></button>)}{!related.length&&<p>No incident relationships are loaded for this record. Expand to request a bounded neighborhood.</p>}<details><summary>Technical record properties</summary><Code>{JSON.stringify(node.properties,null,2)}</Code></details></section>}
  {edge&&<section className="st-panel ll-graph-inspector" aria-label="Selected graph relationship"><span className="st-number">PERSISTED RELATIONSHIP</span><h2>{edge.type}</h2><p>{edge.meaning}</p><div className="ll-edge-explanation">{[edge.source,edge.target].map((key,i)=>{const n=graph.nodes.find(n=>nodeKey(n)===key);return <React.Fragment key={key}>{i>0&&<b>→</b>}<button onClick={()=>choose(key)}>{n?`${humanType(n)} · ${label(n).slice(0,100)}`:key}</button></React.Fragment>})}</div><p className="st-help">A relationship proves a stored link. It does not by itself prove a claim is true or a retrieval caused a decision.</p></section>}
  <section className="st-panel ll-query-inspector"><details open={queryOpen} onToggle={e=>setQueryOpen(e.currentTarget.open)}><summary>Graph Query · How this was retrieved</summary><p>The gateway authenticates your identity, selects your tenant graph, checks project membership and runs these fixed parameterized read operations. This inspector cannot execute arbitrary Cypher.</p><p>SDK-equivalent reads: <code>get_context(project)</code> and <code>trace(memory_reference)</code> recover context/source/evidence. Recorded MCP activity does not retain returned payloads, so this view does not claim which exact context influenced an earlier decision.</p>{graph?.queries.map((q,i)=><details key={i}><summary>{q.name} · {q.returned_rows} returned rows · read only</summary><Code>{q.cypher}</Code><h3>Bound parameters</h3><Code>{JSON.stringify(q.parameters,null,2)}</Code><h3>Returned record samples</h3><Code>{JSON.stringify(q.returned_records||[],null,2)}</Code>{q.sample_truncated&&<p>Sample bounded to five records; the row count above covers the query result.</p>}</details>)}<p>{(typeof graph?.interpretation==='string'?graph.interpretation:graph?.interpretation?.causality)||'Authored content is attributed, untrusted data; inspect its source and evidence.'}</p></details></section>
 </div>;
}
