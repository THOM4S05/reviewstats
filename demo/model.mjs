export const STORAGE_KEY = 'reviewstats-playground-v1';
export function seed(now = Date.now()) {
  const examples = [
    ['Classic burger', 'Alex', 5, 'Great burger and friendly service.'],
    ['Veggie burger', 'Jamie', 4, 'Fresh food, lovely atmosphere.'],
    ['Classic burger', 'Alex', 5, 'Quick service and perfectly cooked chips.'],
    ['Chicken burger', 'Morgan', 4, 'Tasty lunch. Would visit again.'],
    ['Veggie burger', 'Jamie', 3, 'Good food, but a little wait at the table.'],
  ];
  const state = {version: 1, orders: [], scans: [], reviews: [], points: []};
  examples.forEach(([item, worker, rating, comment], i) => {
    const time = now - (180 - i * 35) * 60_000;
    state.orders.push({id: i+1, ref: `DEMO-00${i+1}`, item, worker, table: String(i+1), price: 12, time});
    state.scans.push({id: i+1, orderId: i+1, pointId: null, time: time+20*60_000});
    state.reviews.push({id: i+1, rating, comment, time: time+22*60_000});
  });
  state.scans.push({id: 6, orderId: 5, pointId: null, time: state.scans[4].time+15_000});
  for (let i = 1; i <= 3; i++) state.points.push({id: i, label: `Table ${i}`, table: String(i), active: true});
  return state;
}
export function nextId(rows) { return Math.max(0, ...rows.map(row => row.id)) + 1; }
export function timeScore(seconds) {
  if (seconds < 0 || seconds > 3600) return 0;
  const anchors = [[0,.99],[120,.96],[300,.88],[600,.76],[1800,.55],[3600,.30]];
  for (let i = 1; i < anchors.length; i++) {
    const [a, x] = anchors[i-1], [b, y] = anchors[i];
    if (seconds <= b) return x + (y-x) * (seconds-a)/(b-a);
  }
  return 0;
}
// Same 60-minute scoring anchors and greedy, one-scan-per-review assignment as
// app/services/matching.py. This sandbox omits backend tenants and audit storage.
export function matchReviews(state) {
  const used = new Set();
  return [...state.reviews].sort((a,b) => a.time-b.time || a.id-b.id).map(review => {
    const candidates = state.scans.filter(scan => !used.has(scan.id) && scan.time <= review.time && review.time-scan.time <= 3_600_000)
      .map(scan => ({scan, delay: Math.floor((review.time-scan.time)/1000)}))
      .sort((a,b) => a.delay-b.delay || a.scan.id-b.scan.id);
    if (!candidates.length) return {review, candidates, score: 0, status: 'Unmatched', scan: null, gap: null};
    const {scan, delay} = candidates[0];
    const gap = candidates.length > 1 ? candidates[1].delay-delay : null;
    let score = timeScore(delay)-Math.min(.12*(candidates.length-1),.36);
    if (gap !== null) score *= gap <= 30 ? .70 : gap <= 120 ? .82 : gap <= 300 ? .92 : 1;
    score = Math.max(0,Math.min(score,.99));
    if (scan.orderId === null) score = Math.max(0, score-.15);
    const status = scan.orderId === null ? (score >= .70 ? 'Probable' : 'Ambiguous') : score >= .85 ? 'High confidence' : score >= .70 ? 'Probable' : 'Ambiguous';
    used.add(scan.id);
    return {review, candidates, scan, delay, gap, score, status};
  });
}
export function load(storage) {
  try {
    const data = JSON.parse(storage.getItem(STORAGE_KEY));
    if (data?.version === 1 && ['orders','scans','reviews','points'].every(key => Array.isArray(data[key])) &&
        data.orders.every(o => Number.isFinite(o.id) && Number.isFinite(o.time) && Number.isFinite(o.price) && typeof o.ref === 'string') &&
        data.scans.every(s => Number.isFinite(s.id) && Number.isFinite(s.time)) &&
        data.reviews.every(r => Number.isFinite(r.id) && Number.isFinite(r.time) && Number.isInteger(r.rating) && r.rating >= 1 && r.rating <= 5) &&
        data.points.every(p => Number.isFinite(p.id) && typeof p.active === 'boolean')) return data;
  } catch { /* Storage may be unavailable or contain obsolete demo data. */ }
  return seed();
}
