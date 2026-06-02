// interclaw_coordinator_standalone.js
// Standalone HTTP server for interclaw coordination
// Listens on PORT (default 18790) and accepts agent connections
// No OpenClaw gateway auth required

import http from 'http';
import fs from 'fs';
import path from 'path';
import url from 'url';

const AGENT_DIR = '/home/node/.openclaw/data/interclaw';
const TASK_FILE = path.join(AGENT_DIR, 'tasks.json');
const AGENTS_FILE = path.join(AGENT_DIR, 'agents.json');
const PORT = parseInt(process.env.INTERCLAW_PORT || '18790');

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

const handlers = {
  registerAgent: ({ agent_id, skills = [], metadata = {} }) => {
    const agents = loadAgents();
    agents.agents[agent_id] = {
      agent_id, skills, metadata,
      registered_at: new Date().toISOString(),
      last_heartbeat: new Date().toISOString(),
      status: 'online'
    };
    saveAgents(agents);
    console.log(`[${new Date().toISOString()}] REGISTER ${agent_id} (skills: ${skills.join(',')})`);
    return { ok: true, agent_id, registered_at: agents.agents[agent_id].registered_at };
  },

  heartbeat: ({ agent_id }) => {
    const agents = loadAgents();
    if (!agents.agents[agent_id]) {
      agents.agents[agent_id] = {
        agent_id, skills: [], metadata: {},
        registered_at: new Date().toISOString(),
        last_heartbeat: new Date().toISOString(),
        status: 'online'
      };
    } else {
      agents.agents[agent_id].last_heartbeat = new Date().toISOString();
      agents.agents[agent_id].status = 'online';
    }
    saveAgents(agents);
    return { ok: true, agent_id, last_heartbeat: agents.agents[agent_id].last_heartbeat };
  },

  sendTask: ({ from_agent, to = null, task_type, payload = {} }) => {
    const tasks = loadTasks();
    const task = {
      id: `task_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`,
      from_agent, to, task_type, payload,
      created_at: new Date().toISOString(),
      status: 'pending'
    };
    tasks.tasks.push(task);
    saveTasks(tasks);
    console.log(`[${new Date().toISOString()}] TASK ${task.id} from ${from_agent}`);
    return { ok: true, task_id: task.id };
  },

  getMyTasks: ({ agent_id }) => {
    const tasks = loadTasks();
    const myTasks = tasks.tasks.filter(t => t.status === 'pending' && (t.to === agent_id || t.to === null));
    return { ok: true, tasks: myTasks };
  },

  markTaskDone: ({ task_id, agent_id, result = {} }) => {
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
  },

  listAgents: () => loadAgents(),

  status: () => {
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
};

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  const parsed = url.parse(req.url, true);
  const path_parts = parsed.pathname.split('/').filter(Boolean);

  // Health check
  if (req.method === 'GET' && (parsed.pathname === '/' || parsed.pathname === '/health')) {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true, status: 'live', port: PORT }));
    return;
  }

  // API: POST /<action> with JSON body
  if (req.method === 'POST' && path_parts.length === 1) {
    const action = path_parts[0];
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try {
        const params = body ? JSON.parse(body) : {};
        const handler = handlers[action];
        if (!handler) {
          res.writeHead(404, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ ok: false, error: `Unknown action: ${action}` }));
          return;
        }
        const result = handler(params);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(result));
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: e.message }));
      }
    });
    return;
  }

  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ ok: false, error: 'Not found' }));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`🦞 InterClaw Coordinator listening on 0.0.0.0:${PORT}`);
  console.log(`   Health: http://localhost:${PORT}/health`);
  console.log(`   API: POST http://localhost:${PORT}/<action>`);
});
