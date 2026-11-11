# Comparable projects

Read against source, not only README. Update an entry when its project or ours changes a claim below.

## vercel-labs/agent-desktop

[agent-desktop](https://github.com/vercel-labs/agent-desktop) (Vercel Labs, Rust, Apache-2.0, started 2026-02) is the closest project: a computer-use CLI that reads the OS accessibility tree and acts on refs, with no model inside. Read at commit `b43ac4f` (2026-11-05).

**Shared design.** Both observe the accessibility tree instead of pixels, bind every target to the observation that produced it and refuse stale or ambiguous ones, act headless by default through semantic AX actions, and send keys to the target process (`CGEventPostToPid`). Both classify delivery so that only an undelivered action may be retried (`crates/core/src/actions/delivery_semantics.rs`: `NotDelivered` is `safe`, uncertain or delivered is `unsafe`). Both mark secure text fields and omit their values. Its `jev-desktop` skill uses the same per-turn shape as our Agent: one request picks the operation and its target. Its real-app acceptance (`tests/real-apps/acceptance-v1.md`, frozen 2026-09-20) uses the same method as our evals: independent readback from the app, plus `NSWorkspace` activation and input-event counters recorded through each action (`tests/real-apps/headless_probe.swift`); it reports "Overall measured score: not established".

**Where it is broader.** macOS, Windows (UI Automation) and Linux (AT-SPI); about 60 commands covering windows, notifications, clipboard, waits and batches; an MCP server and a C library; npm and Homebrew distribution.

**Where the contract differs.**

| | agent-desktop | open-computer-use |
| --- | --- | --- |
| Focus | Headless is the default; `--headed`, `focus-window` and app activation (`activateWithOptions`) exist as escape hatches | The bridge has no activation, pointer or screenshot path; an unsupported surface stops |
| Acceptance | Same method in `tests/real-apps`; no measured score published | Same method in `evals/`; one single-run reading of 11 / 16 tasks with zero activations (2026-11-03, `max/evals` branch, before later changes) |
| Action space | Wide, one command per capability | `observe` / `act`; a new operation is measured against tasks that do not need it |
| Model | None; `jev-desktop` lives in the repository as a skill | Optional built-in Agent with an OpenAI-compatible or Jev backend |
| Whole-Mac changes | No gate found | System Settings runs navigation only unless the caller passes `--machine-wide` |

What to watch: the method is shared, so the comparison that matters is a measured one. If agent-desktop publishes task results with zero activations, our remaining distinctions are the System Settings gate, the built-in Agent and the smaller action space. Background double-click, triple-click, hover and drag need `--headed` in agent-desktop and are absent here; neither project does them without activation.

### Background mouse probe, 2026-11-10

A throwaway Swift probe sent synthetic mouse events to one process while another app stayed frontmost, and read each result back from the app (window title, file on disk, `AXSelectedTextRange`) with an activation observer running.

- Window number in fields 91/92, with or without the private `CGEventSetWindowLocation`, `SLEventPostToPid`, or a HID or private-state source: no effect in any case (24 attempts), zero activations.
- Window number in field 51 plus field 58, posted with public `CGEventPostToPid`, the recipe measured in [callstack/agent-device#3213](https://github.com/callstack/agent-device/issues/3213) (item 13, credited there to cua): TextEdit triple-click selected the line, zero activations, pointer unchanged. Finder double-click to open a folder failed at the name, icon, row edge and row centre. Drags failed in both apps; #3213 measured drags as needing the private focus-without-raise call (`SLPSPostEventRecordTo`), which makes the app AppKit-active while the frontmost app stays unchanged.
- Finder's `AXOpen` on the row is unsupported (-25205); `AXConfirm` succeeds and does nothing. Selecting the row and posting Cmd-Down to Finder's pid does not open it either.

With the private focus-without-raise record (`SLPSPostEventRecordTo` to the window's process, both the desktopctl `0x0D` record and yabai's make-key pair) before the fields 51/58 post: Finder double-click opened the folder and TextEdit triple-click selected the line, each twice, with the frontmost app, menu-bar owner and window stacking unchanged and no activation notification. Drags still failed: Finder file-into-folder in four attempts, TextEdit drag-select in two (a third was invalidated when the screen locked mid-run). Not measured: where a real keystroke goes right after the focus record. The test beds (open a folder, select a line) are terminal-reachable, so these runs establish the input mechanism, not a product need; no task without a terminal route has yet been shown to need double-click.

agent-desktop does not set field 51 (`crates/macos/src/input/mouse/mod.rs` sets only the click state), which is why its double-click, triple-click and secondary click need `--headed`.
