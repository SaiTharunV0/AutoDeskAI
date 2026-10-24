import React,{useEffect,useState} from 'react';
import {Bell,X} from 'lucide-react';
import {startPolling} from './polling.js';

export default function EmployeeNotifications({api,onViewRequest}){
  const [items,setItems]=useState([]);
  const [open,setOpen]=useState(false);
  const [error,setError]=useState('');
  const [dismissedId,setDismissedId]=useState(null);
  useEffect(()=>{
    const poll=startPolling([{name:'notifications',interval:5000,load:async signal=>{
      const rows=await api('/notifications',{signal});
      if(!signal.aborted){setItems(rows);setError('');}
    }}],{onError:()=>setError('Notifications could not be loaded. Please try again.')});
    return()=>poll.stop();
  },[api]);
  const unread=items.filter(item=>!item.read_at).length;
  const latestUnread=items.find(item=>!item.read_at);
  async function view(item){
    setError('');
    try{
      if(!item.read_at){
        const updated=await api(`/notifications/${item.id}/read`,{method:'POST'});
        setItems(current=>current.map(row=>row.id===item.id?updated:row));
      }
      await onViewRequest(item.request_id);
      setOpen(false);
    }catch{setError('Could not open this notification. Please try again.')}
  }
  return <div className="employeeNotifications">
    <button className="bell" type="button" aria-label={`${unread} unread notifications`} aria-expanded={open} aria-controls="employee-notification-list" onClick={()=>setOpen(value=>!value)}><Bell size={19}/>{unread>0&&<i>{unread}</i>}</button>
    {!open&&latestUnread&&latestUnread.id!==dismissedId&&<div className="notificationToast" role="status">
      <strong>{latestUnread.title}</strong>
      <p>{latestUnread.message}</p>
      {unread>1&&<small>{unread-1} more unread {unread===2?'notification':'notifications'}</small>}
      {error&&<p className="notificationError" role="alert">{error}</p>}
      <div className="notificationToastActions"><button type="button" onClick={()=>view(latestUnread)}>View request</button><button type="button" onClick={()=>setDismissedId(latestUnread.id)}>Dismiss</button></div>
    </div>}
    {open&&<div className="notificationPanel" id="employee-notification-list" role="region" aria-label="Notifications">
      <div className="notificationPanelHead"><b>Notifications</b><button type="button" aria-label="Close notifications" onClick={()=>setOpen(false)}><X size={17}/></button></div>
      {error&&<p className="notificationError" role="alert">{error}</p>}
      {items.length? <div className="notificationList">{items.map(item=><button type="button" key={item.id} className={`notificationItem ${item.read_at?'':'isUnread'}`} onClick={()=>view(item)}><strong>{item.title}</strong><span>{item.message}</span><small>{new Date(item.created_at.endsWith('Z')?item.created_at:item.created_at+'Z').toLocaleString()}</small></button>)}</div> : <p className="notificationEmpty">No notifications yet.</p>}
    </div>}
  </div>;
}
