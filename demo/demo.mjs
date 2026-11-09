import {load, nextId, matchReviews, seed, STORAGE_KEY} from './model.mjs';

let storage;
try { storage = window.localStorage; } catch { storage = null; }
let state = load(storage);
const main = document.querySelector('main');
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = stamp => new Date(stamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
const percent = score => `${Math.round(score*100)}%`;
const stars = rating => `<span class="stars" aria-label="${rating} out of 5 stars">${'★'.repeat(rating)}${'☆'.repeat(5-rating)}</span>`;
const badge = status => `<span class="badge ${status.toLowerCase().replaceAll(' ','-')}">${status}</span>`;
const orderFor = match => state.orders.find(o => o.id === match?.scan?.orderId);
const delay = seconds => `${Math.floor(seconds/60)}m ${seconds%60}s`;
const heading = (title, sub, action='') => `<section class="heading"><div><p class="eyebrow">Demo Burger Bar</p><h1>${title}</h1><p>${sub}</p></div>${action}</section>`;
let noticeTimer;
function notify(message) {
  clearTimeout(noticeTimer);
  document.querySelector('#notice').textContent = message;
  noticeTimer = setTimeout(() => {document.querySelector('#notice').textContent='';}, 6000);
}
function save() {
  try { if (!storage) throw new Error(); storage.setItem(STORAGE_KEY,JSON.stringify(state)); }
  catch { notify('Browser storage is unavailable or full. Changes will last for this visit only.'); }
}
function metrics(matches) {
  const used = new Set(matches.filter(m=>m.scan).map(m=>m.scan.id));
  return [['Demo orders',state.orders.length],['QR / NFC scans',state.scans.length],['Review records',state.reviews.length],['High-confidence matches',matches.filter(m=>m.status==='High confidence').length],['Ambiguous matches',matches.filter(m=>m.status==='Ambiguous').length],['Unmatched scans',state.scans.filter(s=>!used.has(s.id)).length]]
    .map(([label,value])=>`<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('');
}
function ratingTable(matches, field) {
  const groups = new Map();
  matches.filter(m=>m.status==='High confidence' && orderFor(m)).forEach(m=>{
    const name = orderFor(m)[field];
    if (!name) return;
    const list = groups.get(name) || []; list.push(m.review.rating); groups.set(name,list);
  });
  if (!groups.size) return '<p class="empty">No high-confidence attributed ratings yet.</p>';
  return `<div class="table-scroll"><table><thead><tr><th>${field==='item'?'Item':'Worker'}</th><th>Average</th><th>Eligible reviews</th></tr></thead><tbody>${[...groups].sort((a,b)=>b[1].reduce((x,y)=>x+y,0)/b[1].length-a[1].reduce((x,y)=>x+y,0)/a[1].length).map(([name,values])=>`<tr><td>${escape(name)}</td><td><span class="stars">★</span> ${(values.reduce((a,b)=>a+b,0)/values.length).toFixed(2)}</td><td>${values.length}</td></tr>`).join('')}</tbody></table></div>`;
}
function timeline(order, matches) {
  const match = matches.find(m=>m.scan?.orderId === order.id);
  const scan = match?.scan || [...state.scans].reverse().find(s=>s.orderId===order.id);
  return `<article class="card timeline"><div><p class="eyebrow">Order</p><h3>#${escape(order.ref)}</h3><p>${time(order.time)} · ${escape(order.worker || 'Unassigned')}</p><p>${escape(order.item)} · €${Number(order.price).toFixed(2)}</p><button class="secondary" data-scan-order="${order.id}">Simulate scan</button></div><div><p class="eyebrow">QR / NFC scan</p><h3>${scan?time(scan.time):'Not scanned'}</h3><p>${scan?`Scan event #${scan.id}`:'Waiting for a scan'}</p></div><div><p class="eyebrow">Likely mock review</p>${match?`${stars(match.review.rating)}<blockquote>“${escape(match.review.comment || 'No written comment')}”</blockquote><p>${time(match.review.time)}</p>`:'<h3 class="muted">No likely review yet</h3>'}</div><div><p class="eyebrow">Match</p>${badge(match?.status || 'Unmatched')}${match?`<strong class="confidence">${percent(match.score)}</strong><small>Estimated confidence<br>${delay(match.delay)} scan → review<br>${match.candidates.length} candidate scan(s)</small>`:'<p>No timing attribution</p>'}</div></article>`;
}
function dashboard(matches) {
  return heading('Review statistics','Follow the journey from order to scan to likely review.', '<div class="actions"><button data-rematch>Run matcher</button><a class="button secondary" href="#pos">Create order</a></div>')+
    '<aside class="guide"><strong>Take it for a spin →</strong><p>Create an order in Mock POS, simulate its scan, then submit a review in the Reviews tab. Try two scans close together to see confidence fall.</p></aside>'+
    `<section class="metrics" aria-label="Demo metrics">${metrics(matches)}</section><p class="eyebrow">Evidence-aware ratings</p><h2>Attributed rating summaries</h2><div class="grid"><article class="card rating-card"><h3>Average rating by item</h3>${ratingTable(matches,'item')}</article><article class="card rating-card"><h3>Average rating by worker</h3>${ratingTable(matches,'worker')}</article></div><p class="help">Playground summaries include high-confidence matches only and show raw averages. The full app also evaluates ambiguity groups and rebalances worker ratings. Small samples are illustrative.</p><br><p class="eyebrow">Attribution timeline</p><h2>Order → Scan → Likely review</h2>${[...state.orders].sort((a,b)=>b.time-a.time).map(order=>timeline(order,matches)).join('') || '<div class="card empty">Create your first sample order in Mock POS.</div>'}`;
}
function reviewDetail(match) {
  const order = orderFor(match);
  return `<details><summary><span class="review-score">${match.review.rating}★</span><span class="review-copy"><strong>${escape(match.review.comment || 'No written comment')}</strong><small>Mock review #${match.review.id} · ${time(match.review.time)}</small></span>${badge(match.status)}</summary><div class="detail"><div class="grid"><section class="card"><h3>Timing attribution</h3><dl><div><dt>Confidence</dt><dd>${percent(match.score)}</dd></div><div><dt>Candidates</dt><dd>${match.candidates.length}</dd></div><div><dt>Scan → review</dt><dd>${match.scan?delay(match.delay):'No eligible scan'}</dd></div><div><dt>Runner-up gap</dt><dd>${match.gap!==null?match.gap+'s':'—'}</dd></div></dl></section><section class="card"><h3>Likely order</h3>${order?`<p><strong>#${escape(order.ref)}</strong> · Table ${escape(order.table || '—')}</p><p>${escape(order.item)} · ${escape(order.worker || 'Unassigned')} · €${Number(order.price).toFixed(2)}</p>`:'<p>No order linked to the selected scan.</p>'}<p class="help">Reviews are matched by timing, not their rating, comment, or the selected scan button.</p></section></div><h3>Competing scan evidence</h3><div class="table-scroll"><table><thead><tr><th>Rank</th><th>Scan</th><th>Order</th><th>Delay</th><th>Selected</th></tr></thead><tbody>${match.candidates.map((candidate,i)=>`<tr><td>${i+1}</td><td>#${candidate.scan.id}</td><td>${escape(state.orders.find(o=>o.id===candidate.scan.orderId)?.ref || 'Awaiting order')}</td><td>${delay(candidate.delay)}</td><td>${i===0?'Yes':'No'}</td></tr>`).join('') || '<tr><td colspan="5">No unused scan before this review within the 60-minute window.</td></tr>'}</tbody></table></div></div></details>`;
}
function reviews(matches) {
  return heading('All reviews','Open a review to inspect the evidence behind its match.')+
    `<section class="card" style="margin-bottom:28px"><h2>Write a simulated review</h2><form id="review-form"><div class="form-grid"><label>Rating<select name="rating">${[5,4,3,2,1].map(n=>`<option value="${n}">${n} star${n===1?'':'s'}</option>`).join('')}</select></label><label>Review timing<select name="timing"><option value="now">Right now</option><option value="after">2 minutes after the latest scan</option><option value="expired">61 minutes after the latest scan</option></select></label><label class="span-2">Comment<textarea name="comment" maxlength="1000" placeholder="How was your sample visit?"></textarea></label></div><button>Submit mock review</button><p class="help">Use “2 minutes after” to test a short delay or “61 minutes after” to explore the matching window. Nothing is sent to Google.</p></form></section><p class="eyebrow">Review ledger · ${matches.length} records</p>${[...matches].reverse().map(reviewDetail).join('') || '<div class="card empty">No reviews yet. Add one above.</div>'}`;
}
function pos() {
  return heading('Mock POS','Create a sample purchase, then simulate the customer’s QR or NFC scan.')+
    `<div class="grid"><section class="card"><h2>Create an order</h2><form id="order-form"><div class="form-grid"><label>Order reference<input name="ref" required maxlength="60" value="DEMO-${String(nextId(state.orders)).padStart(3,'0')}"></label><label>Worker<input name="worker" maxlength="60" placeholder="e.g. Alex"></label><label>Item<input name="item" required maxlength="100" placeholder="e.g. Classic burger"></label><label>Price (€)<input name="price" type="number" required min="0" max="9999" step="0.01" value="12.00"></label><label>Table<input name="table" maxlength="30" placeholder="e.g. 4"></label></div><button>Create sample order</button></form></section><aside class="card"><p class="eyebrow">How to explore</p><h2>One purchase. A trail of evidence.</h2><p>1. Create an order with any item and worker.</p><p>2. Use <strong>Simulate scan</strong> on the new order.</p><p>3. Add a review under <a href="#reviews">Reviews</a>.</p><p>4. Check the dashboard and expand the review’s candidate evidence.</p><p class="help">Multiple scans close together create competing candidates. A high confidence score remains a heuristic estimate.</p></aside></div><h2>Sample orders</h2><div class="stack">${[...state.orders].reverse().map(o=>`<article class="card order-row"><div><h3>#${escape(o.ref)}</h3><p>${escape(o.item)} · €${Number(o.price).toFixed(2)} · ${escape(o.worker || 'Unassigned')} · Table ${escape(o.table || '—')}</p></div><button class="secondary" data-scan-order="${o.id}">Simulate scan</button></article>`).join('')}</div>`;
}
function scanpoints() {
  return heading('Scanpoints','Experiment with persistent points, table assignments and disabled access.')+
    `<section class="card" style="margin-bottom:26px"><h2>Create a sample scanpoint</h2><form id="point-form"><div class="form-grid"><label>Label<input name="label" required maxlength="60" placeholder="e.g. Window table"></label><label>Table reference<input name="table" required maxlength="30" placeholder="e.g. 4"></label></div><button>Create scanpoint</button></form><p class="help">A scan links to the newest demo order at the assigned table. With no order it stays unresolved. These buttons simulate a visit; they do not create physical QR or NFC tags.</p></section><div class="stack">${state.points.map(point=>`<article class="card point"><div><p class="eyebrow">Permanent point #${point.id}</p><h3>${escape(point.label)}</h3><p>Table ${escape(point.table)} · ${point.active?'Active':'Disabled'} · ${state.scans.filter(s=>s.pointId===point.id).length} scan(s)</p></div><div class="actions"><button data-point-scan="${point.id}" ${point.active?'':'disabled'}>Simulate visit</button><button class="secondary" data-reassign="${point.id}">Reassign</button><button class="secondary" data-toggle="${point.id}">${point.active?'Disable':'Enable'}</button></div></article>`).join('')}</div><section id="reassign-panel"></section>`;
}
function route() {
  const page = ['dashboard','reviews','scanpoints','pos'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'dashboard';
  document.querySelectorAll('nav a').forEach(a=>{if(a.hash===`#${page}`) a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  const matches = matchReviews(state);
  main.innerHTML = page==='reviews'?reviews(matches):page==='pos'?pos():page==='scanpoints'?scanpoints():dashboard(matches);
  document.title = `${{dashboard:'Dashboard',reviews:'Reviews',pos:'Mock POS',scanpoints:'Scanpoints'}[page]} · ReviewStats demo`;
}
function recordScan(orderId, pointId=null) {
  state.scans.push({id:nextId(state.scans), orderId, pointId, time:Date.now()}); save(); route();
  notify(orderId===null?'Scan recorded without an order. Add a review to explore unresolved evidence.':'Scan recorded. Add a simulated review in Reviews to see its attribution.');
}
main.addEventListener('click', event=>{
  const button = event.target.closest('button'); if (!button) return;
  if (button.hasAttribute('data-scan-order')) recordScan(Number(button.dataset.scanOrder));
  if (button.hasAttribute('data-rematch')) { route(); notify('Matching recalculated from the current demo evidence.'); }
  if (button.hasAttribute('data-point-scan')) {
    const point = state.points.find(p=>p.id===Number(button.dataset.pointScan)); if (!point?.active) return;
    const order = [...state.orders].sort((a,b)=>b.time-a.time).find(o=>o.table===point.table);
    recordScan(order?.id ?? null,point.id);
  }
  if (button.hasAttribute('data-toggle')) { const point=state.points.find(p=>p.id===Number(button.dataset.toggle)); point.active=!point.active;save();route();notify(`Scanpoint ${point.active?'enabled':'disabled'}.`); }
  if (button.hasAttribute('data-reassign')) {
    const point=state.points.find(p=>p.id===Number(button.dataset.reassign));
    const panel=document.querySelector('#reassign-panel');
    panel.innerHTML=`<div class="card" style="margin-top:20px"><h2>Reassign ${escape(point.label)}</h2><form id="reassign-form" data-id="${point.id}"><label>New table reference<input name="table" required maxlength="30" value="${escape(point.table)}"></label><button>Save assignment</button><p class="help">Earlier scans keep their original linked order.</p></form></div>`;
    panel.querySelector('input').focus();
  }
});
main.addEventListener('submit', event=>{
  event.preventDefault(); const form=event.target, data=new FormData(form);
  const text=name=>String(data.get(name) || '').trim();
  if (form.id==='order-form') {
    if (!text('ref') || !text('item')) return notify('Enter an order reference and item.');
    if (state.orders.some(o=>o.ref.toLowerCase()===text('ref').toLowerCase())) return notify('That order reference already exists. Choose a unique reference.');
    state.orders.push({id:nextId(state.orders),ref:text('ref'),worker:text('worker'),item:text('item'),price:Number(text('price')),table:text('table'),time:Date.now()}); save();route();notify('Order created. Use Simulate scan to continue.');
  } else if (form.id==='review-form') {
    const latest=Math.max(0,...state.scans.map(s=>s.time));
    const timing=text('timing');
    if (timing!=='now' && !latest) return notify('Simulate a scan first, or choose Right now.');
    const stamp=timing==='after'?latest+120_000:timing==='expired'?latest+3_660_000:Date.now();
    state.reviews.push({id:nextId(state.reviews),rating:Number(text('rating')),comment:text('comment'),time:stamp});save();route();notify('Mock review added and attribution recalculated.');
  } else if (form.id==='point-form') {
    if (!text('label') || !text('table')) return notify('Enter a label and table reference.');
    state.points.push({id:nextId(state.points),label:text('label'),table:text('table'),active:true});save();route();notify('Scanpoint created.');
  } else if (form.id==='reassign-form') {
    if (!text('table')) return notify('Enter a table reference.');
    state.points.find(p=>p.id===Number(form.dataset.id)).table=text('table');save();route();notify('Table assignment updated. Earlier scan evidence is preserved.');
  }
});
const resetDialog=document.querySelector('#reset-dialog');
document.querySelector('#reset').addEventListener('click',()=>resetDialog.showModal());
resetDialog.addEventListener('close',()=>{if(resetDialog.returnValue==='reset'){state=seed();save();route();notify('Original sample data restored.');}});
window.addEventListener('hashchange',()=>{route();main.focus();});
save();route();
