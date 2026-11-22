import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

const context = createContext();
const source = readFileSync(new URL('../Order.js', import.meta.url), 'utf8');
runInContext(source.replace(/^\.pragma library\r?\n/, ''), context);
const { neighbor } = context;
const row = (pinned, categoryId = 1) => ({ pinned, categoryId });

test('moves up and down by one visible row within a pin group', () => {
  const rows = [row(true), row(true), row(false), row(false)];
  assert.equal(neighbor(rows, 1, -1).index, 0);
  assert.equal(neighbor(rows, 0, 1).index, 1);
  assert.equal(neighbor(rows, 3, -1).index, 2);
  assert.equal(neighbor(rows, 2, 1).index, 3);
});

test('explains both sides of a pin boundary', () => {
  const rows = [row(true), row(true), row(false), row(false)];
  assert.equal(neighbor(rows, 1, 1).reason, 'Bottom of pinned items');
  assert.equal(neighbor(rows, 2, -1).reason, 'Top of unpinned items');
});

test('explains list ends, including a single item', () => {
  for (const rows of [[row(false)], [row(true), row(false)]]) {
    assert.equal(neighbor(rows, 0, -1).reason, 'Already at the top');
    assert.equal(neighbor(rows, rows.length - 1, 1).reason, 'Already at the bottom');
  }
});

test('does nothing without a selected row', () => {
  assert.equal(neighbor([], 0, -1), null);
  assert.equal(neighbor([row(false)], -1, 1), null);
});

test('uses visible neighbors in Pinned even across categories', () => {
  const rows = [row(true, 3), row(true, -1), row(true, 2)];
  assert.equal(neighbor(rows, 1, -1).index, 0);
  assert.equal(neighbor(rows, 1, 1).index, 2);
});
