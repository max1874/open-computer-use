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

**Read a menu after it opens.** Blocks two things at once: `AXShowMenu` is kept
out of the action space, and `SELECT` has never been offered — 40 pop-up and
menu buttons counted across five apps, 0 exposing a menu item while closed. An
open menu is its own window and the snapshot reads the focused one, so the work
is cross-window observation, not a new operation. Cost to weigh first: an open
menu holds the screen for as long as it is open. Do not start this without
saying that out loud.

**Give `SELECT` a post-execution read-back.** Only after the above. Today it
confirms that `AXUIElementPerformAction` returned success and reads nothing
back, unlike `TYPE_TEXT`. Pointless while the operation is never offered.

## Known gaps, no plan

- **Text input is not general.** `TYPE_KEYS` maps characters the keyboard
  layout can produce; CJK and emoji go through Unicode events. Key combinations,
  paste, and text selection are not addressable at all.
- **Drag has no representation.** Neither does a custom-drawn canvas.
- **One window, one app.** No sheets belonging to other windows, no workflows
  that cross apps. This is a design boundary, not an oversight — moving it
  changes what a snapshot is.
- **The pixel fallback gets little exercise.** Since the traversal-depth fix it
  fires far less often than it was built to, so it is the least-tested path in
  the project per line of code.
