import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const out = dirname(fileURLToPath(import.meta.url));
mkdirSync(out, { recursive: true });
const ink = '#15352e', green = '#0d7160', mint = '#d8efe3', pale = '#f5faf7', line = '#92b7a6';
const esc = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const parts = [];
const rect = (x,y,w,h,fill='white',stroke=line,r=18) => parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`);
const txt = (x,y,s,size=24,weight=500,color=ink,anchor='start') => parts.push(`<text x="${x}" y="${y}" fill="${color}" font-family="Arial,Helvetica,sans-serif" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}">${esc(s)}</text>`);
const lines = (x,y,arr,size=23,gap=34,weight=500,color=ink,anchor='start') => arr.forEach((s,i)=>txt(x,y+i*gap,s,size,weight,color,anchor));
const path = (d,color=green,width=4,dash='') => parts.push(`<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" ${dash?`stroke-dasharray="${dash}"`:''} marker-end="url(#arrow)"/>`);
const box = (x,y,w,h,title,body=[],fill='white') => {rect(x,y,w,h,fill); txt(x+22,y+38,title,24,700); lines(x+22,y+77,body,20,29);};
const pill = (x,y,w,label,fill=mint) => {rect(x,y,w,45,fill,fill,22);txt(x+w/2,y+30,label,18,700,green,'middle');};
const base = (no,title,subtitle='') => {parts.length=0;rect(0,0,1600,900,pale,pale,0);rect(0,0,1600,15,green,green,0);txt(60,82,`FIGURE ${no}`,21,700,green);txt(60,132,title,39,700);if(subtitle)txt(60,170,subtitle,19,400,'#557068');parts.push('<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto"><path d="M2 2 L10 6 L2 10" fill="none" stroke="#0d7160" stroke-width="2"/></marker></defs>');};
const finish = (name,note='') => {if(note)txt(60,850,note,18,400,'#557068');writeFileSync(join(out,name),`<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-label="${esc(name)}">${parts.join('')}</svg>\n`);};

base('1.1','Traditional IT Help Desk Problem Domain','Manual triage and disconnected follow-up create delay and limited visibility.');
box(70,285,290,175,'Employee',['Password, software,','or access issue']);box(500,285,290,175,'Support inbox',['Email or phone queue','and repeated details']);box(930,225,290,175,'IT administrator',['Manual review','and handoff']);box(930,480,290,175,'Separate systems',['Identity, device,','application tools']);
path('M365 372 H485');path('M795 365 H915');path('M1075 410 V465');path('M920 570 H790 V490 H755');pill(495,535,300,'Back-and-forth clarification');pill(70,570,300,'Waiting for status');
finish('figure-1.1-traditional-helpdesk.svg','Conceptual problem-domain illustration.');

base('2.1','Existing vs. AI-Assisted Help Desk Workflow','The assistant classifies intent; backend rules and administrators retain decision authority.');
rect(70,225,680,475,'white');rect(850,225,680,475,'white');pill(105,250,190,'Existing workflow');pill(885,250,245,'AutoDeskAI workflow');
['Employee reports issue','Support manually triages','Administrator coordinates','Employee follows up'].forEach((s,i)=>{box(105,330+i*80,590,62,s);if(i<3)path(`M400 ${395+i*80} V${405+i*80}`);});
['Employee submits request','Sanitized intent classification','Policy and admin review','Provider or endpoint action'].forEach((s,i)=>{box(885,330+i*80,590,62,s);if(i<3)path(`M1180 ${395+i*80} V${405+i*80}`);});
finish('figure-2.1-existing-vs-ai-workflow.svg','Comparison is conceptual; outcomes depend on configured services.');

base('3.1','Functional Workflow of AutoDeskAI','Supported requests follow explicit validation, policy, and outcome steps.');
box(70,345,245,145,'Sign in',['Approved account']);box(390,345,245,145,'Submit issue',['Chat or access form']);box(710,345,245,145,'Classify intent',['Sanitized input']);box(1030,255,240,140,'Policy route',['Password / access']);box(1030,480,240,140,'Device route',['VS Code install']);box(1340,345,210,145,'Track result',['Audit + status']);
path('M320 415 H375');path('M640 415 H695');path('M960 400 L1015 325');path('M960 430 L1015 540');path('M1275 325 L1325 400');path('M1275 550 L1325 445');
finish('figure-3.1-functional-workflow.svg');

base('4.1','Project Development Timeline','Milestone sequence; source repository does not establish calendar dates for each phase.');
path('M120 500 H1460',green,6);const stages=[['Scope','IT helpdesk'],['Core','Auth + requests'],['Assistant','Intent routing'],['Services','Windows + access'],['Control','Admin + audit'],['Validation','Tests + deploy']];
stages.forEach((s,i)=>{const x=120+i*265;parts.push(`<circle cx="${x}" cy="500" r="16" fill="${green}"/>`);rect(x-110,i%2?545:285,220,128,'white');txt(x,i%2?595:335,s[0],25,700,ink,'middle');txt(x,i%2?630:370,s[1],18,400,ink,'middle');});
finish('figure-4.1-development-timeline.svg','Phase order is illustrative; no unverified dates are implied.');

base('5.1','AutoDeskAI System Architecture','FastAPI owns policy decisions; external providers report independently verified outcomes.');
box(70,335,265,180,'React frontend',['Employee portal','Admin portal']);box(415,335,265,180,'FastAPI backend',['Auth, workflow,','policy, audit']);box(750,225,265,140,'PostgreSQL',['Users, requests, audit']);box(750,450,265,140,'Ollama',['Sanitized intent only']);box(1090,195,390,125,'Access providers',['GitHub organization / Jira group']);box(1090,385,390,125,'Windows endpoint agent',['WinGet install + verification']);box(1090,575,390,125,'Microsoft hosted pages',['Password help / SSPR']);
path('M340 425 H400');path('M685 390 L735 300');path('M685 440 L735 515');path('M685 380 L1075 255');path('M685 470 L1075 445');path('M685 490 L1075 635');
finish('figure-5.1-system-architecture.svg');

base('5.2','Data Flow Diagram of AutoDeskAI','Only controlled request fields and sanitized intent are sent onward.');
box(65,345,225,145,'Employee',['Credentials + issue']);box(385,345,255,145,'API process',['Validate + authorize']);box(740,225,255,145,'Request store',['PostgreSQL']);box(740,470,255,145,'Classifier',['Ollama']);box(1100,225,390,145,'Admin / policy',['Decision + audit']);box(1100,470,390,145,'Service execution',['GitHub, Jira, endpoint']);
path('M295 415 H370');path('M645 395 L725 305');path('M645 440 L725 540');path('M1000 295 H1085');path('M1000 545 H1085');path('M1295 375 V455');
finish('figure-5.2-data-flow.svg','Password entry and raw chat transcripts are not stored by this flow.');

base('5.3','AutoDeskAI Request Lifecycle','Helpdesk ticket closure and application provisioning are separate states.');
box(60,330,230,135,'Created',['Validated input']);box(355,330,230,135,'Clarification',['If details missing']);box(650,330,230,135,'Decision',['Policy or admin']);box(945,215,260,135,'Approved',['Ticket closes']);box(945,475,260,135,'Rejected',['Ticket closes']);box(1270,215,270,135,'Provisioning',['External check']);box(1270,475,270,135,'Outcome',['Granted / pending']);
path('M295 395 H340');path('M590 395 H635');path('M885 370 L930 290');path('M885 420 L930 540');path('M1210 285 H1255');path('M1405 355 V460');
finish('figure-5.3-request-lifecycle.svg','Employee confirmation applies only to open request types that need their outcome.');

base('6.1','AutoDeskAI User Interface','Representative interface composition based on the current React application.');
rect(60,200,1480,585,'#102a23','#102a23',14);rect(60,200,270,585,'#0d3d35','#0d3d35',14);txt(95,250,'AutoDeskAI',28,700,'white');['Overview','My Requests','Application Access','Knowledge Base','Settings'].forEach((s,i)=>txt(95,325+i*70,s,21,500,i===0?'#cfeaae':'#bdd7cf'));
txt(375,260,'Workspace  ›  Overview',20,600,'#dcefe6');txt(375,330,'Hi, how can we help?',35,700,'white');['All requests','Closed','In progress','Needs your input'].forEach((s,i)=>{rect(375+i*275,365,250,100,'#183a30','#3a6254');txt(395+i*275,400,s,17,500,'#bdd7cf');txt(395+i*275,445,'0',34,700,'white');});rect(375,500,705,245,'#19382e','#3a6254');txt(400,545,'Your IT assistant',23,700,'white');rect(410,575,610,74,'#24473a','#24473a');lines(430,605,['Tell me what is getting in your way.','Password help · Software · Application access'],17,28,400,'white');rect(410,675,610,45,'#102a23','#699b7c',10);txt(430,705,'Describe what you need help with...',17,400,'#a9c0b6');rect(1110,500,385,245,'#19382e','#3a6254');txt(1135,545,'What do you need?',22,700,'white');lines(1135,590,['Password help','Application access','Recent requests'],20,53,500,'#dcefe6');
finish('figure-6.1-user-interface.svg','Illustrative redraw, not a live browser screenshot.');

base('6.2','Backend API Documentation Using Swagger UI','Representative FastAPI OpenAPI documentation layout; endpoint examples are project-specific.');
rect(60,200,1480,585,'white','#d0ded6',12);rect(60,200,1480,75,'#20282a','#20282a',12);txt(95,249,'Swagger UI',28,700,'white');txt(100,335,'AutoDeskAI API',34,700);txt(100,375,'OpenAPI · FastAPI interactive documentation',20,400,'#557068');
const endpoints=[['GET','/auth/me','Current account'],['POST','/auth/login','Sign in'],['GET','/access/applications','Available applications'],['POST','/access/requests','Create access request'],['GET','/access/requests','My access requests']];endpoints.forEach((e,i)=>{const y=415+i*67;rect(95,y,1410,55,i%2?'#edf7f0':'#e6f2f7',i%2?'#9bcbb0':'#91b9cf',6);rect(110,y+9,95,36,e[0]==='GET'?'#56a783':'#4b91b9','none',4);txt(157,y+34,e[0],17,700,'white','middle');txt(235,y+35,e[1],19,700);txt(980,y+35,e[2],17,400,'#557068');});
finish('figure-6.2-swagger-ui.svg','Illustrative API documentation view; use /docs on a running backend for a live screenshot.');

base('7.1','Backend and Frontend Testing Workflow','Local checks validate policy logic, API behavior, and the built client.');
box(70,335,260,165,'Code change',['Backend or frontend']);box(410,235,315,160,'Backend tests',['pytest: auth, policy,','provider + requests']);box(410,475,315,160,'Frontend tests',['Vitest: flow, UI,','pagination + API']);box(805,335,315,165,'Frontend build',['Vite production build']);box(1200,335,300,165,'Review + deploy',['Diff, commit, push']);path('M335 390 L395 315');path('M335 445 L395 550');path('M730 310 L790 395');path('M730 550 L790 445');path('M1125 420 H1185');
finish('figure-7.1-testing-workflow.svg','Tests use local and mocked services; live tenant verification is a separate check.');

base('8.1','Secure Request Processing Workflow','Identity, scope, policy, and external verification are checked in sequence.');
box(50,335,220,155,'Sign in',['JWT account state']);box(330,335,220,155,'Validate',['Length + rate limit']);box(610,335,220,155,'Sanitize',['Allowed intent data']);box(890,335,220,155,'Authorize',['Policy / admin']);box(1170,335,350,155,'Execute + audit',['Verify grant or endpoint result']);path('M275 410 H315');path('M555 410 H595');path('M835 410 H875');path('M1115 410 H1155');pill(90,580,315,'Pending accounts blocked');pill(485,580,340,'Out-of-scope requests rejected');pill(925,580,490,'No unverified access marked granted');
finish('figure-8.1-secure-processing.svg','Conceptual security workflow; see README for implementation details.');
