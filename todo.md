# Remaining boundaries

- **One app per run.** Accessible windows and open menus are included; cross-app workflows require an outer coordinator.
- **Native background capabilities vary.** `CLICK` selects an observed native row where supported. Arbitrary pointer input, dragging and inaccessible canvases are outside the product scope. A future capability must complete its task without taking focus; a frontmost workaround is not equivalent.
- **App actions can affect focus.** The bridge never activates an app or moves the pointer. A full-run activation-event record is still required alongside the intended application result. Endpoint `took_focus` alone cannot prove absence of transient focus theft.
- **Model completion varies.** Reliable delivery does not establish good planning. Existing unchanged-state stopping does not catch every state-changing cycle. A measured secure-field model run repeated correctly delivered input because it could not inspect the hidden value; native delivery/redaction passed, autonomous secure-field completion did not.

Identity proof, process binding, batched metadata, deadlines, transport recovery, fresh permission probes, secure-field redaction and native field editing remain part of the supported execution path. CI covers their declared contracts and the Swift build; actual background task completion is verified in the running product.
