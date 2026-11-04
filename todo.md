# Not done

README's "Known limits" says what this cannot do today. This file says which of
those are meant to move, what each one is actually blocked on, and what it would
cost. Nothing here is scheduled.

## Would remove a real constraint

**Deliver an arbitrary click without taking the screen.** Native row selection
now delivers indexed `CLICK` in the background where the element's nearest row
supports it. Measured on System Settings behind other windows: both
`AXRow.AXSelected = true` and `AXOutline.AXSelectedRows = [row]` navigate from
General to Wi-Fi and Appearance, with no FocusWatch events. Targets without that
capability are still hidden without pointer permission; native delivery never
falls back to HID. Finder's measured file-list names are `TYPE_TEXT`, not
`CLICK`-only; row selection leaves the folder unopened, and an advertised
`AXOpen` on its filename returned `-25205` while the observed window stayed on
the containing folder.

The mouse-event experiment did not remove the pixel path's constraint:
`.leftMouseDown`/`.leftMouseUp` posted to System Settings' pid at each sidebar
target left General unchanged, with no focus events and identical pointer
positions. No process-targeted mouse delivery is offered. `CLICK_POINT` and
pointer-only `CLICK` retain their foreground and occlusion guards. A different
background mouse mechanism would need its own measurement before changing that.

## Remaining boundaries

- **One app per run.** Multiple windows, sheets and menus are now observed;
  workflows crossing applications still require an outer coordinator.
- **Model task success varies.** The final calculator comparison completed
  3/4 cases against 4/4 for the baseline, despite identical requests for the
  same single-window observation. The failed run repeated digits and Clear.
  This small sample cannot establish a regression or an improvement; do not
  equate reliable delivery with reliable planning.
- **Sparse pixel windows remain the least exercised path.** Indexed and
  screenshot-bound dragging have native application read-back. Each new canvas
  still needs its own outcome check, and pointer delivery requires foreground
  and occlusion guards.

The implemented backlog covers observation-time uniqueness, process-generation
binding, batched AX metadata, fresh permission probes, truncation metadata,
open-menu observation and SELECT read-back, observed-field editing, indexed and
screenshot-bound dragging, multi-window observation and CI contract/build gates.
