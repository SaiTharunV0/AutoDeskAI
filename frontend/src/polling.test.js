import test from 'node:test';
import assert from 'node:assert/strict';
import {startPolling} from './polling.js';

class Clock {
  time = 0;
  nextId = 1;
  timers = new Map();
  now = () => this.time;
  set = (callback, delay) => {
    const id = this.nextId++;
    this.timers.set(id, {at: this.time + delay, callback});
    return id;
  };
  clear = id => this.timers.delete(id);
  async flush() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
  async advance(ms) {
    const end = this.time + ms;
    while (true) {
      const next = [...this.timers].sort((a, b) => a[1].at - b[1].at)[0];
      if (!next || next[1].at > end) break;
      this.time = next[1].at;
      this.timers.delete(next[0]);
      next[1].callback();
      await this.flush();
    }
    this.time = end;
    await this.flush();
  }
}

class Visibility extends EventTarget {
  hidden = false;
  setHidden(value) {
    this.hidden = value;
    this.dispatchEvent(new Event('visibilitychange'));
  }
}

test('requests and devices have separate intervals and pause while hidden', async () => {
  const clock = new Clock(), visibility = new Visibility();
  const calls = {requests: 0, devices: 0};
  const poll = startPolling([
    {name: 'requests', interval: 15000, load: async () => { calls.requests++; }},
    {name: 'devices', interval: 45000, load: async () => { calls.devices++; }},
  ], {visibility, now: clock.now, setTimer: clock.set, clearTimer: clock.clear});
  await clock.advance(0);
  assert.deepEqual(calls, {requests: 1, devices: 1});
  await clock.advance(30000);
  assert.deepEqual(calls, {requests: 3, devices: 1});
  visibility.setHidden(true);
  await clock.advance(60000);
  assert.deepEqual(calls, {requests: 3, devices: 1});
  visibility.setHidden(false);
  await clock.advance(0);
  assert.deepEqual(calls, {requests: 4, devices: 2});
  poll.stop();
  await clock.advance(60000);
  assert.deepEqual(calls, {requests: 4, devices: 2});
});

test('slow reads do not overlap and an explicit refresh runs after them', async () => {
  const clock = new Clock(), visibility = new Visibility();
  let finish, calls = 0, aborted = false;
  const poll = startPolling([{name: 'requests', interval: 15000,
    load: signal => { calls++; signal.addEventListener('abort', () => { aborted = true; });
      return calls === 1 ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(); },
  }], {visibility, now: clock.now, setTimer: clock.set, clearTimer: clock.clear});
  await clock.advance(0);
  await clock.advance(60000);
  assert.equal(calls, 1);
  const refreshed = poll.refresh('requests');
  assert.equal(calls, 1);
  finish();
  await refreshed;
  assert.equal(calls, 2);
  poll.stop();
  assert.equal(aborted, false);
  await clock.advance(60000);
  assert.equal(calls, 2);
});

test('hiding aborts an active read and visibility resumes without a long wait', async () => {
  const clock = new Clock(), visibility = new Visibility();
  let calls = 0, aborts = 0;
  const poll = startPolling([{name: 'requests', interval: 15000, load: signal => {
    calls++;
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => {
      aborts++;
      reject(new DOMException('Aborted', 'AbortError'));
    }));
  }}], {visibility, now: clock.now, setTimer: clock.set, clearTimer: clock.clear});
  await clock.advance(0);
  visibility.setHidden(true);
  await clock.flush();
  assert.equal(aborts, 1);
  visibility.setHidden(false);
  await clock.advance(0);
  assert.equal(calls, 2);
  poll.stop();
});

test('settled requests stop polling until a new request triggers refresh', async () => {
  const clock = new Clock(), visibility = new Visibility();
  let calls = 0;
  const poll = startPolling([{name: 'requests', interval: 15000,
    load: async () => { calls++; return calls !== 1; },
  }], {visibility, now: clock.now, setTimer: clock.set, clearTimer: clock.clear});
  await clock.advance(0);
  await clock.advance(60000);
  assert.equal(calls, 1);
  await poll.refresh('requests');
  await clock.advance(15000);
  assert.equal(calls, 3);
  poll.stop();
});
