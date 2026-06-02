// skills/interclaw_client.js
// Client SDK for other 5 Claws to connect to interclaw_coordinator
// (this OpenClaw is the coordinator)

const HEARTBEAT_INTERVAL_MS = 50 * 1000; // 50s
const POLL_INTERVAL_MS = 15 * 1000; // 15s
const COORDINATOR_SKILL = "interclaw_coordinator";
const GATEWAY_URL = process.env.INTERCLAW_GATEWAY_URL || "http://localhost:18790";

let _log = (msg) => console.log(`[InterClaw] ${msg}`);

export async function callCoordinatorSkill(action, params) {
  // Try HTTP route first; fall back to direct import if running in the
  // coordinator process.
  const url = `${GATEWAY_URL}/${action}`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Bypass-Tunnel-Reminder": "true"
      },
      body: JSON.stringify(params || {})
    });
    if (res.ok) return await res.json();
    _log(`HTTP ${res.status} on ${action}, falling back to direct import`);
  } catch (e) {
    _log(`HTTP failed (${e.message}), trying direct import`);
  }

  // Direct import fallback (works when co-located with coordinator)
  try {
    const mod = await import("./interclaw_coordinator.js");
    const skill = mod.default;
    if (typeof skill[action] !== "function") {
      throw new Error(`Skill has no method ${action}`);
    }
    return await skill[action](params || {});
  } catch (e) {
    throw new Error(`callCoordinatorSkill(${action}) failed: ${e.message}`);
  }
}

export async function registerToCoordinator(agent_id, skills = [], metadata = {}) {
  _log(`Registering ${agent_id} (skills: ${skills.join(",")})`);
  return await callCoordinatorSkill("registerAgent", { agent_id, skills, metadata });
}

export async function sendHeartbeat(agent_id) {
  return await callCoordinatorSkill("heartbeat", { agent_id });
}

export async function sendTaskToClaw(from_agent, task_type, payload, to = null) {
  _log(`sendTask ${task_type} from ${from_agent} → ${to || "auto-route"}`);
  return await callCoordinatorSkill("sendTask", { from_agent, to, task_type, payload });
}

export async function checkMyTasks(agent_id) {
  const r = await callCoordinatorSkill("getMyTasks", { agent_id });
  return r.tasks || [];
}

export async function startInterClawLoop({ agent_id, skills = [], metadata = {}, onTask = null, log = null }) {
  if (log) _log = log;
  if (!agent_id) throw new Error("agent_id required");

  await registerToCoordinator(agent_id, skills, metadata);

  setInterval(() => {
    sendHeartbeat(agent_id).catch(e => _log(`heartbeat err: ${e.message}`));
  }, HEARTBEAT_INTERVAL_MS);

  setInterval(async () => {
    try {
      const tasks = await checkMyTasks(agent_id);
      for (const task of tasks) {
        _log(`Task from ${task.from_agent}: ${task.task_type}`);
        if (onTask) {
          try { await onTask(task); } catch (e) {
            _log(`onTask error: ${e.message}`);
          }
        }
      }
    } catch (e) {
      _log(`poll err: ${e.message}`);
    }
  }, POLL_INTERVAL_MS);

  _log(`Loop started (heartbeat ${HEARTBEAT_INTERVAL_MS/1000}s, poll ${POLL_INTERVAL_MS/1000}s)`);
}

export default { callCoordinatorSkill, registerToCoordinator, sendHeartbeat, sendTaskToClaw, checkMyTasks, startInterClawLoop };
