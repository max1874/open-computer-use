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

test('editing requires a window editor at publication and delivery', () => {
  const editor = source.slice(source.indexOf('func textEditor('), source.indexOf('let checkableRoles'));
  assert.match(editor, /filename\(of: element, role: role\)\.isEmpty/);
  assert.match(editor, /kAXWindowRole/);
  const operations = source.slice(source.indexOf('func operations('), source.indexOf('func backgroundClickTarget('));
  assert.match(operations, /if textEditor\(element, role: role, surface: surface\)/);
  const execute = source.slice(source.indexOf('func executeAction('), source.indexOf('    case "PRESS":'));
  assert.match(execute, /\["TYPE_TEXT", "PASTE_TEXT", "SELECT_TEXT", "KEY_CHORD"\]/);
  assert.match(execute, /!textEditor\(element, role: string\(element, kAXRoleAttribute\), surface: target.surface\)/);
  assert.match(execute, /throw BridgeError\(message: "target is not a supported window text editor"\)/);
});

test('scrolling uses a proven observed area and native vertical page controls', () => {
  const execute = source.slice(source.indexOf('func executeAction('));
  const scroll = execute.slice(execute.indexOf('    case "SCROLL_UP", "SCROLL_DOWN":'), execute.indexOf('    case "PRESS":'));
  assert.ok(execute.indexOf('try observedTarget(request, app: app)') < execute.indexOf('    case "SCROLL_UP", "SCROLL_DOWN":'));
  assert.match(scroll, /kAXScrollAreaRole/);
  assert.match(scroll, /scrollControls\(element\)/);
  assert.match(scroll, /perform\(button, kAXPressAction\)/);
  assert.doesNotMatch(source, /mainScrollArea|scrollWheelEvent/);
  const bar = source.slice(source.indexOf('func scrollControls('), source.indexOf('func operations('));
  assert.match(bar, /AXIncrementPage/);
  assert.match(bar, /AXDecrementPage/);
  assert.match(bar, /guard !secureField\(area\) else \{ return nil \}/);
  assert.ok(bar.indexOf('guard !secureField(area)') < bar.indexOf('children(area)'));
  assert.match(source, /if role == kAXScrollAreaRole, !secureField\(element\) \{/);
});
