// =============================================
// InterClaw Integration Snippet for claw_trading_002
// Add this to the TOP of your main program file
// (index.js / main.js / start.js) AFTER imports
// =============================================

// ES Module syntax:
import { startInterClawLoop } from './skills/interclaw_client.js';

// CommonJS syntax (if your main file uses require):
// const { startInterClawLoop } = require('./skills/interclaw_client.js');

await startInterClawLoop({
  agent_id: 'claw_trading_002',
  skills: ['trading', 'mnq_analysis'],
  metadata: {
    hostname: 'claw_trading_002',
    version: '1.0',
    deployed_at: new Date().toISOString()
  },
  onTask: async (task) => {
    console.log('[claw_trading_002] Task:', task.task_type, task.payload);
    // TODO: 之後加 logic 處理唔同 task_type
  }
});

// =============================================
// Your existing main program code follows below
// =============================================
