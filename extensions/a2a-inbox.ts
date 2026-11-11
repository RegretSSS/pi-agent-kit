import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const HEARTBEAT_MS = 20000;
const RESOLVE_MS = 5000;
const LANDING_CONFIRM_MS = 1500;
const LANDING_MAX_ATTEMPTS = 36;
const LANDING_MARKER_CHARS = 60;

function mailboxRoot(): string {
  return process.env.A2A_MAILBOX_ROOT || path.join(os.homedir(), ".agents-mailbox");
}

function readJson(file: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function paneOf(rec: Record<string, unknown>): string {
  return typeof rec.pane_id === "string" ? rec.pane_id : "";
}

function instancePanes(rec: Record<string, unknown>): string[] {
  const instances = rec.instances;
  if (!instances || typeof instances !== "object") {
    return [];
  }
  return Object.values(instances as Record<string, Record<string, unknown>>)
    .map((entry) => (typeof entry.pane_id === "string" ? entry.pane_id : ""))
    .filter(Boolean);
}

function resolveAgentId(root: string): string | null {
  const registry = readJson(path.join(root, "registry.json"));
  const agents = (registry?.agents ?? {}) as Record<string, Record<string, unknown>>;
  const pane = process.env.TMUX_PANE || "";
  if (pane) {
    for (const [id, rec] of Object.entries(agents)) {
      if (rec.cli !== "pi") {
        continue;
      }
      if (paneOf(rec) === pane || instancePanes(rec).includes(pane)) {
        return id;
      }
    }
  }
  let hit: string | null = null;
  for (const [id, rec] of Object.entries(agents)) {
    if (rec.cli !== "pi" || rec.cwd !== process.cwd()) {
      continue;
    }
    if (hit !== null) {
      return null;
    }
    hit = id;
  }
  return hit;
}

function targetedAtOtherInstance(envelope: Record<string, unknown>, pane: string): boolean {
  const target = envelope.to_instance;
  if (typeof target !== "string" || !target) {
    return false;
  }
  return pane !== "" && target !== pane;
}

type BranchLike = {
  getBranch(): { type: string; message?: { role?: string; content?: { type: string; text?: string }[] } }[];
};

export default function (pi: ExtensionAPI) {
  const root = mailboxRoot();
  let agentId: string | null = null;
  let watcher: fs.FSWatcher | null = null;
  let heartbeat: ReturnType<typeof setInterval> | null = null;
  let resolver: ReturnType<typeof setInterval> | null = null;
  let rescuer: ReturnType<typeof setInterval> | null = null;
  let branch: BranchLike | null = null;
  const injected = new Set<string>();
  const inflight = new Set<string>();
  const attempts = new Map<string, number>();

  function wakeLanded(marker: string): boolean {
    if (!branch) {
      return false;
    }
    try {
      for (const entry of branch.getBranch()) {
        if (entry.type !== "message" || entry.message?.role !== "user") {
          continue;
        }
        for (const part of entry.message.content ?? []) {
          if (part.type === "text" && typeof part.text === "string" && part.text.includes(marker)) {
            return true;
          }
        }
      }
    } catch {}
    return false;
  }

  function agentDir(): string {
    return path.join(root, "native-inbox", agentId as string);
  }

  function beat(): void {
    try {
      fs.mkdirSync(agentDir(), { recursive: true });
      const file = path.join(agentDir(), "alive.json");
      const tmp = `${file}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify({ pid: process.pid, ts: Date.now() / 1000 }));
      fs.renameSync(tmp, file);
    } catch {}
  }

  function takeMsg(file: string): void {
    if (!agentId) {
      return;
    }
    const envelope = readJson(file);
    if (!envelope || typeof envelope.msg_id !== "string") {
      return;
    }
    const msgId = envelope.msg_id;
    const wakeText = envelope.wake_text;
    if (typeof wakeText !== "string" || !wakeText) {
      return;
    }
    if (targetedAtOtherInstance(envelope, process.env.TMUX_PANE || "")) {
      return;
    }
    if (injected.has(msgId) || inflight.has(msgId)) {
      return;
    }
    const ackId = envelope.ack_id;
    if (typeof ackId === "string" && fs.existsSync(path.join(root, "acks", ackId))) {
      return;
    }
    const rcpt = path.join(agentDir(), `rcpt-${msgId}`);
    if (fs.existsSync(rcpt)) {
      injected.add(msgId);
      return;
    }
    const marker = wakeText.slice(0, LANDING_MARKER_CHARS);
    if (wakeLanded(marker)) {
      markDelivered(msgId, rcpt);
      return;
    }
    if ((attempts.get(msgId) ?? 0) >= LANDING_MAX_ATTEMPTS) {
      markDelivered(msgId, rcpt);
      return;
    }
    attempts.set(msgId, (attempts.get(msgId) ?? 0) + 1);
    inflight.add(msgId);
    try {
      pi.sendUserMessage(wakeText, { deliverAs: "steer" });
    } catch {
      inflight.delete(msgId);
      return;
    }
    setTimeout(() => {
      if (wakeLanded(marker)) {
        markDelivered(msgId, rcpt);
      } else {
        inflight.delete(msgId);
      }
    }, LANDING_CONFIRM_MS);
  }

  function markDelivered(msgId: string, rcpt: string): void {
    try {
      const handle = fs.openSync(rcpt, "wx");
      fs.writeSync(handle, JSON.stringify({ ts: Date.now() / 1000 }));
      fs.closeSync(handle);
      injected.add(msgId);
    } catch {}
    inflight.delete(msgId);
    attempts.delete(msgId);
  }

  function scanQueue(): void {
    if (!agentId) {
      return;
    }
    const dir = path.join(root, "queue", agentId);
    let names: string[] = [];
    try {
      names = fs.readdirSync(dir);
    } catch {
      return;
    }
    for (const name of names) {
      if (name.endsWith(".msg")) {
        takeMsg(path.join(dir, name));
      }
    }
  }

  function startWatching(): void {
    const dir = path.join(root, "queue", agentId);
    try {
      fs.mkdirSync(dir, { recursive: true });
    } catch {}
    watcher = fs.watch(dir, () => scanQueue());
    beat();
    heartbeat = setInterval(beat, HEARTBEAT_MS);
    heartbeat.unref?.();
    scanQueue();
  }

  function tryResolve(): void {
    if (agentId) {
      return;
    }
    agentId = resolveAgentId(root);
    if (!agentId) {
      return;
    }
    if (resolver) {
      clearInterval(resolver);
      resolver = null;
    }
    startWatching();
  }

  resolver = setInterval(tryResolve, RESOLVE_MS);
  resolver.unref?.();
  rescuer = setInterval(scanQueue, RESOLVE_MS);
  rescuer.unref?.();
  tryResolve();

  pi.on("session_start", (_event, ctx) => {
    branch = ctx.sessionManager as unknown as BranchLike;
  });

  pi.on("session_shutdown", () => {
    if (watcher) {
      watcher.close();
    }
    if (heartbeat) {
      clearInterval(heartbeat);
    }
    if (resolver) {
      clearInterval(resolver);
    }
    if (rescuer) {
      clearInterval(rescuer);
    }
  });
}
