import test from 'node:test';
import assert from 'node:assert/strict';
import {seed,matchReviews,timeScore,load} from './model.mjs';

test('sample contains high confidence and competing-scan ambiguity',()=>{
  const matches=matchReviews(seed(1_000_000_000));
  assert.equal(matches.filter(m=>m.status==='High confidence').length,4);
  assert.equal(matches[4].status,'Ambiguous');
  assert.equal(matches[4].gap,15);
  assert.equal(matches[4].candidates.length,2);
});
test('scan assignment is greedy, stable for ties, and never reused',()=>{
  const state={orders:[],scans:[{id:2,time:0,orderId:2},{id:1,time:0,orderId:1}],reviews:[{id:2,time:120_000},{id:1,time:120_000},{id:3,time:120_000}]};
  const matches=matchReviews(state);
  assert.deepEqual(matches.map(m=>m.scan?.id ?? null),[1,2,null]);
  assert.equal(matches[2].status,'Unmatched');
});
test('future and expired scans cannot match; window boundary is inclusive',()=>{
  const state={scans:[{id:1,time:0,orderId:1}],reviews:[{id:1,time:3_600_001}]};
  assert.equal(matchReviews(state)[0].status,'Unmatched');
  state.reviews[0].time=-1;
  assert.equal(matchReviews(state)[0].status,'Unmatched');
  state.reviews[0].time=3_600_000;
  assert.equal(matchReviews(state)[0].scan.id,1);
  assert.equal(timeScore(120),.96);
  assert.equal(timeScore(3600),.30);
});
test('unresolved scan receives backend-compatible confidence penalty',()=>{
  const match=matchReviews({scans:[{id:1,time:0,orderId:null}],reviews:[{id:1,time:120_000}]})[0];
  assert.equal(match.status,'Probable');
  assert.ok(Math.abs(match.score-.81)<.00001);
});
test('saved edits survive load; blocked or corrupt storage falls back to sample data',()=>{
  const data=seed();data.orders[0].ref='EDITED';
  assert.equal(load({getItem:()=>JSON.stringify(data)}).orders[0].ref,'EDITED');
  for(const storage of [null,{getItem:()=>'{bad'},{getItem:()=>'{"version":1,"orders":[{}],"scans":[],"reviews":[],"points":[]}'}]) assert.equal(load(storage).orders.length,5);
});
