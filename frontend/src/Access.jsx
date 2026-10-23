import React, {useEffect, useState} from 'react';
import PaginatedRows from './pagination.jsx';
import {accessStatusLabel as label, pendingAccessRequests, buildAccessPayload, buildPolicyPayload, buildDecisionPayload} from './access_logic.js';
import {validatedMicrosoftPasswordActionUrl} from './sspr.js';
import './access.css';

const split = value => value.split(',').map(item => item.trim()).filter(Boolean);
const parseEvaluation = value => {try {return JSON.parse(value)} catch {return {}}};
const employeeClosable = new Set(['COMPLETED', 'FAILED', 'REJECTED', 'AWAITING_USER_ACTION', 'NEEDS_CLARIFICATION', 'APPROVED_PROVISIONING_REQUIRED']);
const defaultApplication = {
  key: '', display_name: '', description: '', enabled: true, required_role: 'employee',
  requestable_roles: ['viewer'], allowed_groups: [], default_duration_days: 30,
  max_duration_days: 90, approval_mode: 'ADMIN_ONLY', conditions: {},
  fallback: 'REQUIRE_ADMIN_APPROVAL', human_roles: [], risk: 'LOW',
  provider_type: 'MOCK', config_ref: '', auto_allowed: false,
};

function AccessStatus({row}) {
  return <span className={'status ' + row.status.toLowerCase()}>{label(row.status)}</span>;
}

function AccessHistory({rows, admin = false, onRetry}) {
  if (!rows.length) return <div className="empty">No application access requests yet.</div>;
  return <PaginatedRows rows={rows}>{pageRows => <div className="accessHistory">
    {pageRows.map(row => {const evaluation = parseEvaluation(row.evaluation_json);return <article className="accessHistoryRow" key={row.id}>
      <div><b>{row.application} · {row.requested_role}</b><small>Request {row.request_id} · {new Date(row.created_at + 'Z').toLocaleString()}</small></div>
      <AccessStatus row={row}/><p>{row.decision_reason}</p>
      <small>Route: {label(row.approval_route)} · Policy: {evaluation.policy_id || row.application} v{row.policy_version} · Provisioning: {label(row.provisioning_status)}</small>
      {row.expires_at && <small>Expires: {new Date(row.expires_at + 'Z').toLocaleString()}</small>}
      {admin && ['FAILED', 'TIMEOUT'].includes(row.provisioning_status) && <div className="accessActions"><button type="button" onClick={() => onRetry?.(row)}>Retry simulated provisioning</button></div>}
      {admin && <details><summary>Decision details</summary><div>Requester: {row.user_id} · Approver: {row.approver_id || 'None'} · Duration: {row.duration_days} days</div>
        <div>Conditions: {Object.entries(evaluation.conditions || {}).map(([key, value]) => `${key}: ${value === null ? 'unverified' : value ? 'pass' : 'fail'}`).join(', ') || 'None'}</div>
        <div>Fallback: {label(evaluation.fallback)}</div><div>Justification: {row.justification || 'None'}</div></details>}
    </article>})}
  </div>}</PaginatedRows>;
}

export function EmployeeAccess({api}) {
  const [applications, setApplications] = useState([]), [requests, setRequests] = useState([]), [tickets, setTickets] = useState([]);
  const [selected, setSelected] = useState(''), [role, setRole] = useState(''), [days, setDays] = useState(30);
  const [justification, setJustification] = useState(''), [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const current = applications.find(item => item.key === selected);
  useEffect(() => {let live = true; Promise.all([api('/access/applications'), api('/access/requests'), api('/requests')])
    .then(([apps, rows, allTickets]) => {if (live) {setApplications(apps);setRequests(rows);setTickets(allTickets);}})
    .catch(err => {if (live) setError(err.message)})
    .finally(() => {if (live) setLoading(false)}); return () => {live = false};}, [api]);
  const openTicket = [...tickets].reverse().find(row => row.status !== 'CLOSED');
  async function closeTicket(resolved) {if (!openTicket) return;setBusy(true);setError('');setNotice('');
    try {if(openTicket.status==='RETRY_ACTION_REQUIRED'){if(openTicket.intent==='PASSWORD_CHANGE'||openTicket.intent==='PASSWORD_RESET'){const action=await api(`/requests/${openTicket.id}/password/action`,{method:'POST'}),url=validatedMicrosoftPasswordActionUrl(action.url);if(!url)throw new Error('Unapproved Microsoft password destination. Contact your IT administrator.');window.location.assign(url);return}if(openTicket.intent==='SOFTWARE_INSTALL'){await api(`/requests/${openTicket.id}/retry-action`,{method:'POST'});setTickets(await api('/requests'));setNotice('The same installation was queued again.');return}}if(!employeeClosable.has(openTicket.status))return;const outcome=await api(`/requests/${openTicket.id}/resolution`, {method: 'POST', body: JSON.stringify({resolved})});if(outcome.retry_action){setTickets(await api('/requests'));if(openTicket.intent==='PASSWORD_CHANGE'||openTicket.intent==='PASSWORD_RESET'){const action=await api(`/requests/${openTicket.id}/password/action`,{method:'POST'}),url=validatedMicrosoftPasswordActionUrl(action.url);if(!url)throw new Error('Unapproved Microsoft password destination. Contact your IT administrator.');window.location.assign(url);return}if(openTicket.intent==='SOFTWARE_INSTALL'){await api(`/requests/${openTicket.id}/retry-action`,{method:'POST'});setTickets(await api('/requests'));setNotice('The same installation was queued again.');return}}setNotice(outcome.message);setTickets(await api('/requests'))}
    catch (err) {setError(err.message)} finally {setBusy(false)}}
  function choose(key) {const item = applications.find(app => app.key === key);setSelected(key);
    setRole(item?.requestable_roles[0] || '');setDays(item?.default_duration_days || 30);setJustification('');}
  async function submit(event) {event.preventDefault();if (!current || busy) return;setBusy(true);setError('');setNotice('');
    try {const result = await api('/access/requests', {method: 'POST', body: JSON.stringify(
      buildAccessPayload(current, role, justification, days, crypto.randomUUID()))});
      setRequests(await api('/access/requests'));setTickets(await api('/requests'));setNotice(`Request ${result.request_id} submitted: ${label(result.status)}.`);}
    catch (err) {setError(err.message)} finally {setBusy(false)}}
  return <section className="pageCard accessPage"><h1>Application Access</h1><p>Request an approved application and follow its decision and provisioning status.</p>
    {error && <div className="error" role="alert">{error}</div>}{notice && <div className="accessNotice" role="status">{notice}</div>}
    {openTicket&&<div className="accessTicketGate" role="status"><span className="accessTicketDetails"><b>Ticket #{openTicket.id} · {openTicket.intent.replaceAll('_',' ')}</b><small><strong>Issue:</strong> {openTicket.original_message&&openTicket.original_message!=='[not retained]'?openTicket.original_message:openTicket.message}</small><small><strong>Current status:</strong> {label(openTicket.status)}</small><small><strong>Resolution:</strong> {openTicket.resolved===true?'Marked resolved by you':openTicket.resolved===false?'Marked not resolved by you':'Not confirmed yet'}</small>{openTicket.status==='AWAITING_USER_ACTION'&&<small>AutoDeskAI cannot verify the Microsoft outcome; choose the resolution that matches your experience.</small>}{openTicket.status==='APPROVED_PROVISIONING_REQUIRED'&&<small>Approval is recorded, but application access has not been verified by AutoDeskAI.</small>}{openTicket.status==='AWAITING_ADMIN_CLOSE'&&<small>An administrator must close this ticket first.</small>}</span>{employeeClosable.has(openTicket.status)&&<div className="ticketCloseChoices"><button type="button" disabled={busy} onClick={()=>closeTicket(true)}>Resolved</button><button type="button" className="unresolved" disabled={busy} onClick={()=>closeTicket(false)}>Not resolved</button></div>}</div>}
    {openTicket?.status==='RETRY_ACTION_REQUIRED'&&<div className="accessTicketGate" role="status"><span><b>Retry the action for ticket #{openTicket.id}</b><small>After trying it again, report whether the issue is resolved.</small></span><button type="button" disabled={busy} onClick={()=>closeTicket(false)}>Retry same action</button></div>}{openTicket?.status==='AWAITING_ADMIN'&&openTicket.resolved===false&&<div className="accessTicketGate" role="status"><span><b>Ticket #{openTicket.id} has been raised to an administrator</b><small>The issue is still unresolved. An administrator has been notified and will follow up.</small></span></div>}
    {loading ? <div className="empty">Loading applications...</div> : <>
      <div className="accessCatalog">{applications.map(item => <button type="button" key={item.key} className={'accessApp ' + (selected === item.key ? 'selected' : '')} onClick={() => choose(item.key)}>
        <b>{item.display_name}</b><small>{item.description}</small><span>{item.requestable_roles.join(', ')} · Up to {item.max_duration_days} days</span>
      </button>)}{!applications.length && <div className="empty">No applications are currently available for requests.</div>}</div>
      {current && <form className="accessForm" onSubmit={submit}><h2>Request {current.display_name}</h2>
        <label>Requested role<select value={role} onChange={event => setRole(event.target.value)}>{current.requestable_roles.map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Access duration (days)<input type="number" min="1" max={current.max_duration_days} required value={days} onChange={event => setDays(event.target.value)}/></label>
        <label>Business justification<textarea maxLength="500" value={justification} onChange={event => setJustification(event.target.value)} placeholder="Explain why you need this access"/></label>
        <p>Approval: {label(current.approval_mode)} · Provider: {current.provider_type === 'MOCK' ? 'Simulation only' : 'No provisioning configured'}</p>
        <button className="primary" type="submit" disabled={busy||Boolean(openTicket)}>{busy ? 'Submitting...' : 'Submit access request'}</button></form>}
      <div className="sectionHead"><h2>My access requests</h2><button type="button" className="secondary" onClick={() => api('/access/requests').then(setRequests).catch(err => setError(err.message))}>Refresh status</button></div><AccessHistory rows={requests}/>
    </>}
  </section>;
}

export function AdminAccess({api, onPendingChange}) {
  const [apps, setApps] = useState([]), [requests, setRequests] = useState([]);
  const [revisions, setRevisions] = useState([]);
  const [form, setForm] = useState(defaultApplication), [isNew, setIsNew] = useState(true), [editorOpen, setEditorOpen] = useState(false);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  async function load() {const [catalog, history] = await Promise.all([api('/admin/access/applications'), api('/admin/access/requests')]);setApps(catalog);setRequests(history);onPendingChange?.(pendingAccessRequests(history))}
  useEffect(() => {let live = true;Promise.all([api('/admin/access/applications'), api('/admin/access/requests')])
    .then(([catalog, history]) => {if (live) {setApps(catalog);setRequests(history);onPendingChange?.(pendingAccessRequests(history))}})
    .catch(err => {if (live) setError(err.message)})
    .finally(() => {if (live) setLoading(false)});return () => {live = false}}, [api, onPendingChange]);
  const update = (key, value) => setForm(current => ({...current, [key]: value}));
  function edit(item) {setForm(item);setIsNew(false);setEditorOpen(true);setNotice('');setError('');
    api(`/admin/access/applications/${item.key}/revisions`).then(setRevisions).catch(err => setError(err.message))}
  async function save(event) {event.preventDefault();if (busy) return;setBusy(true);setError('');setNotice('');
    try {const payload = buildPolicyPayload(form);
      const saved = await api(isNew ? '/admin/access/applications' : `/admin/access/applications/${form.key}`,
        {method: isNew ? 'POST' : 'PUT', body: JSON.stringify(payload)});
      await load();setForm(saved);setIsNew(false);setEditorOpen(true);
      setRevisions(await api(`/admin/access/applications/${saved.key}/revisions`));
      setNotice(`${form.display_name} saved.`);}
    catch (err) {setError(err.message)} finally {setBusy(false)}}
  async function decide(row, decision) {const reason = decision === 'REJECT' ? window.prompt(`Reason for rejecting ${row.application}:`) : '';
    if (decision === 'REJECT' && reason === null) return;
    setBusy(true);setError('');setNotice('');try {await api(`/admin/access/requests/${row.id}/decision`,
      {method: 'POST', body: JSON.stringify(buildDecisionPayload(decision, reason))});await load();setNotice(`Request ${row.request_id} ${decision.toLowerCase()}d.`)}
    catch (err) {setError(err.message)} finally {setBusy(false)}}
  async function retry(row) {if (busy) return;setBusy(true);setError('');setNotice('');
    try {await api(`/admin/access/requests/${row.id}/provisioning/retry`, {method: 'POST'});
      await load();setNotice(`Provisioning attempt recorded for request ${row.request_id}.`)}
    catch (err) {setError(err.message)} finally {setBusy(false)}}
  const pending = pendingAccessRequests(requests);
  return <section className="pageCard accessPage"><h1>Application Access Administration</h1><p>Manage the catalog, approval policy, queue and provisioning records.</p>
    {error && <div className="error" role="alert">{error}</div>}{notice && <div className="accessNotice" role="status">{notice}</div>}
    {loading ? <div className="empty">Loading access policies...</div> : <>
      <h2>Pending approval · {pending.length}</h2>{pending.length ? <PaginatedRows rows={pending}>{pageRows => <div className="accessHistory">{pageRows.map(row => <article className="accessHistoryRow" key={row.id}>
        <b>{row.application} · {row.requested_role}</b><small>Request {row.request_id} · User {row.user_id} · {row.duration_days} days · Policy v{row.policy_version}</small>
        <p>{row.justification || 'No business justification supplied.'}</p><div className="accessActions"><button type="button" disabled={busy} onClick={() => decide(row, 'APPROVE')}>Approve</button><button type="button" disabled={busy} onClick={() => decide(row, 'REJECT')}>Reject</button></div>
      </article>)}</div>}</PaginatedRows> : <div className="empty">No requests are waiting for approval.</div>}
      <h2>Application catalog</h2><div className="accessCatalog">{apps.map(item => <button type="button" className={'accessApp ' + (!isNew && form.key === item.key ? 'selected' : '')} key={item.key} onClick={() => edit(item)}>
        <b>{item.display_name}</b><small>{item.key} · v{item.version} · {item.enabled ? 'Enabled' : 'Disabled'}</small><span>{label(item.approval_mode)} · {item.provider_type}</span></button>)}</div>
      <button type="button" className="primary addApplicationButton" onClick={() => {setForm(defaultApplication);setIsNew(true);setEditorOpen(true);setRevisions([]);setError('');setNotice('')}}>＋ Add application</button>
      {editorOpen && <form className="accessForm accessEditor" onSubmit={save}>
        <div className="accessEditorHeading"><div><span className="accessEyebrow">{isNew ? 'NEW CATALOG ENTRY' : `APPLICATION · POLICY V${form.version}`}</span><h2>{isNew ? 'Add an application' : `Edit ${form.display_name}`}</h2><p>Set the basics first. Optional policy controls are grouped below.</p></div><button type="button" className="accessClose" onClick={() => setEditorOpen(false)}>Close</button></div>
        <label>Application ID<input value={form.key} disabled={!isNew} required pattern="[a-z][a-z0-9_-]+" onChange={event => update('key', event.target.value)}/></label>
        <label>Display name<input value={form.display_name} required onChange={event => update('display_name', event.target.value)}/></label>
        <label>Description<textarea value={form.description} onChange={event => update('description', event.target.value)}/></label>
        <label>Requestable roles (comma separated)<input value={form.requestable_roles.join(', ')} required onChange={event => update('requestable_roles', split(event.target.value))}/></label>
        <label>Who approves access?<select value={form.approval_mode} onChange={event => update('approval_mode', event.target.value)}><option value="AUTOMATIC">Bot approves eligible requests</option><option value="CONDITIONAL">Bot approves only when conditions pass</option><option value="ADMIN_ONLY">Administrator approves every request</option></select></label>
        <label className="accessCheck"><input type="checkbox" checked={form.auto_allowed} onChange={event => update('auto_allowed', event.target.checked)}/>Allow the bot to approve eligible requests</label>
        <label className="accessCheck"><input type="checkbox" checked={form.enabled} onChange={event => update('enabled', event.target.checked)}/>Application available for requests</label>
        <details className="accessAdvanced"><summary>Advanced policy settings</summary><div className="accessAdvancedGrid">
        <label>Who may request<select value={form.required_role} onChange={event => update('required_role', event.target.value)}><option value="employee">Employees and admins</option><option value="admin">Admins only</option></select></label>
        <label>Default duration (days)<input type="number" min="1" max="365" value={form.default_duration_days} onChange={event => update('default_duration_days', Number(event.target.value))}/></label>
        <label>Maximum duration (days)<input type="number" min="1" max="365" value={form.max_duration_days} onChange={event => update('max_duration_days', Number(event.target.value))}/></label>
        <label>Mandatory human approval roles<input value={form.human_roles.join(', ')} onChange={event => update('human_roles', split(event.target.value))}/></label>
        <label>Allowed groups (trusted directory source required)<input value={form.allowed_groups.join(', ')} onChange={event => update('allowed_groups', split(event.target.value))}/></label>
        <label>Fallback<select value={form.fallback} onChange={event => update('fallback', event.target.value)}><option>REQUIRE_ADMIN_APPROVAL</option><option>DENY</option></select></label>
        <label>Minimum justification characters<input type="number" min="0" max="500" value={form.conditions.min_justification_length ?? ''} onChange={event => setForm(current => ({...current, conditions: {...current.conditions, min_justification_length: event.target.value === '' ? undefined : Number(event.target.value)}}))}/></label>
        <label>Conditional maximum duration<input type="number" min="1" max="365" value={form.conditions.max_duration_days ?? ''} onChange={event => setForm(current => ({...current, conditions: {...current.conditions, max_duration_days: event.target.value === '' ? undefined : Number(event.target.value)}}))}/></label>
        <label>Required verified groups (comma separated)<input value={(form.conditions.required_groups || []).join(', ')} onChange={event => setForm(current => ({...current, conditions: {...current.conditions, required_groups: split(event.target.value)}}))}/></label>
        <label className="accessCheck"><input type="checkbox" checked={Boolean(form.conditions.require_verified_mfa)} onChange={event => setForm(current => ({...current, conditions: {...current.conditions, require_verified_mfa: event.target.checked}}))}/>Require verified MFA</label>
        <label className="accessCheck"><input type="checkbox" checked={form.conditions.employment_status === 'ACTIVE'} onChange={event => setForm(current => ({...current, conditions: {...current.conditions, employment_status: event.target.checked ? 'ACTIVE' : undefined}}))}/>Require verified active employment</label>
        <label>Risk<select value={form.risk} onChange={event => update('risk', event.target.value)}><option>LOW</option><option>MEDIUM</option><option>HIGH</option></select></label>
        <label>Provisioning provider<select value={form.provider_type} onChange={event => update('provider_type', event.target.value)}><option value="MOCK">Mock / simulated</option><option value="NONE">None</option></select></label>
        <label>Configuration reference (no secrets)<input value={form.config_ref} onChange={event => update('config_ref', event.target.value)}/></label>
        </div><p className="accessPolicyHelp">Bot approval still checks the role, risk, request duration and configured conditions. High risk, human only roles, or failed and unverified checks follow the fallback policy.</p></details>
        <div className="accessEditorActions"><button className="primary" disabled={busy}>{busy ? 'Saving...' : isNew ? 'Add application' : 'Save changes'}</button><button type="button" className="secondary" onClick={() => setEditorOpen(false)}>Cancel</button></div></form>}
      {!isNew && <details><summary>Policy revisions · {revisions.length}</summary>{revisions.map(row => <p key={row.version}>Version {row.version} · Administrator {row.actor_id || 'System'} · {new Date(row.created_at + 'Z').toLocaleString()} · {row.snapshot.approval_mode}</p>)}</details>}
      <h2>Request history and provisioning</h2><AccessHistory rows={requests} admin onRetry={retry}/>
    </>}
  </section>;
}
