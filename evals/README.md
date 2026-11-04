# Background task acceptance

The 16 task goals and result checks come from the legacy evals branch. Its scripted solves, focus polling, foreground restoration and broad app/window cleanup are not retained. This runner uses the normal `Agent` and the same native executor as the product.

Approve a usage-billed batch before running it. Select tasks explicitly and run only one writer for a shared usage file:

```sh
uv run --env-file .env python -m evals.run \
  --tasks calc-multiply textedit-edit --reps 1 \
  --max-calls 20 --usage-file /absolute/path/batch.json \
  --output /absolute/path/new-acceptance-folder
```

`--max-calls` caps actual HTTP attempts across the batch, including retries, text helpers and prior stages recorded in the same file. An existing file's `approved_calls` must match. This is a limit, not spending authorization. The configured decision backend is used without switching providers. `--max-decisions` bounds one task; reaching a limit never counts as success.

A pass requires all of the following:

- The independent app check is false after setup and true after the real Agent run. No expected answer is injected by a scripted solve. Calculator reads its display, TextEdit its document, Settings its pane title (or a recognized detail heading while the title is unavailable), Safari its window title, and Dictionary its definition text. Finder reads the exact owned window's target directory, so row selection cannot satisfy opening a folder.
- System Settings navigation tasks hold operations other than native row selection, scrolling, waiting and Escape, using the existing approval callback; they never approve unrelated preference changes.
- The Agent ended with `done`. `DONE` with a false reading is recorded separately as `false_done`.
- The activation-event observer started before app setup and ended after cleanup. **Any activation event invalidates this run**, including during cleanup. An unrelated human app switch is conservatively inconclusive; the runner does not label it task-caused or silently exclude it. It never restores foreground focus.
- The owned instance/window was confirmed closed. Missing observer endpoints, native errors and cleanup failures invalidate acceptance.

One task owns one fresh app instance at a time. An already-running target app is preserved and the task is recorded as `not_run`, never passed. Finder owns one exact new window ID and refuses setup when other Finder windows or unknown surfaces exist, because the model sees all of an app's windows. No user app or document is closed to improve a score. The native owner watches stdin through launch and teardown; closing the runner closes its resources, including a launch whose callback arrives late. A 240-second deadline requests teardown; an in-flight launch is awaited so its late callback can supply ownership before closing. Artifacts and cumulative usage are outside the checkout.

`results.jsonl` and per-task records contain before/after readings, the public redacted action history, phase times and activation events. `events.jsonl` preserves the native record; `native.log` keeps helper diagnostics. Skipped, unavailable, limited, failed and unobserved tasks remain visible. A partial run is not a 16-task benchmark, and legacy scores do not describe this code.

This runs the product against real apps and a real configured model. Unit/source-contract suites run in existing CI only; there is no local sensitivity-suite or scripted-solve mode. The Swift ownership helper is built for each invocation. It observes and owns acceptance resources; it has no agent-action execution API.
