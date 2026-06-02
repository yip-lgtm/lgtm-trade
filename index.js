// claw_trading_002 main entry (template)
import { startInterClawLoop } from './skills/interclaw_client.js';

async function main() {
  console.log('[claw_trading_002] starting...');

  await startInterClawLoop({
    agent_id: 'claw_trading_002',
    skills: ['trading', 'mnq_analysis'],
    metadata: {
      hostname: 'claw_trading_002',
      version: '1.0',
      deployed_at: new Date().toISOString()
    },
    onTask: async (task) => {
      console.log('[claw_trading_002] Task:', task.task_type);
      switch (task.task_type) {
        case 'analyze_mnq':
          console.log(' → MNQ analysis');
          break;
        case 'check_position':
          console.log(' → checking position');
          break;
        default:
          console.log(' → unknown task');
      }
    }
  });

  console.log('[claw_trading_002] ready.');
  setInterval(() => {}, 1 << 30);
}
main().catch(e => { console.error('FATAL:', e); process.exit(1); });
