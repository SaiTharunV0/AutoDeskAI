import test from 'node:test';
import assert from 'node:assert/strict';
import {attachPageGestures} from './gestures.js';

const emit = (target, type, properties) => {
  const event = new Event(type, {cancelable: true});
  Object.assign(event, properties);
  target.dispatchEvent(event);
  return event;
};
const touches = (x, y = 0, gap = 60) => [{clientX: x, clientY: y}, {clientX: x + gap, clientY: y}];

test('one trackpad gesture navigates once, including momentum; cleanup removes handlers', () => {
  const target = new EventTarget(), moves = [], timers = new Map();
  let id = 0;
  const stop = attachPageGestures(target, direction => moves.push(direction), {
    setTimer: fn => { timers.set(++id, fn); return id; }, clearTimer: key => timers.delete(key),
  });
  for (let i = 0; i < 20; i++) emit(target, 'wheel', {deltaX: -30, deltaY: 1});
  assert.deepEqual(moves, [-1]);
  for (const fn of [...timers.values()]) fn();
  emit(target, 'wheel', {deltaX: 100, deltaY: 0});
  assert.deepEqual(moves, [-1, 1]);
  stop();
  emit(target, 'wheel', {deltaX: -100, deltaY: 0});
  assert.deepEqual(moves, [-1, 1]);
});

test('two-finger swipe works but vertical scrolling and pinch zoom do not navigate', () => {
  const target = new EventTarget(), moves = [];
  const stop = attachPageGestures(target, direction => moves.push(direction));
  emit(target, 'touchstart', {touches: touches(0)});
  emit(target, 'touchmove', {touches: touches(110)});
  emit(target, 'touchend', {touches: []});
  assert.deepEqual(moves, [-1]);
  for (const positions of [touches(110, 200), touches(110, 0, 140)]) {
    emit(target, 'touchstart', {touches: touches(0)});
    emit(target, 'touchmove', {touches: positions});
    emit(target, 'touchend', {touches: []});
  }
  emit(target, 'wheel', {deltaX: 200, deltaY: 0, ctrlKey: true});
  assert.deepEqual(moves, [-1]);
  stop();
});
