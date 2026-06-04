#!/usr/bin/env node
// ict_scanner_v11_wrapper.cjs
// Node.js wrapper that calls Python ict_scanner_v11.py
// Captures both stdout AND stderr (Python logging goes to stderr)

const { execSync } = require('child_process');
const path = require('path');

const PYTHON_SCRIPT = '/home/node/.openclaw/workspace/ict_scanner_v11.py';
const PYTHON_BIN = process.env.PYTHON_BIN || 'python3';

try {
    // Capture both stdout and stderr
    const result = execSync(`${PYTHON_BIN} -u ${PYTHON_SCRIPT}`, {
        timeout: 60000,
        encoding: 'utf8',
        maxBuffer: 10 * 1024 * 1024,
        stdio: ['ignore', 'pipe', 'pipe']
    });
    // execSync with stdio:'pipe' returns stdout only
    // Use spawnSync for full control
    const { spawnSync } = require('child_process');
    const proc = spawnSync(PYTHON_BIN, ['-u', PYTHON_SCRIPT], {
        timeout: 60000,
        encoding: 'utf8',
        maxBuffer: 10 * 1024 * 1024
    });
    // Merge stdout and stderr
    const output = (proc.stdout || '') + (proc.stderr || '');
    process.stdout.write(output);
    if (proc.status !== 0) {
        process.exit(proc.status || 1);
    }
    process.exit(0);
} catch (e) {
    console.error('ICT Scanner v1.1 error:', e.message);
    if (e.stdout) console.error(e.stdout.toString());
    if (e.stderr) console.error(e.stderr.toString());
    process.exit(1);
}
