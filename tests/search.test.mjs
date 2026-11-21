import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

const context = createContext();
const source = readFileSync(new URL('../Search.js', import.meta.url), 'utf8');
runInContext(source.replace(/^\.pragma library\r?\n/, ''), context);
const { score, filter } = context;

test('ranks prefix, word start, substring, subsequence, category, then body', () => {
  const prefix = { title: 'Git checkout' };
  const word = { title: 'Tools:git aliases' };
  const substring = { title: 'Magit actions' };
  const fuzzy = { title: 'Get inside today', categoryName: 'git' };
  const category = { title: 'Commands', categoryName: 'Git', body: 'git' };
  const body = { title: 'Clone a repository', body: 'git clone' };
  const expected = [prefix, word, substring, fuzzy, category, body];
  assert.deepEqual(Array.from(filter('GIT', [...expected].reverse())), expected);
  assert.equal(score('git', fuzzy), score('Git', { title: 'Get inside today' }));
});

test('requires every whitespace-separated token, independently across fields', () => {
  const match = { title: 'Café toolkit', categoryName: 'Archive', body: 'Install here' };
  const titleOnly = { title: 'Café' };
  assert.deepEqual(Array.from(filter('  CAFÉ\tarchive\n INSTALL ', [titleOnly, match])), [match]);
  assert.equal(score('café missing', match), -1);
  assert.equal(score('tool', match), score('café', { title: 'My Café' }));
});

test('preserves recency for ties and the input order for empty queries', () => {
  const rows = [{ title: 'App latest' }, { title: 'App older' }, { title: 'App oldest' }];
  assert.deepEqual(Array.from(filter('app', rows)), rows);
  assert.deepEqual(Array.from(filter('  \t', rows)), rows);
  assert.equal(score('', rows[0]), 0);
});

test('body text beyond the first 20,000 characters is not searched', () => {
  assert.ok(score('needle', { body: 'x'.repeat(19994) + 'needle' }) >= 0);
  assert.equal(score('needle', { body: 'x'.repeat(19995) + 'needle' }), -1);
  assert.ok(score('needle', { title: 'A needle', body: 'x'.repeat(20000) }) >= 0);
});
