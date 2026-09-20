// The executor half, for Codex Computer Use.
//
// This file runs inside the host's JavaScript runtime, where a global `sky`
// (or `cua`) already exists — that is the whole reason it is JavaScript and the
// rest of this project is not. It observes, hands the tree to the decision
// process, and performs what comes back.
//
//   const { runTask } = await import("file:///path/to/repo/runtime/loop.mjs");
//   await runTask({ sky, app: "Calculator", goal: "Compute 12 times 34", dryRun: true });
//
// Nothing here decides anything. It also does not interpret what it is given
// beyond looking the index up in the tree it just read: what crosses the pipe
// is a number out of that text, and if it is not in there, nothing runs.

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// The app's own schedule, not ours. The host already waits for the interface
// to settle after an action, so this is only for the operation it cannot see.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** The decision process: one JSON line in, one JSON line out. */
function decider({ python = "python3", env = {} } = {}) {
  const child = spawn(python, ["-m", "open_computer_use.decide"], {
    cwd: REPO,
    env: { ...process.env, ...env },
    stdio: ["pipe", "pipe", "pipe"],
  });
  let buffer = "";
  const waiting = [];
  child.stdout.on("data", (chunk) => {
    buffer += chunk.toString();
    let cut;
    while ((cut = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, cut).trim();
      buffer = buffer.slice(cut + 1);
      if (line && waiting.length) waiting.shift()(JSON.parse(line));
    }
  });
  let errors = "";
  child.stderr.on("data", (chunk) => (errors += chunk.toString()));
  child.on("exit", (code) => {
    while (waiting.length) waiting.shift()({ error: `decider exited ${code}: ${errors.slice(-400)}` });
  });
  return {
    ask(request) {
      return new Promise((resolve) => {
        waiting.push(resolve);
        child.stdin.write(JSON.stringify(request) + "\n");
      });
    },
    stop() {
      child.stdin.end();
      child.kill();
    },
  };
}

/** Everything this loop is allowed to do, and the one place it does it. */
async function perform(sky, app, decision) {
  const index = decision.index;
  switch (decision.operation) {
    case "PRESS":
    case "CLICK":
      return sky.click({ app, element_index: Number(index) });
    case "TYPE_TEXT":
      return sky.set_value({ app, element_index: Number(index), value: String(decision.text ?? "") });
    case "SCROLL_UP":
      return sky.scroll({ app, element_index: Number(index), direction: "up", pages: 1 });
    case "SCROLL_DOWN":
      return sky.scroll({ app, element_index: Number(index), direction: "down", pages: 1 });
    case "PRESS_RETURN":
      return sky.press_key({ app, key: "Return" });
    case "PRESS_ESCAPE":
      return sky.press_key({ app, key: "Escape" });
    case "WAIT":
      return sleep(400);
    default:
      throw new Error(`this loop does not perform ${decision.operation}`);
  }
}

export async function runTask({
  sky,
  app,
  goal,
  dryRun = true,
  maxSteps = 40,
  riskThreshold = 0.5,
  approve = null, // (decision) => boolean, for anything rated at or above the threshold
  python = "python3",
  env = {},
  emit = (line) => (globalThis.nodeRepl?.write ? nodeRepl.write(line + "\n") : console.log(line)),
}) {
  if (!sky) throw new Error("runTask needs the host's `sky`");
  const ask = decider({ python, env });
  const history = [];
  let refused = [];
  try {
    for (let step = 1; step <= maxSteps; step++) {
      // Re-read every step. The indices are only valid for the observation
      // that produced them, so there is no such thing as a stale index here —
      // only a stale tree, and this is how it stops being one.
      const state = await sky.get_app_state({ app, disableDiff: true });
      const decision = await ask.ask({
        goal,
        ax: state.text,
        history: history.slice(-10),
        refused,
        risk_threshold: riskThreshold,
      });
      if (decision.error) return finish("error", { step, message: decision.error });

      const where = decision.index == null ? "" : ` [${decision.index}] ${decision.label ?? ""}`;
      emit(`[${step}] ${decision.operation}${where} risk=${Number(decision.risk).toFixed(2)} ${decision.latency_ms}ms`);

      if (decision.operation === "DONE") return finish("done", { step, decision });
      if (decision.operation === "BLOCKED") return finish("blocked", { step, decision });
      if (decision.held && !(approve && approve(decision))) {
        return finish("needs_approval", { step, decision });
      }
      if (dryRun) return finish("dry_run", { step, decision });

      // Recorded before it is performed, so an observation that arrives after
      // a change cannot erase the operation that caused it.
      const record = {
        operation: decision.operation,
        label: decision.label,
        text: decision.text ?? null,
        window_changed: null,
      };
      history.push(record);
      try {
        await perform(sky, app, decision);
      } catch (error) {
        // The executor refused, so nothing ran, so the run continues — and
        // that target is not offered again until the tree changes.
        record.outcome = "failed";
        record.window_changed = false;
        if (decision.index != null) refused = refused.concat([[decision.operation, decision.index]]);
        emit(`      refused: ${error.message}`);
        continue;
      }
      const after = await sky.get_app_state({ app, disableDiff: true });
      record.window_changed = after.text !== state.text;
      if (record.window_changed) refused = [];
      emit(`      ${record.window_changed ? "the window changed" : "nothing changed"}`);

      const recent = history.slice(-3);
      if (recent.length === 3 && recent.every((h) => h.window_changed === false)) {
        return finish("blocked", { step, message: "three operations changed nothing" });
      }
    }
    return finish("max_steps", { step: maxSteps });
  } finally {
    ask.stop();
  }

  function finish(status, extra) {
    emit(`[done] ${status}${extra.message ? ": " + extra.message : ""}`);
    return { status, history, ...extra };
  }
}
