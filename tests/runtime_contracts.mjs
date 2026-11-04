// CI-only regression guards for the native execution boundary.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../open_computer_use/axbridge.swift', import.meta.url), 'utf8');

test('the native bridge has no activation, cursor delivery or screenshot escape hatch', () => {
  for (const forbidden of [/\.activate\s*\(/, /cghidEventTap/, /mouseEventSource/,
                           /case "activate"/, /case "capture"/, /case "DRAG"/, /CGPreflightScreenCaptureAccess/]) {
    assert.doesNotMatch(source, forbidden);
  }
  assert.match(source, /event\.postToPid\(pid\)/);
  assert.match(source, /unsupported background operation/);
});

test('native row clicks cannot fall through to a physical pointer route', () => {
  const click = source.slice(source.indexOf('    case "CLICK":'), source.indexOf('    case "INCREMENT"'));
  assert.match(click, /guard let target = backgroundClickTarget/);
  assert.match(click, /throw BridgeError/);
  assert.match(click, /setAttribute\(target.element, target.attribute, target.value\)/);
});

test('all editing keys stay inside the native field-command whitelist', () => {
  const field = source.slice(source.indexOf('    case "KEY_CHORD":'), source.indexOf('    case "SELECT_TEXT":'));
  assert.match(field, /guard editingKeys.contains\(key\)/);
  assert.ok(field.indexOf('guard editingKeys') < field.indexOf('try focus('));
  assert.doesNotMatch(field, /cmd\+tab|cmd\+q/);
});
