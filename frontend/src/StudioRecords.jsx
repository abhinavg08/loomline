import React,{useEffect,useRef,useState} from 'react';

export function RecordId({value,label='Copy identifier'}){
 const [state,setState]=useState('');
 if(!value)return <span>Unavailable</span>;
 const text=String(value);
 return <span className="st-record-id"><code title={text}>{text.length>30?text.slice(0,16)+'…'+text.slice(-8):text}</code><button type="button" aria-label={label} title={text} onClick={async()=>{try{await navigator.clipboard.writeText(text);setState('Copied')}catch{setState('Select the full value in details to copy')}}}>Copy</button><span role="status">{state}</span><details><summary>Full ID</summary><code>{text}</code></details></span>;
}

export function Code({children}){
 const [state,setState]=useState('Copy');
 return <div className="st-code"><button type="button" aria-label="Copy code" onClick={async()=>{try{await navigator.clipboard.writeText(String(children));setState('Copied')}catch{setState('Select to copy')}}}>{state}</button><pre>{children}</pre></div>;
}

export function ProvenanceDialog({trace,onClose,Stamp}){
 const dialog=useRef(null);
 useEffect(()=>{
  const previous=document.activeElement,overflow=document.body.style.overflow;
  document.body.style.overflow='hidden';dialog.current?.querySelector('button')?.focus();
  const key=e=>{if(e.key==='Escape'){e.preventDefault();onClose()}if(e.key==='Tab'){
   const nodes=[...dialog.current.querySelectorAll('button,a[href],summary,input,select,textarea,[tabindex="0"]')].filter(n=>!n.disabled&&n.getClientRects().length);
   const first=nodes[0],last=nodes[nodes.length-1];
   if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}
  }};
  const node=dialog.current;node.addEventListener('keydown',key);
  return()=>{node.removeEventListener('keydown',key);document.body.style.overflow=overflow;previous?.focus()};
 },[]);
 const m=trace.memory;
 return <div className="st-overlay" onClick={onClose}><section ref={dialog} role="dialog" aria-modal="true" aria-labelledby="provenance-title" className="st-trace" onClick={e=>e.stopPropagation()}><button className="st-close" aria-label="Close provenance" onClick={onClose}>×</button><span className="st-number">ACTUAL FALKORDB RELATIONSHIPS</span><h2 id="provenance-title">Follow the evidence.</h2><Stamp value={m.class}/>{' '}<Stamp value={m.status}/><p className="st-claim">{m.content}</p>
  <ol className="st-provenance-flow" aria-label="Stored provenance path"><li><b>Agent</b><span>{trace.session?.agent_id||m.created_by}</span><small>HAS_SESSION ↓</small></li><li><b>Session</b><RecordId value={trace.session?.id} label="Copy source session ID"/><small>HAS_TURN ↓</small></li><li><b>Source turn</b><RecordId value={trace.source_turn?.id} label="Copy source turn ID"/><small>↑ DERIVED_FROM (memory to turn)</small></li><li><b>{m.class} memory</b><RecordId value={m.id} label="Copy memory ID"/><small>Created by {m.created_by} · version {m.version}</small></li></ol>
  <label>Permanent memory URI</label><RecordId value={m.reference} label="Copy memory URI"/>
  {trace.source_turn&&<details className="st-source-turn"><summary>Read the explicit source turn</summary><p>{trace.source_turn.content}</p><small>{new Date(trace.source_turn.created_at).toLocaleString()}</small></details>}
  {[['SUPPORTED_BY',m.support],['CHALLENGED_BY',m.challenges]].map(([label,items])=><div key={label}><h3>{label==='SUPPORTED_BY'?'Supporting evidence':'Contrary evidence'} <small>{label}</small></h3>{items.map(e=><article className="st-source" key={e.id}><p>{e.content}</p><RecordId value={e.id} label="Copy evidence ID"/><small>{e.source_ref} · {new Date(e.observed_at).toLocaleString()}</small></article>)}{!items.length&&<p>No linked evidence in this trace.</p>}</div>)}
  {!!trace.related_handoffs?.length&&<><h3>Subsequent handoffs <small>Handoff → REFERS_TO → Memory</small></h3>{trace.related_handoffs.map(h=><article key={h.id} className="st-handoff"><Stamp value={h.status}/><p>{h.description}</p><p>{h.from_agent_id} → {h.to_agent_id} · version {h.version}</p><RecordId value={h.id} label="Copy related handoff ID"/></article>)}</>}
  {m.steps&&<><h3>Procedure steps</h3><ol>{m.steps.map((s,i)=><li key={i}>{s}</li>)}</ol></>}
  <h3>Status and version history</h3>{trace.events.map(e=><article className="st-event" key={e.id}><b>{e.type}</b><p>{e.actor_id} · {e.old_status?e.old_status+' → ':''}{e.new_status} · version {e.new_version}</p><p>{e.reason}</p><small>{e.created_at&&new Date(e.created_at).toLocaleString()}</small></article>)}<h3>Supersession</h3><p>Replaces: {trace.supersedes.join(', ')||'none'} · Replaced by: {trace.replacements.join(', ')||'none'}</p><p className="st-help">This is a bounded trace of stored relationships. Evidence is an attributed record, not automatic proof that a claim is true.</p>
 </section></div>;
}
