// interclaw_coordinator.js
// Central coordinator for multi-claw mesh
// All other Claws register to this one

import fs from 'fs';
import path from 'path';

const AGENT_DIR = '/home/node/.openclaw/data/interclaw';
const TASK_FILE = path.join(AGENT_DIR, 'tasks.json');
const AGENTS_FILE = path.join(AGENT_DIR, 'agents.json');

if (!fs.existsSync(AGENT_DIR)) {
  fs.mkdirSync(AGENT_DIR, { recursive: true });
}
if (!fs.existsSync(TASK_FILE)) {
  fs.writeFileSync(TASK_FILE, JSON.stringify({ tasks: [] }, null, 2));
}
if (!fs.existsSync(AGENTS_FILE)) {
  fs.writeFileSync(AGENTS_FILE, JSON.stringify({ agents: {} }, null, 2));
}

function loadTasks() {
  return JSON.parse(fs.readFileSync(TASK_FILE, 'utf8'));
}
function saveTasks(data) {
  fs.writeFileSync(TASK_FILE, JSON.stringify(data, null, 2));
}
function loadAgents() {
  return JSON.parse(fs.readFileSync(AGENTS_FILE, 'utf8'));
}
function saveAgents(data) {
  fs.writeFileSync(AGENTS_FILE, JSON.stringify(data, null, 2));
}

export async function registerAgent({ agent_id, skills = [], metadata = {} }) {
  const agents = loadAgents();
  agents.agents[agent_id] = {
    agent_id,
    skills,
    metadata,
    registered_at: new Date().toISOString(),
    last_heartbeat: new Date().toISOString(),
    status: 'online'
  };
  saveAgents(agents);
  console.log(`[coordinator] Registered ${agent_id} (skills: ${skills.join(',')})`);
  return { ok: true, agent_id, registered_at: agents.agents[agent_id].registered_at };
}

export async function heartbeat({ agent_id }) {
  const agents = loadAgents();
  if (!agents.agents[agent_id]) {
    // Auto-register if not exists
    return await registerAgent({ agent_id, skills: [], metadata: {} });
  }
  agents.agents[agent_id].last_heartbeat = new Date().toISOString();
  agents.agents[agent_id].status = 'online';
  saveAgents(agents);
  return { ok: true, agent_id, last_heartbeat: agents.agents[agent_id].last_heartbeat };
}

export async function sendTask({ from_agent, to = null, task_type, payload = {} }) {
  const tasks = loadTasks();
  const task = {
    id: `task_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`,
    from_agent,
    to,
    task_type,
    payload,
    created_at: new Date().toISOString(),
    status: 'pending'
  };
  tasks.tasks.push(task);
  saveTasks(tasks);
  console.log(`[coordinator] Task ${task.id}: ${task_type} from ${from_agent} → ${to || 'auto-route'}`);
  return { ok: true, task_id: task.id };
}

export async function getMyTasks({ agent_id }) {
  const tasks = loadTasks();
  const myTasks = tasks.tasks.filter(t => 
    t.status === 'pending' && (t.to === agent_id || t.to === null)
  );
  return { ok: true, tasks: myTasks };
}

export async function markTaskDone({ task_id, agent_id, result = {} }) {
  const tasks = loadTasks();
  const task = tasks.tasks.find(t => t.id === task_id);
  if (task) {
    task.status = 'done';
    task.completed_at = new Date().toISOString();
    task.completed_by = agent_id;
    task.result = result;
    saveTasks(tasks);
    return { ok: true };
  }
  return { ok: false, error: 'task not found' };
}

export async function listAgents() {
  const agents = loadAgents();
  return { ok: true, agents: agents.agents };
}

export async function status() {
  const agents = loadAgents();
  const tasks = loadTasks();
  const online = Object.values(agents.agents).filter(a => 
    Date.now() - new Date(a.last_heartbeat).getTime() < 120000
  ).length;
  return {
    ok: true,
    total_agents: Object.keys(agents.agents).length,
    online_agents: online,
    pending_tasks: tasks.tasks.filter(t => t.status === 'pending').length,
    total_tasks: tasks.tasks.length
  };
}

export default {
  registerAgent,
  heartbeat,
  sendTask,
  getMyTasks,
  markTaskDone,
  listAgents,
  status
};
