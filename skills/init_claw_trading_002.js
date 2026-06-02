import { startInterClawLoop } from './skills/interclaw_client.js';
await startInterClawLoop({
  agent_id: 'claw_trading_002',
  skills: ['trading', 'mnq_analysis'],
  metadata: { hostname: 'claw_trading_002', version: '1.0' },
  onTask: async (task) => {
    console.log('[claw_trading_002] Task:', task.task_type, task.payload);
  }
});
