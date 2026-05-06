#!/usr/bin/env node
/**
 * KZ Scheduler - runs ICT scanner at London/NY Kill Zone CLOSE
 * London KZ: 15:00-16:00 HKT → run at 16:05 HKT
 * NY KZ: 21:30-22:30 HKT → run at 22:35 HKT
 * Sends results to Telegram + records profit/win rate to journal
 */
'use strict';

const { execSync, spawn } = require('child_process');
const https = require('https');
const fs = require('fs');

// ====== CONFIG ======
const BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY'; // Telegram bot token
const CHAT_ID = '8475453959';
const SCANNER_FILE = '/home/node/.openclaw/workspace/ict_scanner_v5.js';
const LOG_FILE = '/tmp/kz_scheduler.log';
const JOURNAL_FILE = '/home/node/.openclaw/workspace/live_trading_journal.csv';

// ====== LOGGING ======
function log(msg) {
    const ts = new Date().toISOString();
    console.log(`${ts} ${msg}`);
    fs.appendFileSync(LOG_FILE, `${ts} ${msg}\n`);
}

// ====== TELEGRAM ======
function sendTelegram(text) {
    return new Promise((resolve, reject) => {
        const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage?chat_id=${CHAT_ID}&text=${encodeURIComponent(text)}&parse_mode=HTML`;
        https.get(url, (res) => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => {
                try { resolve(JSON.parse(d)); }
                catch(e) { reject(new Error(d)); }
            });
        }).on('error', reject);
    });
}

function sendFileTelegram(filePath, caption) {
    return new Promise((resolve, reject) => {
        const fileData = fs.readFileSync(filePath);
        const formData = [
            `--boundary\nContent-Disposition: form-data; name="chat_id"\n\n${CHAT_ID}`,
            `--boundary\nContent-Disposition: form-data; name="caption"\n\n${caption}`,
            `--boundary\nContent-Disposition: form-data; name="document"; filename="${filePath.split('/').pop()}"\nContent-Type: application/octet-stream\n\n${fileData.toString()}`,
            `--boundary--`
        ].join('\n');

        const options = {
            hostname: 'api.telegram.org',
            path: `/bot${BOT_TOKEN}/sendDocument`,
            method: 'POST',
            headers: {
                'Content-Type': 'multipart/form-data; boundary=boundary',
                'Content-Length': Buffer.byteLength(formData)
            }
        };

        const req = https.request(options, (res) => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => {
                try { resolve(JSON.parse(d)); }
                catch(e) { reject(new Error(d)); }
            });
        });
        req.on('error', reject);
        req.write(formData);
        req.end();
    });
}

// ====== DOWNLOAD DATA ======
function downloadData() {
    return new Promise((resolve, reject) => {
        log('Downloading latest data...');
        try {
            const result = execSync('/usr/local/bin/node /tmp/dl_node.js', { timeout: 120000 });
            log('Download complete');
            resolve();
        } catch(e) {
            log('Download failed: ' + e.message);
            reject(e);
        }
    });
}

// ====== RUN SCANNER ======
function runScanner() {
    return new Promise((resolve, reject) => {
        log('Running ICT scanner...');
        try {
            const output = execSync(`node ${SCANNER_FILE}`, { timeout: 30000, encoding: 'utf8' });
            resolve(output);
        } catch(e) {
            reject(e);
        }
    });
}

// ====== CHECK IF IN KZ ======
function isNowKZ() {
    const now = new Date();
    const hkt = new Date(now.getTime() + 8 * 60 * 60 * 1000);
    const h = hkt.getUTCHours();
    const m = hkt.getUTCMinutes();

    // London KZ: 15:00-16:00 HKT (03:00-04:00 EST)
    if (h === 15) return 'London';
    // NY KZ: 21:30-22:30 HKT (09:30-10:30 EST)
    if (h === 21 && m >= 30) return 'NY';
    return null;
}

function shouldRunNow(lastRunTime) {
    const now = new Date();
    const hkt = new Date(now.getTime() + 8 * 60 * 60 * 1000);
    const h = hkt.getUTCHours();
    const m = hkt.getUTCMinutes();

    // London KZ closes at 16:00 → run at 16:05
    if (h === 16 && m === 5) return 'London';
    // NY KZ closes at 22:30 → run at 22:35
    if (h === 22 && m === 35) return 'NY';

    // Check if we missed it (within first 5 min of KZ)
    if (lastRunTime) {
        const last = new Date(lastRunTime);
        const diffMs = now - last;
        const diffMin = diffMs / 60000;

        if (h === 16 && diffMin > 1 && diffMin < 10) return 'London_missed';
        if (h === 22 && diffMin > 1 && diffMin < 10) return 'NY_missed';
    }
    return null;
}

// ====== JOURNAL ======
function writeToJournal(scanOutput, kz) {
    const ts = new Date().toISOString();
    const lines = scanOutput.split('\n').filter(l => l.includes('MES.F') || l.includes('MNQ.F') || l.includes('M2K.F') || l.includes('MYM.F') || l.includes('M6E.F') || l.includes('M6A.F') || l.includes('MCL.F') || l.includes('MBT.F') || l.includes('MET.F'));
    const kzLines = scanOutput.split('\n').filter(l => l.includes('Entry:'));
    
    let journalLines = [];
    lines.forEach(line => {
        // Parse signals like: MES.F: Long  @ 7163.00 | RSI:53 KZ:NY Est:$0
        const match = line.match(/^\s*([A-Z0-9.]+):\s+(Long|Short|None)/);
        if (!match) return;
        const sym = match[1];
        const dir = match[2];
        if (dir === 'None') return;
        
        // Find KZ entry data
        const kzMatch = kzLines.find(l => l.includes(sym + ' ') || l.includes(sym + '\n'));
        let entry = '', sl = '', tp1 = '', tp2 = '', contracts = '2';
        if (kzMatch) {
            const eMatch = kzMatch.match(/Entry:([\d.]+)/);
            const sMatch = kzMatch.match(/SL:([\d.]+)/);
            const t1Match = kzMatch.match(/TP1:([\d.]+)/);
            const t2Match = kzMatch.match(/TP2:([\d.]+)/);
            const cMatch = kzMatch.match(/(\d+)合約/);
            entry = eMatch ? eMatch[1] : '';
            sl = sMatch ? sMatch[1] : '';
            tp1 = t1Match ? t1Match[1] : '';
            tp2 = t2Match ? t2Match[1] : '';
            contracts = cMatch ? cMatch[1] : '2';
        }
        journalLines.push(`${ts.split('T')[0]},${ts.split('T')[1].substring(0,8)},${sym},${dir},${entry},${sl},${tp1},${tp2},${contracts},${kz},pending`);
    });
    
    if (journalLines.length > 0) {
        const header = 'date,time,symbol,direction,entry,sl,tp1,tp2,contracts,killzone,status';
        if (!fs.existsSync(JOURNAL_FILE)) {
            fs.writeFileSync(JOURNAL_FILE, header + '\n');
        }
        fs.appendFileSync(JOURNAL_FILE, journalLines.join('\n') + '\n');
        log(`Journal: ${journalLines.length} trades written`);
    }
}

// ====== MAIN LOOP ======
let lastRunTime = null;
let lastRunKZ = null;
const stateFile = '/tmp/kz_last_run.json';

function loadState() {
    try {
        if (fs.existsSync(stateFile)) {
            const s = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
            lastRunTime = s.lastRunTime;
            lastRunKZ = s.lastRunKZ;
        }
    } catch(e) {}
}

function saveState() {
    try {
        fs.writeFileSync(stateFile, JSON.stringify({ lastRunTime, lastRunKZ }));
    } catch(e) {}
}

async function main() {
    log('🚀 KZ Scheduler started');
    console.log('🚀 KZ Scheduler started - watching for London (16:05 HKT) and NY (22:35 HKT) - runs at KZ CLOSE');

    loadState();

    // Check if we just missed a KZ at startup
    const missed = shouldRunNow(lastRunTime);
    if (missed && missed.includes('_missed')) {
        const kz = missed.replace('_missed', '');
        log(`⚠️ Startup detected missed ${kz} KZ, running now...`);
        console.log(`⚠️ Startup: caught missed ${kz} KZ, running now...`);
        try {
            await downloadData();
            const result = await runScanner();
            writeToJournal(result, kz);
            await sendTelegram(`🔔 <b>${kz} KZ 補運行</b>\n${result.substring(0, 2000)}`);
            lastRunTime = new Date().toISOString();
            lastRunKZ = kz;
            saveState();
        } catch(e) {
            log('Error: ' + e.message);
            await sendTelegram(`❌ ${kz} KZ 補運行失敗: ${e.message}`);
        }
    }

    let checkCount = 0;
    while (true) {
        await new Promise(r => setTimeout(r, 60000)); // check every minute
        checkCount++;

        if (checkCount % 5 === 0) {
            log(`Still watching... (check #${checkCount})`);
        }

        const action = shouldRunNow(lastRunTime);
        if (!action) continue;

        const kz = action.replace('_missed', '');
        log(`🎯 ${kz} KZ detected at ${new Date().toISOString()}!`);
        console.log(`🎯 ${kz} KZ starting! Running scanner...`);

        try {
            // Download fresh data first
            await downloadData();

            // Run scanner
            const result = await runScanner();
            writeToJournal(result, kz);

            // Extract KZ signals from output
            const kzLines = result.split('\n').filter(l => l.includes('🔥') || l.includes('KZ'));
const summary = result.split('\n').filter(l => l.includes('MES.F') || l.includes('MNQ.F') || l.includes('M2K.F') || l.includes('MYM.F') || l.includes('M6E.F') || l.includes('M6A.F') || l.includes('MCL.F') || l.includes('MBT.F') || l.includes('MET.F'));

            let msg = `🔔 <b>${kz} Kill Zone 掃描結果</b>\n`;
            msg += `⏰ ${new Date().toLocaleString('zh-HK', {timeZone:'Asia/Hong_Kong'})}\n\n`;
            msg += `<pre>${summary.slice(2, 9).join('\n')}</pre>\n`;
            if (kzLines.length > 0) {
                msg += `\n${kzLines.join('\n')}`;
            }

            await sendTelegram(msg);
            lastRunTime = new Date().toISOString();
            lastRunKZ = kz;
            saveState();
            log(`✅ ${kz} KZ scan sent to Telegram`);
            console.log(`✅ ${kz} scan complete, notification sent`);
        } catch(e) {
            log(`❌ Error: ${e.message}`);
            console.log(`❌ Error: ${e.message}`);
            await sendTelegram(`❌ ${kz} KZ 運行失敗: ${e.message}`);
        }
    }
}

main().catch(e => {
    log('FATAL: ' + e.message);
    console.error('FATAL:', e);
    process.exit(1);
});
