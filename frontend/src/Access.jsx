import React, {useEffect, useState} from 'react';
import {ArrowRight, Check, CheckCircle2, ChevronRight, Clock3, Grid2X2, History, Plus, RefreshCw, ShieldCheck, X} from 'lucide-react';
import PaginatedRows from './pagination.jsx';
import {accessStatusLabel as label, pendingAccessRequests, buildAccessPayload, buildPolicyPayload, buildDecisionPayload} from './access_logic.js';
import './access.css';

const split = value => value.split(',').map(item => item.trim()).filter(Boolean);
const parseEvaluation = value => {try {return JSON.parse(value)} catch {return {}}};
const formatDate = value => new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : value + 'Z').toLocaleString();
const appInitials = value => (value || 'Application').split(/[\s_-]+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
const approvalLabel = value => ({AUTOMATIC: 'Automatic approval', CONDITIONAL: 'Conditional approval', ADMIN_ONLY: 'Administrator review'}[value] || label(value));
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
  if (!rows.length) return <div className="accessEmpty"><span className="accessEmptyIcon"><History size={22}/></span><b>{admin ? 'No access requests yet' : 'Your request history starts here'}</b><p>{admin ? 'Application access requests and their outcomes will appear here.' : 'Once you request access, you can follow its progress here.'}</p></div>;
  return <PaginatedRows rows={rows}>{pageRows => <div className="accessHistory">
    {pageRows.map(row => {const evaluation = parseEvaluation(row.evaluation_json);return <article className="accessHistoryRow" key={row.id}>
      <div className="accessHistoryIdentity"><span className="accessAppMark" aria-hidden="true">{appInitials(row.application)}</span><div><b>{row.application}</b><small>Request #{row.request_id} <span aria-hidden="true">·</span> {formatDate(row.created_at)}</small></div></div>
      <AccessStatus row={row}/>
      {row.decision_reason && <p className="accessDecision">{row.decision_reason}</p>}
      <div className="accessHistoryFacts"><span><small>Requested role</small><b>{row.requested_role}</b></span><span><small>Approval</small><b>{approvalLabel(row.approval_route)}</b></span><span><small>Provisioning</small><b>{label(row.provisioning_status)}</b></span><span><small>Policy</small><b>{evaluation.policy_id || row.application} · v{row.policy_version}</b></span>{row.expires_at && <span><small>Access expires</small><b>{formatDate(row.expires_at)}</b></span>}</div>
      {admin && ['FAILED', 'TIMEOUT'].includes(row.provisioning_status) && <div className="accessActions"><button type="button" className="secondary" onClick={() => onRetry?.(row)}><RefreshCw size={15}/>Retry simulated provisioning</button></div>}
      {admin && <details className="accessDecisionDetails"><summary>Decision details</summary><dl><div><dt>Requester</dt><dd>{row.username || row.user_id}</dd></div><div><dt>Approver</dt><dd>{row.approver_id || 'None'}</dd></div><div><dt>Duration</dt><dd>{row.duration_days} days</dd></div><div><dt>Policy</dt><dd>{evaluation.policy_id || row.application} · v{row.policy_version}</dd></div><div><dt>Conditions</dt><dd>{Object.entries(evaluation.conditions || {}).map(([key, value]) => `${key}: ${value === null ? 'unverified' : value ? 'pass' : 'fail'}`).join(', ') || 'None'}</dd></div><div><dt>Fallback</dt><dd>{label(evaluation.fallback)}</dd></div><div><dt>Justification</dt><dd>{row.justification || 'None supplied'}</dd></div></dl></details>}
    </article>})}
  </div>}</PaginatedRows>;
}

export function EmployeeAccess({api, onContinueChat}) {
  const [applications, setApplications] = useState([]), [requests, setRequests] = useState([]), [tickets, setTickets] = useState([]);
  const [selected, setSelected] = useState(''), [role, setRole] = useState(''), [days, setDays] = useState(30);
  const [justification, setJustification] = useState(''), [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const current = applications.find(item => item.key === selected);
  useEffect(() => {let live = true; Promise.all([api('/access/applications'), api('/access/requests'), api('/requests')])
    .then(([apps, rows, allTickets]) => {if (live) {setApplications(apps);setRequests(rows);setTickets(allTickets);}})
    .catch(err => {if (live) setError(err.message)})
    .finally(() => {if (live) setLoading(false)}); return () => {live = false};}, [api]);
  const openTicket = [...tickets].reverse().find(row => !['CLOSED', 'REJECTED'].includes(row.status));
  function choose(key) {const item = applications.find(app => app.key === key);setSelected(key);
    setRole(item?.requestable_roles[0] || '');setDays(item?.default_duration_days || 30);setJustification('');}
  async function submit(event) {event.preventDefault();if (!current || busy) return;setBusy(true);setError('');setNotice('');
    try {const result = await api('/access/requests', {method: 'POST', body: JSON.stringify(
      buildAccessPayload(current, role, justification, days, crypto.randomUUID()))});
      setRequests(await api('/access/requests'));setTickets(await api('/requests'));setNotice(`Request ${result.request_id} submitted: ${label(result.status)}.`);}
    catch (err) {setError(err.message)} finally {setBusy(false)}}
  return <section className="pageCard accessPage">
    <header className="accessPageHeader"><div><span className="accessEyebrow">YOUR WORKSPACE</span><h1>Application access</h1><p>The tools you need, with access that fits your role.</p></div><span className="accessHeaderLabel"><ShieldCheck size={17}/>Approved applications</span></header>
    {error && <div className="error" role="alert">{error}</div>}{notice && <div className="accessNotice" role="status"><CheckCircle2 size={18}/><p>{notice}</p></div>}
    {openTicket && <div className="accessNotice accessContinueNotice" role="status"><Clock3 size={19}/><div><b>Let's finish your current request</b><p>Please return to the chat before starting another request.</p></div><button type="button" className="secondary" onClick={onContinueChat}>Continue in chat<ArrowRight size={15}/></button></div>}
    {loading ? <div className="accessEmpty" role="status"><span className="accessEmptyIcon"><Grid2X2 size={22}/></span><b>Loading your applications…</b><p>Getting the approved catalog ready.</p></div> : <>
      <div className="accessWorkspace"><section className="accessCatalogPanel"><div className="accessSectionHeading"><div><span className="accessEyebrow">01 / EXPLORE</span><h2>Choose an application</h2><p>Browse the applications available to your team.</p></div><span className="accessCount">{applications.length}</span></div>
        <div className="accessCatalog">{applications.map(item => <button type="button" key={item.key} aria-pressed={selected === item.key} className={'accessApp ' + (selected === item.key ? 'selected' : '')} onClick={() => choose(item.key)}>
          <span className="accessAppTop"><span className="accessAppMark" aria-hidden="true">{appInitials(item.display_name)}</span><span className="accessAppSelect" aria-hidden="true">{selected === item.key ? <Check size={16}/> : <ChevronRight size={16}/>}</span></span><b>{item.display_name}</b><small>{item.description || 'Request access to this approved application.'}</small><span className="accessAppTags"><span>{item.requestable_roles.join(', ')}</span><span><Clock3 size={12}/>Up to {item.max_duration_days} days</span></span>
        </button>)}{!applications.length && <div className="accessEmpty"><span className="accessEmptyIcon"><Grid2X2 size={22}/></span><b>No applications available yet</b><p>Your IT team will add approved applications here.</p></div>}</div>
      </section>
      <section className="accessRequestPanel">{current ? <form className="accessForm" onSubmit={submit}><div className="accessFormHeading"><span className="accessEyebrow">02 / REQUEST ACCESS</span><h2>Request {current.display_name}</h2><p>Tell us what you need. We'll take it from here.</p></div>
        <label>Requested role<select value={role} onChange={event => setRole(event.target.value)}>{current.requestable_roles.map(value => <option key={value}>{value}</option>)}</select></label>
        <label>Duration in days<input type="number" min="1" max={current.max_duration_days} required value={days} onChange={event => setDays(event.target.value)}/><small>Maximum {current.max_duration_days} days</small></label>
        <label className="accessFullField">Business justification<textarea maxLength="500" value={justification} onChange={event => setJustification(event.target.value)} placeholder="How will you use this application for your work?"/><span className="accessFieldHint"><span>A little context helps your request get reviewed.</span><span>{justification.length}/500</span></span></label>
        <div className="accessRequestPolicy"><ShieldCheck size={16}/><div><b>{approvalLabel(current.approval_mode)}</b><small>{current.provider_type === 'MOCK' ? 'Provisioning is simulated for this application.' : 'Provisioning is not configured for this application.'}</small></div></div>
        <button className="primary accessSubmit" type="submit" disabled={busy || Boolean(openTicket)}>{busy ? 'Submitting…' : 'Submit access request'}{!busy && <ArrowRight size={16}/>}</button></form> : <div className="accessRequestPlaceholder"><span className="accessEmptyIcon"><ShieldCheck size={25}/></span><span className="accessEyebrow">02 / REQUEST ACCESS</span><h2>Find your next tool</h2><p>Select an application to choose a role and send your access request.</p><span className="accessPlaceholderNote"><CheckCircle2 size={14}/>Every request stays in your history.</span></div>}</section></div>
      <section className="accessSection accessHistorySection"><div className="accessSectionHeading"><div><span className="accessEyebrow">KEEP TRACK</span><h2>My access requests <span className="accessInlineCount">{requests.length}</span></h2><p>Follow your requests from review to access.</p></div><button type="button" className="secondary" onClick={() => api('/access/requests').then(setRequests).catch(err => setError(err.message))}><RefreshCw size={14}/>Refresh status</button></div><AccessHistory rows={requests}/></section>
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
  return <section className="pageCard accessPage accessAdminPage"><header className="accessPageHeader"><div><span className="accessEyebrow">ACCESS MANAGEMENT</span><h1>Applications & permissions</h1><p>A single place for your catalog, approvals and access policies.</p></div><span className="accessHeaderLabel"><ShieldCheck size={17}/>{apps.filter(item => item.enabled).length} active applications</span></header>
    {error && <div className="error" role="alert">{error}</div>}{notice && <div className="accessNotice" role="status"><CheckCircle2 size={18}/><p>{notice}</p></div>}
    {loading ? <div className="accessEmpty" role="status"><span className="accessEmptyIcon"><ShieldCheck size={22}/></span><b>Loading access policies…</b></div> : <>
      <section className="accessSection"><div className="accessSectionHeading"><div><span className="accessEyebrow">NEEDS YOUR ATTENTION</span><h2>Pending approval <span className="accessInlineCount">{pending.length}</span></h2><p>Review the request and decide who gets access.</p></div></div>{pending.length ? <PaginatedRows rows={pending}>{pageRows => <div className="accessApprovalQueue">{pageRows.map(row => <article className="accessApprovalCard" key={row.id}>
        <div className="accessApprovalIdentity"><span className="accessAppMark" aria-hidden="true">{appInitials(row.application)}</span><div><b>{row.application}</b><small>Request #{row.request_id} · {row.username || `Employee ${row.user_id}`}</small></div><span className="accessApprovalRole">{row.requested_role}</span></div>
        <p>{row.justification || 'No business justification supplied.'}</p><div className="accessApprovalMeta"><span><Clock3 size={13}/>{row.duration_days} days</span><span><ShieldCheck size={13}/>Policy v{row.policy_version}</span></div><div className="accessActions"><button type="button" className="primary" disabled={busy} onClick={() => decide(row, 'APPROVE')}><Check size={15}/>Approve request</button><button type="button" className="secondary accessReject" disabled={busy} onClick={() => decide(row, 'REJECT')}>Reject</button></div>
      </article>)}</div>}</PaginatedRows> : <div className="accessEmpty accessEmptyCompact"><span className="accessEmptyIcon"><CheckCircle2 size={22}/></span><div><b>You're all caught up</b><p>No access requests are waiting for approval.</p></div></div>}</section>
      <section className="accessSection"><div className="accessSectionHeading"><div><span className="accessEyebrow">YOUR ORGANIZATION'S TOOLS</span><h2>Application catalog <span className="accessInlineCount">{apps.length}</span></h2><p>Select an application to manage its policy.</p></div><button type="button" className="primary addApplicationButton" onClick={() => {setForm(defaultApplication);setIsNew(true);setEditorOpen(true);setRevisions([]);setError('');setNotice('')}}><Plus size={16}/>Add application</button></div>
        <div className="accessCatalog accessAdminCatalog">{apps.map(item => <button type="button" aria-pressed={!isNew && form.key === item.key} className={'accessApp ' + (!isNew && form.key === item.key ? 'selected' : '')} key={item.key} onClick={() => edit(item)}>
          <span className="accessAppTop"><span className="accessAppMark" aria-hidden="true">{appInitials(item.display_name)}</span><span className={'accessAvailability ' + (item.enabled ? 'enabled' : '')}>{item.enabled ? 'Enabled' : 'Disabled'}</span></span><b>{item.display_name}</b><small>{item.key} · Policy v{item.version}</small><span className="accessAppTags"><span>{approvalLabel(item.approval_mode)}</span><span>{item.provider_type}</span></span></button>)}{!apps.length && <div className="accessEmpty"><span className="accessEmptyIcon"><Grid2X2 size={22}/></span><b>Build your application catalog</b><p>Add your first application to start managing access.</p></div>}</div>
      </section>
      {editorOpen && <form className="accessForm accessEditor" onSubmit={save}>
        <div className="accessEditorHeading"><div><span className="accessEyebrow">{isNew ? 'NEW CATALOG ENTRY' : `APPLICATION / POLICY V${form.version}`}</span><h2>{isNew ? 'Add an application' : `Edit ${form.display_name}`}</h2><p>Make the right tools available with clear access rules.</p></div><button type="button" className="accessClose" onClick={() => setEditorOpen(false)}><X size={15}/>Close</button></div>
        <fieldset className="accessEditorGroup"><legend>Application details</legend><p>The information employees see in the catalog.</p><div className="accessEditorGrid">
          <label>Application ID<input value={form.key} disabled={!isNew} required pattern="[a-z][a-z0-9_-]+" onChange={event => update('key', event.target.value)}/></label>
          <label>Display name<input value={form.display_name} required onChange={event => update('display_name', event.target.value)}/></label>
          <label className="accessFullField">Description<textarea value={form.description} onChange={event => update('description', event.target.value)} placeholder="A short description of the application and what it is used for."/></label>
          <label className="accessCheck accessFullField"><input type="checkbox" checked={form.enabled} onChange={event => update('enabled', event.target.checked)}/><span><b>Available for requests</b><small>Show this application in the employee catalog.</small></span></label>
        </div></fieldset>
        <fieldset className="accessEditorGroup"><legend>Access & approval</legend><p>Choose the roles employees can request and how they are reviewed.</p><div className="accessEditorGrid">
          <label className="accessFullField">Requestable roles<input value={form.requestable_roles.join(', ')} required onChange={event => update('requestable_roles', split(event.target.value))}/><small>Separate multiple roles with a comma.</small></label>
          <label className="accessFullField">Who approves access?<select value={form.approval_mode} onChange={event => update('approval_mode', event.target.value)}><option value="AUTOMATIC">Bot approves eligible requests</option><option value="CONDITIONAL">Bot approves only when conditions pass</option><option value="ADMIN_ONLY">Administrator approves every request</option></select></label>
          <label className="accessCheck accessFullField"><input type="checkbox" checked={form.auto_allowed} onChange={event => update('auto_allowed', event.target.checked)}/><span><b>Allow automatic approval</b><small>The bot can approve requests that meet the policy.</small></span></label>
        </div></fieldset>
        <details className="accessAdvanced"><summary><span>Advanced policy settings<small>Eligibility, conditions and provisioning</small></span></summary><div className="accessAdvancedGrid">
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
        </div><p className="accessPolicyHelp"><ShieldCheck size={16}/><span>Automatic approval checks the role, risk, duration and configured conditions. High risk requests, human approval roles, and failed or unverified checks follow the fallback policy.</span></p></details>
        <div className="accessEditorActions"><p>Changes create a new policy revision.</p><button type="button" className="secondary" onClick={() => setEditorOpen(false)}>Cancel</button><button className="primary" disabled={busy}>{busy ? 'Saving…' : isNew ? 'Add application' : 'Save changes'}</button></div>
      </form>}
      {!isNew && <details className="accessRevisions"><summary><History size={16}/>Policy revisions<span className="accessInlineCount">{revisions.length}</span></summary><div>{revisions.length ? revisions.map(row => <p key={row.version}><b>Version {row.version}</b><span>Administrator {row.actor_id || 'System'} · {formatDate(row.created_at)}</span><small>{label(row.snapshot.approval_mode)}</small></p>) : <p>No revisions available.</p>}</div></details>}
      <section className="accessSection accessHistorySection"><div className="accessSectionHeading"><div><span className="accessEyebrow">THE COMPLETE PICTURE</span><h2>Request history <span className="accessInlineCount">{requests.length}</span></h2><p>Decisions, provisioning updates and the details behind them.</p></div></div><AccessHistory rows={requests} admin onRetry={retry}/></section>
    </>}
  </section>;
}
