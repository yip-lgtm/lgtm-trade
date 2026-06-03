#!/usr/bin/env node
/**
 * KZ Scheduler v7d - Summer Time (DST) - Fixed HKT Bug
 * 
 * Hours are in UTC (getHKTHM returns UTC hours directly)
 * HKT = UTC + 8
 * 
 * Summer KZ Times:
 *   London KZ: 14:00 - 17:00 HKT = 06:00 - 09:00 UTC
 *   NY KZ:     20:30 - 23:00 HKT = 12:30 - 15:00 UTC
 * 
 * LSTM: runs at KZ START (UTC)
 *   London: 06:00 UTC  |  NY: 12:30 UTC
 * 
 * Journal: runs at KZ CLOSE+5min (UTC)
 *   London: 09:05 UTC  |  NY: 15:05 UTC
 */
'use strict';
const { execSync } = require('child_process');
const https = require('https');
const fs = require('fs');

// ====== CONFIG ======
const BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY';
const CHAT_ID = '8475453959';
const SCANNER_FILE = '/home/node/.openclaw/workspace/ict_scanner_v5.js';
const LSTM_FILE = '/home/node/.openclaw/workspace/lstm_trading_v4_node.js';
const LOG_FILE = '/tmp/kz_scheduler.log';
const JOURNAL_FILE = '/home/node/.openclaw/workspace/live_trading_journal.csv';

// ====== LOGGING ======
function log(msg) {
    const ts = new Date().toISOString();
    console.log(ts + ' ' + msg);
    fs.appendFileSync(LOG_FILE, ts + ' ' + msg + '\n');
}

// ====== TELEGRAM ======
function sendTelegram(text) {
    return new Promise((resolve, reject) => {
        const url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage?chat_id=' + CHAT_ID + '&text=' + encodeURIComponent(text) + '&parse_mode=HTML';
        const req = https.get(url, (res) => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch(e) { reject(new Error(d)); } });
        });
        req.on('error', reject);
        req.setTimeout(10000, () => { req.destroy(); reject(new Error('Telegram timeout')); });
    });
}

// ====== DOWNLOAD ======
function downloadData() {
    log('Downloading data...');
    try {
        // First try workspace location, then /tmp
        const workspaceScript = '/home/node/.openclaw/workspace/dl_node.cjs';
        const tmpScript = '/tmp/dl_node.js';
        const script = fs.existsSync(workspaceScript) ? workspaceScript : tmpScript;
        execSync(`/usr/local/bin/node ${script}`, { timeout: 120000 });
        log('Download complete');
    } catch(e) {
        log('Download failed (continuing with existing data): ' + e.message);
        // Don't throw - continue with existing CSV data
    }
}

// ====== RUN ICT SCANNER ======
function runICT() {
    try {
        return execSync('/usr/local/bin/node ' + SCANNER_FILE, { timeout: 30000, encoding: 'utf8' });
    } catch(e) { throw e; }
}

// ====== RUN LSTM ======
function runLSTM() {
    log('LSTM skipped - using ICT only');
    return 'LSTM SKIPPED - ICT Mode';
}

// ====== JOURNAL ======
function writeJournal(scanOutput, kz) {
    const ts = new Date().toISOString();
    const lines = scanOutput.split('\n');
    const entryLines = lines.filter(l => l.includes('Entry:') && l.includes('合約'));
    const summaryLines = lines.filter(l => /^\s+[A-Z0-9.]+:\s+(Long|Short|None)/.test(l));

    let rows = [];
    summaryLines.forEach(line => {
        const m = line.match(/^\s+([A-Z0-9.]+):\s+(Long|Short|None)/);
        if (!m || m[2] === 'None') return;
        const sym = m[1], dir = m[2];
        let closePrice = '';
        const priceM = line.match(/@\s+([\d.]+)/);
        if (priceM) closePrice = priceM[1];
        const em = entryLines.find(l => l.includes(sym + ' '));
        let entry = '', sl = '', tp1 = '', tp2 = '', contracts = '2', est = '0';
        if (em) {
            const e1 = em.match(/Entry:([\d.]+)/);
            const s1 = em.match(/SL:([\d.]+)/);
            const t1 = em.match(/TP1:([\d.]+)/);
            const t2 = em.match(/TP2:([\d.]+)/);
            const cm = em.match(/(\d+)合約/);
            const pm = em.match(/\$\/? ?([\d,]+)/);
            entry = e1 ? e1[1] : '';
            sl = s1 ? s1[1] : '';
            tp1 = t1 ? t1[1] : '';
            tp2 = t2 ? t2[1] : '';
            contracts = cm ? cm[1] : '2';
            est = pm ? pm[1].replace(',', '') : '0';
        }
        rows.push(ts.split('T')[0] + ',' + ts.split('T')[1].substring(0,8) + ',' + sym + ',' + dir + ',' + entry + ',' + closePrice + ',' + sl + ',' + tp1 + ',' + tp2 + ',' + contracts + ',' + kz + ',' + est);
    });

    if (rows.length > 0) {
        const hdr = 'date,time,symbol,direction,entry_price,close_price,sl,tp1,tp2,contracts,killzone,signal_est_pnl';
        if (!fs.existsSync(JOURNAL_FILE)) fs.writeFileSync(JOURNAL_FILE, hdr + '\n');
        fs.appendFileSync(JOURNAL_FILE, rows.join('\n') + '\n');
        log('Journal: ' + rows.length + ' signals written');
    }
}

// ====== STATE ======
const stateFile = '/tmp/kz_state.json';
let state = {
    lstmLondon: null, lstmNY: null,
    journalLondon: null, journalNY: null,
    activeTask: null,
    lastRunTime: null
};

function loadState() {
    try {
        if (fs.existsSync(stateFile)) {
            const loaded = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
            state = { ...state, ...loaded };
        }
    } catch(e) { log('State load error: ' + e.message); }
}

function saveState() {
    try { fs.writeFileSync(stateFile, JSON.stringify(state)); } catch(e) { log('State save error: ' + e.message); }
}

// ====== HELPERS ======
function getHKTHM() {
    return { h: new Date().getUTCHours(), m: new Date().getUTCMinutes(), day: new Date().toISOString().split('T')[0] };
}

function loggableTime() {
    // Returns HKT time as a string using Intl API (correct)
    return new Intl.DateTimeFormat('zh-HK', {timeZone:'Asia/Hong_Kong', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}).format(new Date());
}

// ====== LSTM SESSION ======
async function runLSTMSession(kz) {
    const key = kz === 'London' ? 'lstmLondon' : 'lstmNY';
    const { day } = getHKTHM();

    log('LSTM ' + kz + ' START');
    state.activeTask = 'LSTM_' + kz;
    saveState();

    try {
        await downloadData();
        const lstmOut = runLSTM();
        const ictOut = runICT();
        const lines = ictOut.split('\n').filter(l => /^\s+[A-Z0-9.]+:\s+(Long|Short|None)/.test(l));
        const lstmLines = lstmOut.split('\n').filter(l => l.includes('Signal') || l.includes('Long') || l.includes('Short'));

        let msg = '🧠 <b>' + kz + ' KZ 開盤 - LSTM 信號</b>\n';
        msg += '📅 ' + loggableTime() + '\n\n';
        if (lstmLines.length > 0) msg += '<pre>' + lstmLines.slice(0,12).join('\n') + '</pre>';
        msg += '\n<b>ICT:</b>\n<pre>' + lines.slice(0,9).join('\n') + '</pre>';

        await sendTelegram(msg);
        state[key] = day;
        state.activeTask = null;
        state.lastRunTime = new Date().toISOString();
        saveState();
        log('LSTM ' + kz + ' DONE');
    } catch(e) {
        log('LSTM ' + kz + ' ERROR: ' + e.message);
        state.activeTask = null;
        saveState();
        try { await sendTelegram('❌ LSTM ' + kz + ' 失敗: ' + e.message); } catch(e2) {}
    }
}

// ====== JOURNAL SESSION ======
async function runJournalSession(kz) {
    const key = kz === 'London' ? 'journalLondon' : 'journalNY';
    const { day } = getHKTHM();

    log('Journal ' + kz + ' START');
    state.activeTask = 'J_' + kz;
    saveState();

    try {
        await downloadData();
        const ictOut = runICT();
        writeJournal(ictOut, kz);
        const lines = ictOut.split('\n').filter(l => /^\s+[A-Z0-9.]+:\s+(Long|Short|None)/.test(l));

        let msg = '📝 <b>' + kz + ' KZ 完結 - 紀錄</b>\n';
        msg += '📅 ' + loggableTime() + '\n';
        msg += '<pre>' + lines.slice(0,9).join('\n') + '</pre>';

        await sendTelegram(msg);
        state[key] = day;
        state.activeTask = null;
        state.lastRunTime = new Date().toISOString();
        saveState();
        log('Journal ' + kz + ' DONE');
    } catch(e) {
        log('Journal ' + kz + ' ERROR: ' + e.message);
        state.activeTask = null;
        saveState();
        try { await sendTelegram('❌ Journal ' + kz + ' 失敗: ' + e.message); } catch(e2) {}
    }
}

// ====== CRASH RECOVERY ======
async function recoverInterruptedTasks() {
    log('Crash recovery check...');
    const { h, m, day } = getHKTHM();
    const active = state.activeTask;

    if (active) {
        log('Found interrupted task: ' + active + ' - clearing');
        state.activeTask = null;
        saveState();
    }

    // LSTM London: 14:00 HKT = 06:00 UTC (recover within 25 min)
    if (h === 6 && m <= 25 && state.lstmLondon !== day) {
        log('Recovering LSTM London (missed)');
        await runLSTMSession('London');
    }
    // LSTM NY: 20:30 HKT = 12:30 UTC (recover within 25 min)
    if (h === 12 && m >= 30 && m <= 55 && state.lstmNY !== day) {
        log('Recovering LSTM NY (missed)');
        await runLSTMSession('NY');
    }
    // Journal London: 17:05 HKT = 09:05 UTC
    if (h === 9 && m >= 5 && m <= 35 && state.journalLondon !== day) {
        log('Recovering Journal London (missed)');
        await runJournalSession('London');
    }
    // Journal NY: 23:05 HKT = 15:05 UTC
    if (h === 15 && m >= 5 && m <= 35 && state.journalNY !== day) {
        log('Recovering Journal NY (missed)');
        await runJournalSession('NY');
    }
}

// ====== MAIN ======
async function main() {
    log('KZ Scheduler v7d - Summer KZ times (UTC hours)');
    console.log('v7d: LSTM 06:00/12:30 UTC | Journal 09:05/15:05 UTC');
    loadState();
    await recoverInterruptedTasks();
    while (true) {
        await new Promise(r => setTimeout(r, 30000));

        if (state.activeTask) {
            log('Task ' + state.activeTask + ' running, skip cycle');
            continue;
        }

        const { h, m, day } = getHKTHM();

        // === LSTM at KZ START ===
        // London: 14:00 HKT = 06:00 UTC
        if (h === 6 && m === 0 && state.lstmLondon !== day) {
            log('Trigger LSTM London');
            await runLSTMSession('London');
            continue;
        }
        // NY: 20:30 HKT = 12:30 UTC
        if (h === 12 && m === 30 && state.lstmNY !== day) {
            log('Trigger LSTM NY');
            await runLSTMSession('NY');
            continue;
        }

        // === Journal at KZ CLOSE ===
        // London: 17:05 HKT = 09:05 UTC, NY: 23:05 HKT = 15:05 UTC
        if (h === 9 && m >= 5 && m <= 35 && state.journalLondon !== day) {
            log('Trigger Journal London');
            await runJournalSession('London');
            continue;
        }
        if (h === 15 && m >= 5 && m <= 35 && state.journalNY !== day) {
            log('Trigger Journal NY');
            await runJournalSession('NY');
            continue;
        }
    }
}

main().catch(e => { log('FATAL: ' + e.message); process.exit(1); });
