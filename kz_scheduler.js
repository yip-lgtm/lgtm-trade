#!/usr/bin/env node
/**
 * KZ Scheduler v7b - Summer Time (DST) - Corrected KZ Hours
 * 
 * Summer KZ Times (currently in effect):
 *   London KZ: 14:00 - 17:00 HKT (06:00 - 09:00 UTC)
 *   NY KZ:     20:30 - 23:00 HKT (12:30 - 15:00 UTC)
 * 
 * LSTM: runs at KZ START
 *   London: 14:00 HKT (06:00 UTC)
 *   NY:     20:30 HKT (12:30 UTC)
 * 
 * Journal: runs at KZ CLOSE
 *   London: 17:05 HKT (09:05 UTC)
 *   NY:     23:05 HKT (15:05 UTC)
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
        execSync('/usr/local/bin/node /tmp/dl_node.js', { timeout: 120000 });
        log('Download complete');
    } catch(e) { log('Download failed: ' + e.message); throw e; }
}

// ====== RUN ICT SCANNER ======
function runICT() {
    try {
        return execSync('/usr/local/bin/node ' + SCANNER_FILE, { timeout: 30000, encoding: 'utf8' });
    } catch(e) { throw e; }
}

// ====== RUN LSTM ======
function runLSTM() {
    try {
        log('Running LSTM v4...');
        const out = execSync('/usr/local/bin/node ' + LSTM_FILE, { timeout: 600000, encoding: 'utf8' });
        log('LSTM complete');
        return out;
    } catch(e) {
        log('LSTM error: ' + e.message);
        return 'LSTM error: ' + e.message;
    }
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
    const hktMs = Date.now() + 8 * 3600000;
    const hkt = new Date(hktMs);
    return { h: hkt.getUTCHours(), m: hkt.getUTCMinutes(), day: hkt.toISOString().split('T')[0] };
}

function loggableTime() {
    return new Date(Date.now() + 8*3600000).toLocaleString('zh-HK', {timeZone:'Asia/Hong_Kong'});
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
    // Journal London: 17:05 HKT = 09:05 UTC (recover within 30 min)
    if (h === 9 && m >= 5 && m <= 35 && state.journalLondon !== day) {
        log('Recovering Journal London (missed)');
        await runJournalSession('London');
    }
    // Journal NY: 23:05 HKT = 15:05 UTC (recover within 30 min)
    if (h === 15 && m >= 5 && m <= 35 && state.journalNY !== day) {
        log('Recovering Journal NY (missed)');
        await runJournalSession('NY');
    }
}

// ====== MAIN ======
async function main() {
    log('KZ Scheduler v7b - Summer KZ times updated');
    console.log('v7b: LSTM 14:00/20:30 HKT | Journal 17:05/23:05 HKT');
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
            await runLSTMSession('London');
            continue;
        }
        // NY: 20:30 HKT = 12:30 UTC
        if (h === 12 && m === 30 && state.lstmNY !== day) {
            await runLSTMSession('NY');
            continue;
        }

        // === Journal at KZ CLOSE ===
        // London: 17:05 HKT = 09:05 UTC
        if (h === 9 && m >= 5 && m <= 35 && state.journalLondon !== day) {
            await runJournalSession('London');
            continue;
        }
        // NY: 23:05 HKT = 15:05 UTC
        if (h === 15 && m >= 5 && m <= 35 && state.journalNY !== day) {
            await runJournalSession('NY');
            continue;
        }
    }
}

main().catch(e => { log('FATAL: ' + e.message); process.exit(1); });
