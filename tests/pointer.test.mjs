import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

const context = createContext();
const source = readFileSync(new URL('../Pointer.js', import.meta.url), 'utf8');
runInContext(source.replace(/^\.pragma library\r?\n/, ''), context);
const { advance } = context;

function tracker() {
  let previous = null;
  return {
    sample(x, y) {
      const next = advance(previous, x, y);
      const moved = previous !== null && next !== previous;
      previous = next;
      return moved;
    },
    reset() { previous = null; },
  };
}

test('opening under a row only primes the gate; a row change at the same scene point does not move it', () => {
  const pointer = tracker();
  assert.equal(pointer.sample(20, 50), false);
  assert.equal(pointer.sample(20, 50), false);
});

test('the first move onto a row counts when the previous sample was outside the list', () => {
  const pointer = tracker();
  assert.equal(pointer.sample(220, 50), false);
  assert.equal(pointer.sample(20, 50), true);
  assert.equal(pointer.sample(20, 50), false);
});

test('one-pixel jitter does not move selection, but slow motion accumulates from the last accepted point', () => {
  const pointer = tracker();
  assert.equal(pointer.sample(20, 50), false);
  assert.equal(pointer.sample(19.5, 50.5), false);
  assert.equal(pointer.sample(21, 49), false);
  assert.equal(pointer.sample(21.25, 49), true);
  assert.equal(pointer.sample(21.25, 49.75), false);
  assert.equal(pointer.sample(21.25, 50.25), true);
});

test('reopening forgets the previous position', () => {
  const pointer = tracker();
  assert.equal(pointer.sample(20, 50), false);
  assert.equal(pointer.sample(23, 50), true);
  pointer.reset();
  assert.equal(pointer.sample(2, 2), false);
  assert.equal(pointer.sample(2, 4), true);
});
