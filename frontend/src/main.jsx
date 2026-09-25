import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

function App(){
  // Access token lives only in memory. Reloading signs out.
  const [token,setToken]=useState(''),[user,setUser]=useState(null);
  const [mode,setMode]=useState('login'),[page,setPage]=useState('Helpdesk');
  const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [requests,setRequests]=useState([]),[devices,setDevices]=useState([]);
  const [message,setMessage]=useState(''),[deviceId,setDeviceId]=useState('');
  const [clarify,setClarify]=useState(null),[history,setHistory]=useState(null);
  const [admin,setAdmin]=useState({users:[],requests:[],devices:[],audit:[]});
  const [catalog,setCatalog]=useState({software:[],applications:[]});
  const [enrollment,setEnrollment]=useState(null);
  const [retryKey,setRetryKey]=useState(null);
  const sessionToken=useRef('');
  async function api(path, options={}){
    let response;
    try {response=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',
      ...(token?{Authorization:'Bearer '+token}:{}),...options.headers}});}
    catch {throw new Error('Backend unavailable. Check that FastAPI is running.');}
    let data;
    try {data=await response.json();} catch {throw new Error('Backend returned an invalid response.');}
    if(!response.ok){
      if(response.status===401 && token && sessionToken.current===token){signOut();}
      throw new Error(response.status===401?'Session expired or credentials are invalid. Please sign in.':
        typeof data.detail==='string'?data.detail:Array.isArray(data.detail)?data.detail.map(x=>x.msg).join('. '):'Request failed.');
    }
    return data;
  }
  async function action(fn){setBusy(true);setError('');try{await fn();}catch(e){setError(e.message);}finally{setBusy(false);}}
  function signOut(){sessionToken.current='';setToken('');setUser(null);setEnrollment(null);setRequests([]);setDevices([]);setHistory(null);setClarify(null);setMessage('');setRetryKey(null);setAdmin({users:[],requests:[],devices:[],audit:[]});}
  async function refresh(){
    const [rows,devs]=await Promise.all([api('/requests'),api('/devices')]);
    if(sessionToken.current===token){setRequests(rows);setDevices(devs);}
  }
  async function refreshAdmin(){
    const [users,rows,devs,audit,cat]=await Promise.all([api('/admin/users'),api('/admin/requests'),api('/admin/devices'),api('/admin/audit'),api('/catalog')]);
    if(sessionToken.current===token){setAdmin({users,requests:rows,devices:devs,audit});setCatalog(cat);}
  }
  useEffect(()=>{
    if(!token)return;
    let active=true;
    async function poll(){try{if(active){await refresh();if(user?.role==='admin'&&page==='Admin')await refreshAdmin();}}catch(e){if(active)setError(e.message);}}
    poll();const timer=setInterval(poll,5000);
    return()=>{active=false;clearInterval(timer);};
  },[token,page]);
  function status(value){return <span className={'status '+value.toLowerCase()}>{value.replaceAll('_',' ')}</span>;}
  function requestList(rows){return rows.length?<div className="request-list">{rows.map(row=><article className="request" key={row.id}>
    <div className="row"><strong>#{row.id} · {row.intent.replaceAll('_',' ')}</strong>{status(row.status)}</div>
    <p>{row.message}</p><small>{new Date(row.created_at+'Z').toLocaleString()}</small>
    <div className="actions"><button className="secondary" onClick={()=>action(async()=>setHistory(await api('/requests/'+row.id+'/history')))}>View history</button>
    {row.status==='NEEDS_CLARIFICATION'&&<button onClick={()=>{setClarify(row.id);setPage('Helpdesk');}}>Answer clarification</button>}
    {row.status==='PENDING'&&row.intent.startsWith('PASSWORD_')&&<button disabled={busy} onClick={()=>action(async()=>{
      await api('/requests/'+row.id+'/password/confirm',{method:'POST',body:JSON.stringify({confirm_simulation:true})});await refresh();
    })}>Confirm simulated password operation</button>}</div>
    </article>)}</div>:<div className="empty">No requests yet. Start with one of the examples below.</div>;}
  if(!user)return <main className="auth"><section className="intro"><div className="brand">A<span>AutoDeskAI</span></div>
    <h1>Your IT helpdesk.<br/>One place to get help.</h1><p>Request approved software, application access, or a guided password workflow.</p>
    <div className="notice">Prototype environment · Password, access, and installation operations are simulated.</div></section>
    <section className="card"><h2>{mode==='login'?'Welcome back':'Create your account'}</h2><p className="muted">Sign in to your employee workspace.</p>
    <form onSubmit={e=>{e.preventDefault();const data=new FormData(e.currentTarget);const password=data.get('password');
      action(async()=>{if(mode==='register')await api('/auth/register',{method:'POST',body:JSON.stringify({name:data.get('name'),email:data.get('email'),password})});
      const login=await api('/auth/login',{method:'POST',body:JSON.stringify({email:data.get('email'),password})});
      sessionToken.current=login.access_token;setToken(login.access_token);setUser(login.user);setPage('Helpdesk');});
      e.currentTarget.reset();
    }}>
    {mode==='register'&&<label>Name<input name="name" required maxLength={100} autoComplete="name"/></label>}
    <label>Email<input name="email" type="email" required autoComplete="username"/></label>
    <label>Password<input name="password" type="password" required minLength={mode==='register'?12:1} maxLength={256} autoComplete={mode==='login'?'current-password':'new-password'}/></label>
    {mode==='register'&&<small>Use at least 12 characters.</small>}
    {error&&<p role="alert" className="error">{error}</p>}<button disabled={busy}>{busy?'Please wait…':mode==='login'?'Sign in':'Register and sign in'}</button></form>
    <button className="link" onClick={()=>{setMode(mode==='login'?'register':'login');setError('');}}>{mode==='login'?'New here? Create an account':'Already registered? Sign in'}</button></section></main>;
  return <div className="layout"><aside><div className="brand">A<span>AutoDeskAI</span></div><small>EMPLOYEE WORKSPACE</small>
    <nav>{['Helpdesk','Requests','Profile',...(user.role==='admin'?['Admin']:[])].map(item=><button key={item} className={page===item?'selected':''} onClick={()=>setPage(item)}>{item}</button>)}</nav>
    <div className="account"><strong>{user.name}</strong><small>{user.role}</small><button className="secondary" onClick={signOut}>Sign out</button></div></aside>
    <main><header><div><small>IT SUPPORT / {page.toUpperCase()}</small><h1>{page==='Helpdesk'?'How can we help?':page}</h1></div><span className="demo">Simulation mode</span></header>
    <div className="notice">Demo only. No real password changes, application provisioning, or OS installations occur.</div>
    {error&&<p role="alert" className="error">{error}</p>}
    {page==='Helpdesk'&&<><div className="stats"><section><b>{requests.length}</b><span>Total requests</span></section><section><b>{requests.filter(x=>['PENDING','PROCESSING'].includes(x.status)).length}</b><span>In progress</span></section><section><b>{devices.length}</b><span>Registered devices</span></section></div>
    <section className="card"><h2>AI helpdesk</h2><p className="muted">Choose a workflow or describe what you need. Never enter passwords or other credentials here.</p>
      <div className="examples">{['I forgot my password','Install VS Code','I need access to Tableau'].map(text=><button className="secondary" key={text} onClick={()=>{setMessage(text);setRetryKey(null);}}>{text}</button>)}</div>
      <form onSubmit={e=>{e.preventDefault();action(async()=>{
        const key=retryKey||crypto.randomUUID();setRetryKey(key);
        const row=await api('/requests',{method:'POST',body:JSON.stringify({message,device_id:deviceId?Number(deviceId):null,
          previous_request_id:clarify,idempotency_key:key})});
        setMessage('');setRetryKey(null);setClarify(row.status==='NEEDS_CLARIFICATION'?row.id:null);await refresh();
      });}}>
      <label>Device for software installation<select value={deviceId} onChange={e=>{setDeviceId(e.target.value);setRetryKey(null);}}><option value="">Select your device</option>{devices.filter(x=>x.status==='ACTIVE').map(x=><option key={x.id} value={x.id}>{x.hostname}</option>)}</select></label>
      {!devices.length&&<small>Ask an administrator to enroll your test device, then start its endpoint agent.</small>}
      {clarify&&<p>Replying to request #{clarify} <button type="button" className="link" onClick={()=>setClarify(null)}>Cancel follow-up</button></p>}
      <label>Your request<textarea required maxLength={1000} value={message} onChange={e=>{setMessage(e.target.value);setRetryKey(null);}} placeholder="e.g. Install VS Code"/></label>
      <button disabled={busy}>{busy?'Processing request…':'Send request'}</button></form></section><h2>Recent activity</h2>{requestList(requests.slice(0,5))}</>}
    {page==='Requests'&&requestList(requests)}
    {page==='Profile'&&<section className="card"><h2>{user.name}</h2><p>{user.email}</p><p>Role: {user.role}</p><h3>Your devices</h3>{devices.map(x=><p key={x.id}>{x.hostname} · {x.os_info} · {x.status}</p>)}<small>Your session is kept in memory and expires automatically. Reloading signs you out.</small></section>}
    {page==='Admin'&&<><section className="card"><h2>Approved software</h2>{catalog.software.map(x=><div className="policy" key={x.key}><span>{x.display_name}</span><button disabled={busy} onClick={()=>action(async()=>{await api('/admin/software/'+x.key,{method:'PUT',body:JSON.stringify({enabled:!x.enabled})});await refreshAdmin();})}>{x.enabled?'Disable':'Enable'}</button></div>)}
    <h2>Application policies</h2>{catalog.applications.map(x=><div className="policy" key={x.key}><span>{x.key}</span><select aria-label={'Role for '+x.key} value={x.required_role} onChange={e=>{const role=e.target.value;action(async()=>{await api('/admin/applications/'+x.key,{method:'PUT',body:JSON.stringify({enabled:x.enabled,required_role:role})});await refreshAdmin();});}}><option value="employee">Employees and admins</option><option value="admin">Admins only</option></select><button disabled={busy} onClick={()=>action(async()=>{await api('/admin/applications/'+x.key,{method:'PUT',body:JSON.stringify({enabled:!x.enabled,required_role:x.required_role})});await refreshAdmin();})}>{x.enabled?'Disable':'Enable'}</button></div>)}</section>
    <section className="card"><h2>Enroll device</h2><form onSubmit={e=>{e.preventDefault();const data=new FormData(e.currentTarget);action(async()=>{
      setEnrollment(await api('/agent/register',{method:'POST',body:JSON.stringify({device_id:data.get('device_id'),hostname:data.get('hostname'),owner_user_id:Number(data.get('owner')),os_info:'Windows'})}));await refreshAdmin();
    });}}><label>Owner<select name="owner" required>{admin.users.map(x=><option value={x.id} key={x.id}>{x.name} ({x.email})</option>)}</select></label>
    <label>Device ID<input name="device_id" pattern="[a-zA-Z0-9_.-]+" required/></label><label>Hostname<input name="hostname" pattern="[a-zA-Z0-9_.-]+" required/></label><button disabled={busy}>Enroll device</button></form>
    {enrollment&&<div className="notice"><p>Save this token privately in the endpoint agent environment. It is shown once.</p><label>Device ID<input readOnly value={enrollment.device.device_id}/></label><label>Agent token<input type="password" readOnly value={enrollment.agent_token} onFocus={e=>e.target.select()}/></label><button className="secondary" onClick={()=>setEnrollment(null)}>Dismiss token</button></div>}
    <h3>Registered devices</h3>{admin.devices.map(x=><div className="policy" key={x.id}><span>{x.hostname} · owner #{x.owner_user_id}<small>Last heartbeat: {new Date(x.last_seen+'Z').toLocaleString()}</small></span><button disabled={busy} onClick={()=>action(async()=>{await api('/admin/devices/'+x.id,{method:'PATCH',body:JSON.stringify({status:x.status==='ACTIVE'?'DISABLED':'ACTIVE'})});await refreshAdmin();})}>{x.status==='ACTIVE'?'Disable':'Enable'}</button></div>)}</section>
    <section className="card"><h2>Users</h2>{admin.users.map(x=><p key={x.id}>{x.name} · {x.email} · {x.role}</p>)}</section>
    <h2>All requests</h2>{requestList(admin.requests)}
    <section className="card"><h2>Audit log</h2><div className="table-wrap"><table><thead><tr><th>Time</th><th>Action</th><th>User</th><th>Status</th></tr></thead><tbody>{admin.audit.map(x=><tr key={x.id}><td>{new Date(x.timestamp+'Z').toLocaleString()}</td><td>{x.action}</td><td>{x.user_id||'—'}</td><td>{x.status}</td></tr>)}</tbody></table></div></section></>}
    {history&&<section className="card" aria-label="Request history"><div className="row"><h2>Request history</h2><button className="secondary" onClick={()=>setHistory(null)}>Close</button></div>{history.map(x=><p key={x.id}>{new Date(x.timestamp+'Z').toLocaleString()} · {x.action} · {x.status}</p>)}</section>}
    </main></div>;
}
createRoot(document.getElementById('root')).render(<App/>);
