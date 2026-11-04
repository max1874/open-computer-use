# open-computer-use

Read README.md and docs/design.md before editing. Keep one loop:
window → indexed elements → operation + target → guarded execution → observe.

- Essential variables: the requested result is observed in the target app, and the entire task takes foreground focus zero times. Neither DONE nor an inactive endpoint proves acceptance. Observe macOS app-activation events independently across the same task interval; a transient activation followed by restoration still fails.
- One app and one natural-language goal. No per-app scripts, invented coordinates or generated executable code.
- The native bridge is the only executor. Do not reintroduce activation, mouse input, dragging, screenshots, a visual fallback or host-specific execution loops. Unsupported surfaces stop explicitly.
- Keep app-local field focus and selection separate from activating an application. Keyboard events go only to the target process. Native row CLICK must refuse when its capability disappears; no physical fallback.
- One request chooses the operation, every target head and risk on the same observed state. Consume only the matching head. The model may choose only observed targets and supported operations.
- Never replay a mutation. Consume its decision before input and record delivery before post-action observation. Unknown delivery stops with history intact. Preserve returned focus facts even if read-back fails.
- Capture-time uniqueness and a fresh target census guard execution. Unknown identities, incomplete reads and process replacement refuse input. Preserve secure classification before value reads, redacted history, separate AX deadlines and bridge replacement after transport failure.
- Keep the action space small. INCREMENT/DECREMENT once changed Calculator from 6/6 to 1/8 despite identical observations; they stay unoffered. Measure any new operation against tasks that do not need it.
- Preserve separate content/control publication budgets. A content-heavy window must not hide its toolbar. Static text names come from their values. Inspect traversal depth before declaring an Electron app inaccessible.
- SELECT needs observed options. Do not expand it based on an unmeasured assumption that closed menus expose choices. Popup/menu-opening presses can activate apps and stay withheld.
- No token-probability reconstruction, extra planner or new compatibility framework without a concrete product requirement.
- Read the requested result back from the real app. Unit tests, source contracts and builds supplement that reading; they do not replace it. Local stand-in model runs prove plumbing only, never model accuracy.
- Keep README claims and measured evidence in sync. Task windows and temporary services close in finally; never quit or close another user's documents to clean up an example.
- Credentials stay in the ignored .env. Local verification runs the product; test/check suites run in CI only.

Build: `scripts/build.sh`. The existing CI runs Python contracts, native-source regression guards and the Swift build. Do not change CI definitions without Max's explicit request.
