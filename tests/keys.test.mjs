import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

const Qt = {
  ShiftModifier: 0x02000000,
  ControlModifier: 0x04000000,
  AltModifier: 0x08000000,
  MetaModifier: 0x10000000,
  KeypadModifier: 0x20000000,
  Key_Escape: 0x01000000,
  Key_Tab: 0x01000001,
  Key_Backtab: 0x01000002,
  Key_Return: 0x01000004,
  Key_Enter: 0x01000005,
  Key_Home: 0x01000010,
  Key_Up: 0x01000013,
  Key_Down: 0x01000015,
  Key_F1: 0x01000030,
  Key_C: 67,
  Key_G: 71,
};
const context = createContext({ Qt });
const source = readFileSync(new URL('../Keys.js', import.meta.url), 'utf8');
runInContext(source.replace(/^\.pragma library\r?\n/, ''), context);
const { parseSpec, matches, actionFor, validatedKeymap, keymapFor, textInputAction,
  printableText, tabDigit, hint } = context;
const defaults = JSON.parse(readFileSync(new URL('../config.example.json', import.meta.url), 'utf8')).keys;
const event = (key, text = '', modifiers = 0) => ({ key, text, modifiers });

test('parses Qt keys, modifiers, printable characters, and literal plus', () => {
  assert.equal(parseSpec('Alt+Ctrl+F1').key, Qt.Key_F1);
  assert.equal(parseSpec('Alt+Ctrl+F1').modifiers, Qt.AltModifier | Qt.ControlModifier);
  assert.equal(parseSpec('Shift+G').text, 'G');
  assert.equal(parseSpec('Ctrl++').text, '+');
  assert.equal(parseSpec('+').text, '+');
  assert.equal(parseSpec('😀').text, '😀');
  for (const invalid of ['', 'Ctrl+', 'Alt++C', 'Ctrl+Ctrl+Up', 'Hyper+Y', 'constructor+x',
    'Key_F1', 'NoSuchQtKey', '\n', 'two words']) {
    assert.equal(parseSpec(invalid), null, invalid);
  }
});

test('matches named keys and handles Qt Backtab and keypad Enter', () => {
  assert.ok(matches(event(Qt.Key_Up), 'Up'));
  assert.ok(!matches(event(Qt.Key_Up, '', Qt.ShiftModifier), 'Up'));
  assert.ok(matches(event(Qt.Key_Tab, '\t', Qt.ShiftModifier), 'Shift+Tab'));
  assert.ok(matches(event(Qt.Key_Backtab), 'Shift+Tab'));
  assert.ok(!matches(event(Qt.Key_Backtab, '\t', Qt.ShiftModifier), 'Tab'));
  assert.ok(matches(event(Qt.Key_Enter, '\r', Qt.KeypadModifier), 'Enter'));
});

test('uses case-sensitive text and only requires Shift when specified for plain text', () => {
  const shifted = event(Qt.Key_G, 'G', Qt.ShiftModifier);
  assert.ok(matches(shifted, 'G'));
  assert.ok(matches(shifted, 'Shift+G'));
  assert.ok(!matches(shifted, 'g'));
  assert.ok(matches(event(Qt.Key_G, 'G'), 'G'));
  assert.ok(!matches(event(Qt.Key_G, 'G'), 'Shift+G'));
  assert.ok(matches(event(47, '/', Qt.ShiftModifier), '/'));
  assert.ok(!matches(event(Qt.Key_G, 'g', Qt.AltModifier), 'g'));
});

test('matches Ctrl and Super shortcuts without confusing them with text', () => {
  assert.ok(matches(event(Qt.Key_C, '\x03', Qt.ControlModifier), 'Ctrl+C'));
  assert.ok(matches(event(Qt.Key_C, 'c', Qt.MetaModifier), 'Super+C'));
  assert.ok(!matches(event(Qt.Key_C, 'c'), 'Ctrl+C'));
  assert.ok(!matches(event(Qt.Key_C, '\x03', Qt.ControlModifier | Qt.ShiftModifier), 'Ctrl+C'));
  assert.ok(matches(event(Qt.Key_C, '\x03', Qt.ControlModifier | Qt.ShiftModifier), 'Shift+Ctrl+c'));
});

test('returns the first matching action; empty lists disable actions', () => {
  assert.equal(actionFor(event(Qt.Key_Up), { up: ['Up'], down: ['Up'] }), 'up');
  assert.equal(actionFor(event(Qt.Key_Up), { up: [], down: ['Up'] }), 'down');
  assert.equal(actionFor(event(Qt.Key_Up), { up: [] }), '');
  assert.equal(actionFor(event(Qt.Key_Backtab), defaults), 'prevTab');
});

test('search keymap keeps eligible shortcuts and does not consume query letters', () => {
  const search = keymapFor(defaults, ['up', 'down', 'paste', 'copy', 'back'], true);
  assert.equal(actionFor(event(Qt.Key_Down), search), 'down');
  assert.equal(actionFor(event(Qt.Key_Return, '\r'), search), 'paste');
  assert.equal(actionFor(event(Qt.Key_Escape), search), 'back');
  assert.equal(actionFor(event(Qt.Key_C, '\x03', Qt.ControlModifier), search), 'copy');
  for (const letter of ['j', 'k', 'p', 'y', 'q', 'G', '/']) {
    const key = event(letter.toUpperCase().charCodeAt(0), letter);
    assert.equal(actionFor(key, search), '');
    assert.equal(printableText(key), letter);
  }
  assert.equal(actionFor(event(Qt.Key_Home), search), '');
  assert.equal(printableText(event(Qt.Key_G, 'G', Qt.ShiftModifier)), 'G');
  assert.equal(printableText(event(Qt.Key_C, 'c', Qt.MetaModifier)), '');
  assert.equal(printableText(event(Qt.Key_Return, '\r')), '');
  assert.equal(tabDigit(event(49, '1', Qt.KeypadModifier)), 1);
  assert.equal(tabDigit(event(49, '1', Qt.ControlModifier)), -1);
});

test('save picker uses configured navigation while a new tab name can still contain p', () => {
  const keymap = { ...defaults, up: ['F1'], back: ['Ctrl+C'] };
  const save = keymapFor(keymap, ['up', 'down', 'paste', 'back'], false);
  const input = keymapFor(keymap, ['paste', 'back'], true);
  const p = event(80, 'p');
  const ctrlC = event(Qt.Key_C, '\x03', Qt.ControlModifier);
  assert.equal(actionFor(event(Qt.Key_F1), save), 'up');
  assert.equal(actionFor(event(Qt.Key_Up), save), '');
  assert.equal(actionFor(p, save), 'paste');
  assert.equal(actionFor(p, input), '');
  assert.equal(printableText(p), 'p');
  assert.equal(actionFor(ctrlC, input), 'back');
});

test('reports and filters unknown Qt keys without losing valid bindings', () => {
  const warnings = ['existing warning'];
  const map = validatedKeymap({ up: ['Foo', 'Up'], back: ['Key_Escape'] }, warnings);
  assert.deepEqual(Array.from(map.up), ['Up']);
  assert.equal(map.back.length, 0);
  assert.deepEqual(warnings, ['existing warning', 'Unknown key "Foo" in keys.up',
    'Unknown key "Key_Escape" in keys.back']);
});

test('text input reserves Return, Enter, and Escape even with conflicting or disabled bindings', () => {
  const search = keymapFor({ up: ['Return', 'Escape'], paste: [], back: ['F1'] },
    ['up', 'down', 'paste', 'copy', 'back'], true);
  const newTab = keymapFor({ paste: ['Escape'], back: [] }, ['paste', 'back'], true);
  for (const map of [search, newTab]) {
    assert.equal(textInputAction(event(Qt.Key_Return, '\r'), map), 'paste');
    assert.equal(textInputAction(event(Qt.Key_Enter, '\r', Qt.KeypadModifier), map), 'paste');
    assert.equal(textInputAction(event(Qt.Key_Escape), map), 'back');
    assert.equal(map.paste[0], 'Return');
    assert.equal(map.back[0], 'Escape');
  }
  assert.equal(textInputAction(event(Qt.Key_F1), search), 'back');
});

test('formats readable hints for named keys and leaves bindings intact', () => {
  assert.equal(hint('Up'), '↑');
  assert.equal(hint('Return'), '↵');
  assert.equal(hint('Escape'), 'Esc');
  assert.equal(hint('Shift+Down'), 'Shift+↓');
  assert.equal(hint('Ctrl++'), 'Ctrl++');
  assert.equal(hint('Super+C'), 'Super+C');
});
