import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Laptop,MonitorDown} from 'lucide-react';
import './software.css';

const online=device=>{
  const date=new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(device.last_seen||'')?device.last_seen:`${device.last_seen}Z`);
  return device.status==='ACTIVE'&&device.os_info==='Windows'&&Number.isFinite(date.getTime())&&Date.now()-date.getTime()<=120000;
};

export default function Software({api,devices,requests,onSubmitted,onOpenRequests}){
  const [catalog,setCatalog]=useState([]),[software,setSoftware]=useState(''),[deviceId,setDeviceId]=useState('');
  const [loading,setLoading]=useState(true),[submitting,setSubmitting]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const retry=useRef(null);
  useEffect(()=>{const controller=new AbortController();setLoading(true);api('/software/catalog',{signal:controller.signal}).then(rows=>{if(!controller.signal.aborted){setCatalog(rows);setSoftware(current=>rows.some(row=>row.key===current)?current:rows[0]?.key||'');setError('')}}).catch(err=>{if(!controller.signal.aborted)setError(err.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)});return()=>controller.abort()},[api]);
  const connected=useMemo(()=>devices.filter(online),[devices]);
  const open=requests.find(row=>row.status!=='CLOSED');
  const recent=requests.filter(row=>row.intent==='SOFTWARE_INSTALL').slice(0,10);
  async function submit(event){
    event.preventDefault();if(submitting||open||!software||!deviceId)return;
    const signature=`${software}:${deviceId}`;
    const key=retry.current?.signature===signature?retry.current.key:crypto.randomUUID();
    retry.current={signature,key};setSubmitting(true);setError('');setNotice('');
    try{
      const row=await api('/software/requests',{method:'POST',body:JSON.stringify({software,device_id:Number(deviceId),idempotency_key:key})});
      retry.current=null;setNotice(`Installation request #${row.id} is queued. The endpoint agent will report its result here.`);
      await onSubmitted();
    }catch(err){setError(err.message)}finally{setSubmitting(false)}
  }
  return <div className="softwarePage">
    <section className="pageCard"><div className="softwareHeading"><MonitorDown size={27}/><div><h1>Software installation</h1><p>Choose an approved package and a connected Windows device assigned to you.</p></div></div>
      {loading?<p role="status">Loading approved software…</p>:<form className="softwareForm" onSubmit={submit}>
        <label>Approved software<select value={software} onChange={event=>setSoftware(event.target.value)} disabled={!catalog.length||submitting}>{catalog.length?catalog.map(item=><option key={item.key} value={item.key}>{item.display_name}</option>):<option value="">No software is currently approved</option>}</select></label>
        <label>Installation device<select value={deviceId} onChange={event=>setDeviceId(event.target.value)} disabled={!connected.length||submitting} required><option value="">Select a connected Windows device</option>{connected.map(device=><option key={device.id} value={device.id}>{device.hostname} ({device.device_id})</option>)}</select></label>
        {!connected.length&&<p className="softwareHint"><Laptop size={16}/>No assigned Windows device is connected. Ask an administrator to enroll a device and start its endpoint agent.</p>}
        {open&&<p className="softwareHint" role="status">Finish your current request before starting another installation. <button type="button" onClick={onOpenRequests}>View requests</button></p>}
        <button className="primary" type="submit" disabled={submitting||!catalog.length||!connected.length||!deviceId||Boolean(open)}>{submitting?'Submitting…':'Request installation'}</button>
      </form>}
      {error&&<p className="error" role="alert">{error}</p>}{notice&&<p className="softwareNotice" role="status">{notice}</p>}
    </section>
    <section className="pageCard"><h2>Installation requests</h2>{recent.length?<div className="softwareHistory">{recent.map(row=><div key={row.id} className="softwareHistoryRow"><div><b>{row.original_message}</b><small>{row.task?`Device #${row.task.device_id} · ${row.task.software}`:'Device details unavailable'}</small></div><div><strong>{row.status.replaceAll('_',' ')}</strong><small>{row.task?.result||row.message}</small></div></div>)}</div>:<p>No software installation requests yet.</p>}</section>
  </div>;
}
