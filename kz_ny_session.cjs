#!/usr/bin/env node
/**
 * One-shot NY Kill Zone LSTM Session
 * Mirrors runLSTMSession('NY') from kz_scheduler.cjs but exits after completion.
 * Cron-driven entry point for the NY KZ (20:30 HKT = 12:30 UTC).
 */
'use strict';
const { execSync } = require('child_process');
const https = require('https');
const fs = require('fs');

const BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY';
const CHAT_ID = '8475453959';
const LSTM_FILE = '/home/node/.openclaw/workspace/lstm_trading_v4_node.js';
const ICT_FILE = '/home/node/.openclaw/workspace/ict_scanner_v11_wrapper.cjs';
const DL_FILE = '/home/node/.openclaw/workspace/dl_node.cjs';
const LOG_FILE = '/tmp/kz_scheduler.log';
const STATE_FILE = '/tmp/kz_state.json';
const KZ = 'NY';

function log(msg) {
    const ts = new Date().toISOString();
    console.log(ts + ' ' + msg);
    try { fs.appendFileSync(LOG_FILE, ts + ' [NY] ' + msg + '\n'); } catch(e) {}
}

function sendTelegram(text) {
    return new Promise((resolve, reject) => {
        const url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage?chat_id=' + CHAT_ID + '&text=' + encodeURIComponent(text) + '&parse_mode=HTML';
        const req = https.get(url, (res) => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch(e) { reject(new Error(d)); } });
        });
        req.on('error', reject);
        req.setTimeout(15000, () => { req.destroy(); reject(new Error('Telegram timeout')); });
    });
}

function downloadData() {
    log('Downloading data...');
    try {
        const out = execSync('/usr/local/bin/node ' + DL_FILE, { timeout: 180000, encoding: 'utf8' });
        log('Download: ' + out.split('\n').filter(l => l.includes('[SAVED]') || l.includes('Done')).slice(-3).join(' | '));
    } catch(e) {
        log('Download failed (continuing with existing data): ' + e.message);
    }
}

function runICT() {
    log('Running ICT scanner v1.1...');
    const out = execSync('/usr/local/bin/node ' + ICT_FILE, { timeout: 90000, encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 });
    log('ICT output: ' + out.split('\n').length + ' lines');
    return out;
}

function runLSTM() {
    log('LSTM skipped (ICT-only mode per kz_scheduler v7d).');
    return 'LSTM SKIPPED - ICT Mode';
}

function loggableTime() {
    return new Intl.DateTimeFormat('zh-HK', {timeZone:'Asia/Hong_Kong', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}).format(new Date());
}

async function main() {
    const day = new Date().toISOString().split('T')[0];
    log('=== NY KZ LSTM session START ===');
    log('HKT time: ' + loggableTime());

    let ictOut = '';
    let lstmOut = '';
    let telegramSent = false;
    let err = null;

    try {
        downloadData();
        lstmOut = runLSTM();
        ictOut = runICT();
    } catch(e) {
        err = e;
        log('Session error: ' + e.message);
    }

    // Build Telegram message
    const ictLines = ictOut ? ictOut.split('\n').filter(l => /^\s*[A-Z0-9.]+:\s+(Long|Short|None)/.test(l)) : [];
    const lstmLines = lstmOut ? lstmOut.split('\n').filter(l => l.includes('Signal') || l.includes('Long') || l.includes('Short')) : [];

    let msg = '🧠 <b>' + KZ + ' KZ 開盤 - 信號</b>\n';
    msg += '📅 ' + loggableTime() + ' HKT\n';
    if (lstmLines.length > 0) {
        msg += '\n<b>LSTM:</b>\n<pre>' + lstmLines.slice(0,12).join('\n') + '</pre>\n';
    } else {
        msg += '\n<b>LSTM:</b> 跳過 (ICT 模式)\n';
    }
    msg += '\n<b>ICT:</b>\n<pre>' + ictLines.slice(0,9).join('\n') + '</pre>';

    if (err) {
        msg = '❌ <b>' + KZ + ' KZ LSTM 失敗</b>\n' + msg + '\n\n錯誤: ' + err.message;
    }

    try {
        await sendTelegram(msg);
        telegramSent = true;
        log('Telegram sent');
    } catch(e) {
        log('Telegram send failed: ' + e.message);
    }

    // Update state
    try {
        let state = {};
        if (fs.existsSync(STATE_FILE)) {
            state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
        }
        state.lstmNY = day;
        state.lastRunTime = new Date().toISOString();
        state.activeTask = null;
        fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
        log('State updated: lstmNY=' + day);
    } catch(e) {
        log('State save error: ' + e.message);
    }

    log('=== NY KZ LSTM session END (telegram=' + telegramSent + ') ===');

    // Print summary for cron log
    console.log('\n===== NY KZ SESSION SUMMARY =====');
    console.log('Time:        ' + loggableTime() + ' HKT');
    console.log('Telegram:    ' + (telegramSent ? 'sent' : 'FAILED'));
    console.log('ICT signals: ' + ictLines.length);
    if (ictLines.length > 0) console.log(ictLines.slice(0,9).join('\n'));
    if (err) console.log('ERROR: ' + err.message);
    console.log('=================================');
}

main().catch(e => {
    log('FATAL: ' + e.message);
    process.exit(1);
});
