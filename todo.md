# Remaining boundaries

- **One app per run.** Accessible windows and open menus are included; cross-app workflows require an outer coordinator.
- **Native background capabilities vary.** `CLICK` selects an observed native row where supported. Arbitrary pointer input, dragging and inaccessible canvases are outside the product scope. A future capability must complete its task without taking focus; a frontmost workaround is not equivalent.
- **App actions can affect focus.** The bridge never activates an app or moves the pointer. A full-run activation-event record is still required alongside the intended application result. Endpoint `took_focus` alone cannot prove absence of transient focus theft.
- **Model completion varies.** Reliable delivery does not establish good planning. Repeated state/action pairs now stop before a third delivery, including cycles that return to a previous state. The heuristic cannot detect every changing or hidden state. A measured secure-field model run repeated correctly delivered input because it could not inspect the hidden value; stopping such repetitions remains blocked, not autonomous secure-field completion.

Identity proof, process binding, batched metadata, deadlines, transport recovery, fresh permission probes, secure-field redaction and native field editing remain part of the supported execution path. CI covers their declared contracts and the Swift build; actual background task completion is verified in the running product.
