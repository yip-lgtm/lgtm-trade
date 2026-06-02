#!/usr/bin/env node
/**
 * Journal Trigger Script - called by kz_shell.sh
 * Downloads data, runs ICT, writes journal, sends Telegram
 */
'use strict';
const { execSync } = require('child_process');
const https = require('https');
const fs = require('fs');

const BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY';
const CHAT_ID = '8475453959';
const SCANNER_FILE = '/home/node/.openclaw/workspace/ict_scanner_v5.js';
const JOURNAL_FILE = '/home/node/.openclaw/workspace/live_trading_journal.csv';
const LOG_FILE = '/tmp/kz_journal.log';

function log(msg) {
    const ts = new Date().toISOString();
    console.log(ts + ' ' + msg);
    fs.appendFileSync(LOG_FILE, ts + ' ' + msg + '\n');
}

function sendTelegram(text) {
    return new Promise((resolve, reject) => {
        const url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage?chat_id=' + CHAT_ID + '&text=' + encodeURIComponent(text) + '&parse_mode=HTML';
        https.get(url, (res) => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch(e) { reject(new Error(d)); } });
        }).on('error', reject);
    });
}

function hktTime() {
    return new Date(Date.now() + 8*3600000).toLocaleString('zh-HK', {timeZone:'Asia/Hong_Kong'});
}

function writeJournal(scanOutput, kz) {
    const ts = new Date().toISOString();
    const lines = scanOutput.split('\n');
    const summaryLines = lines.filter(l => /^\s+[A-Z0-9.]+:\s+(Long|Short|None)/.test(l));

    let rows = [];
    summaryLines.forEach(line => {
        const m = line.match(/^\s+([A-Z0-9.]+):\s+(Long|Short|None)/);
        if (!m || m[2] === 'None') return;
        const sym = m[1], dir = m[2];
        let closePrice = '';
        const priceM = line.match(/@\s+([\d.]+)/);
        if (priceM) closePrice = priceM[1];
        rows.push(ts.split('T')[0] + ',' + ts.split('T')[1].substring(0,8) + ',' + sym + ',' + dir + ',,,,,' + ',2,' + kz + ',0');
    });

    if (rows.length > 0) {
        const hdr = 'date,time,symbol,direction,entry_price,close_price,sl,tp1,tp2,contracts,killzone,signal_est_pnl';
        if (!fs.existsSync(JOURNAL_FILE)) fs.writeFileSync(JOURNAL_FILE, hdr + '\n');
        fs.appendFileSync(JOURNAL_FILE, rows.join('\n') + '\n');
        log('Journal: ' + rows.length + ' signals written');
    }
}

async function main() {
    const kz = process.argv[2] || 'Unknown';
    log('Journal ' + kz + ' START');
    
    try {
        // Download data
        log('Downloading...');
        execSync('/usr/local/bin/node /tmp/dl_node.js', { timeout: 120000 });
        
        // Run ICT
        log('Running ICT...');
        const ictOut = execSync('/usr/local/bin/node ' + SCANNER_FILE, { timeout: 30000, encoding: 'utf8' });
        
        // Write journal
        writeJournal(ictOut, kz);
        
        // Parse signals
        const ictLines = ictOut.split('\n').filter(l => /^\s+[A-Z0-9.]+:\s+(Long|Short|None)/.test(l));
        
        // Build message
        let msg = '📝 <b>' + kz + ' KZ 完結 - 紀錄</b>\n';
        msg += '📅 ' + hktTime() + '\n';
        msg += '<pre>' + ictLines.slice(0,9).join('\n') + '</pre>';
        
        await sendTelegram(msg);
        log('Journal ' + kz + ' DONE');
        
    } catch(e) {
        log('Journal ' + kz + ' ERROR: ' + e.message);
        try { await sendTelegram('❌ Journal ' + kz + ' 失敗: ' + e.message); } catch(e2) {}
    }
}

main().catch(e => { log('FATAL: ' + e.message); process.exit(1); });
