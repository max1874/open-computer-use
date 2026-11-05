# One background execution path

The essential variables are the requested result in the target app and zero foreground-focus theft throughout that task. The input is one app and one natural-language goal:

```text
native observation → indexed operation/target choices → one guarded execution → native read-back
```

`actions.py` owns the pure table and answer schema. Model element refs use an `e` prefix (for example `e15`) so a numeric button label such as `2` cannot be mistaken for the reference itself. The prefix never enters a native path or identity; menu refs already have their own `m` prefix. `model.py` asks an OpenAI-compatible chat backend or Jev and validates its choice against that table. `Agent` owns prediction, risk approval and execution; public commands publish one snapshot. One history method owns identity and input redaction, and one observation method invalidates refusals when the window changes.

## Delivery boundary

The native bridge has no app-activation, mouse-event or screenshot entry point. Retired operations are rejected before dispatch. `CLICK` can only use the captured element's native row-selection capability. A missing capability is a refusal, never permission to use HID. Dragging and inaccessible canvases are outside scope.

Scroll operations target a published `AXScrollArea`. Its vertical scroll bar's enabled native page controls and current position supply the supported directions. Execution re-identifies the area and reads the controls again before `AXPress`; position read-back verifies scrolling, while the independent application check establishes navigation or task completion. Protected containers are not traversed. Container descriptions such as a native outline's Sidebar label name the area. The largest-area guess and synthesized wheel-event path are removed.

File-name fields identified by native `AXFilename` are item labels: they are named from that attribute and offer only native row selection. The executor rejects editing requests for them as well. Editing also requires a genuine `AXWindow` surface; Finder's detached rename editor, parented directly to the app, cannot become a document editor simply by appearing in `AXWindows`. This does not classify every text field inside a row as a label; ordinary editable table cells retain field editing.

App-local field focus and selection remain necessary for editing. Keyboard events are addressed to the process and restricted to the existing editing operations. Opening popup/menu buttons is withheld because AppKit can activate the app to show the menu. Already-open menus remain observable. Menu-bar commands are offered only when the target is already active; it is never activated to obtain them.

Native actions can themselves affect focus. Endpoint `took_focus` facts are diagnostic samples, not a continuous guarantee. Acceptance observes macOS activation events independently over the entire task, and reads the resulting application state independently of `DONE`. A transient focus steal fails, even if focus returns before the action reply. A focus fact already returned by input must survive a failed post-action observation.

## Observation and identity

Snapshots include accessible windows and open menus. Control and content publication budgets are separate from the bounded full-surface identity census. Offscreen and zero-size controls are not offered, but unpublished competitors still count toward uniqueness. Unknown competing names and incomplete enumeration prevent identity proof. A fully enumerated surface with only one node of a role has no competing name to resolve. Optional diagnostic-description failures must not invalidate an already-proven role/ID; unknown editable security subroles still fail closed.

Each observation holds bounded references bound to PID plus process start time. Role, label and optional identifier must be unique within the same native surface. Execution re-identifies against a fresh census, so reordered child indices cannot silently select another element. Process replacement invalidates the observation.

AX metadata is batched and cached only for a traversal. Secure classification precedes values and diagnostics; secure descendants are not traversed. Unknown editable subroles are treated as secure. Secure writes skip value read-back and public history excludes their input.

Freshness compares semantic state, including values and selection, without geometry. Text generation and accepting `DONE` require a fresh window; individual input guards its target. This scope is a heuristic about unrelated changes, not proof they are irrelevant.

## Results and failures

Delivery is `not_delivered`, `delivery_uncertain`, `delivered_unverified` or `delivered_verified`. Only proven pre-dispatch refusal is retry-safe. The agent consumes decisions once and records execution before observation; uncertain input stops without replay. Window changes show progress, not causation or final task success. The caller's outcome check decides whether `DONE` is justified.

Read and write AX deadlines are separate. A read failure invalidates the observation. Request/reply exchange and helper replacement share one lock; timeout or malformed reply discards the helper so late replies cannot contaminate another request. Permission probes use a fresh process.

## Model and inspector

One request chooses the operation, a speculative target for each operation, field values where supported, and risk. Only the matching target head executes. Jev returns choices; its field values use the text helper. Chat returns JSON schema or JSON object output. Both are validated at the same boundary. Token-logprob reconstruction and probability charts are absent.

The inspector displays the table, pending decision, risk and executed history. It binds to loopback, checks Host/Origin, requires a startup token and serializes commands. It has no activation control. Its `DONE` state remains a model claim unless an outcome check supplied evidence.

Budgets remain 40 operations, 80 decisions and three consecutive unchanged actions. History also records each pre-action fingerprint and editing parameters. Two delivered matching state/action pairs block a third input, including A → B → A cycles; refusals do not count and WAIT is exempt. The check runs before field-value generation, uses the existing redacted history path, and rechecks freshness before refusing. No parallel counter or planner state is added. A blocked repetition does not establish task completion or progress in hidden fields.
