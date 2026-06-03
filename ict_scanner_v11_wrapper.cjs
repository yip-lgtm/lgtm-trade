#!/usr/bin/env node
// ict_scanner_v11_wrapper.cjs
// Node.js wrapper that calls Python ict_scanner_v11.py
// Maintains compatibility with kz_scheduler.js

const { execSync } = require('child_process');
const path = require('path');

const PYTHON_SCRIPT = '/home/node/.openclaw/workspace/ict_scanner_v11.py';
const PYTHON_BIN = process.env.PYTHON_BIN || 'python3';

try {
    const output = execSync(`${PYTHON_BIN} ${PYTHON_SCRIPT}`, {
        timeout: 60000,
        encoding: 'utf8',
        maxBuffer: 10 * 1024 * 1024
    });
    process.stdout.write(output);
    process.exit(0);
} catch (e) {
    console.error('ICT Scanner v1.1 error:', e.message);
    if (e.stdout) console.error(e.stdout.toString());
    if (e.stderr) console.error(e.stderr.toString());
    process.exit(1);
}
