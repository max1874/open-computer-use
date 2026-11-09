# Comparable projects

Read against source, not only README. Update an entry when its project or ours changes a claim below.

## vercel-labs/agent-desktop

[agent-desktop](https://github.com/vercel-labs/agent-desktop) (Vercel Labs, Rust, Apache-2.0, started 2026-02) is the closest project: a computer-use CLI that reads the OS accessibility tree and acts on refs, with no model inside. Read at commit `b43ac4f` (2026-11-05).

**Shared design.** Both observe the accessibility tree instead of pixels, bind every target to the observation that produced it and refuse stale or ambiguous ones, act headless by default through semantic AX actions, and send keys to the target process (`CGEventPostToPid`). Both classify delivery so that only an undelivered action may be retried (`crates/core/src/actions/delivery_semantics.rs`: `NotDelivered` is `safe`, uncertain or delivered is `unsafe`). Its `jev-desktop` skill uses the same per-turn shape as our Agent: one request picks the operation and its target.

**Where it is broader.** macOS, Windows (UI Automation) and Linux (AT-SPI); about 60 commands covering windows, notifications, clipboard, waits and batches; an MCP server and a C library; npm and Homebrew distribution.

**Where the contract differs.**

| | agent-desktop | open-computer-use |
| --- | --- | --- |
| Focus | Headless is the default; `--headed`, `focus-window` and app activation (`activateWithOptions`) exist as escape hatches | The bridge has no activation, pointer or screenshot path; an unsupported surface stops |
| Acceptance | The agent snapshots again | The result read back from the app, plus an independent record of zero app activations over the whole task |
| Action space | Wide, one command per capability | `observe` / `act`; a new operation is measured against tasks that do not need it |
| Model | None; `jev-desktop` lives in the repository as a skill | Optional built-in Agent with an OpenAI-compatible or Jev backend |

What to watch: if agent-desktop adds a mode that guarantees no activation for a whole task and measures it, our remaining distinction is the activation record as acceptance and the smaller action space.
