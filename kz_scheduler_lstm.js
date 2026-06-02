#!/usr/bin/env node
/**
 * LSTM Trigger Script - called by kz_shell.sh
 * Downloads data, runs LSTM + ICT, sends Telegram
 */
'use strict';
const { execSync } = require('child_process');
const https = require('https');
const fs = require('fs');

const BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY';
const CHAT_ID = '8475453959';
const SCANNER_FILE = '/home/node/.openclaw/workspace/ict_scanner_v5.js';
const LSTM_FILE = '/home/node/.openclaw/workspace/lstm_live.py';
const LOG_FILE = '/tmp/kz_lstm.log';

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

async function main() {
    const kz = process.argv[2] || 'Unknown';
    log('LSTM ' + kz + ' START');
    
    try {
        // Download data and resample to 1hr
        log('Downloading...');
        execSync('/usr/local/bin/node /tmp/dl_node.js', { timeout: 120000 });
        
        // Resample 15min to 1hr
        log('Resampling to 1hr...');
        execSync('/usr/bin/python3 /tmp/resample_1hr.py', { timeout: 60000 });
        
        // Run LSTM 1HR
        log('Running LSTM 1HR...');
        const lstmOut = execSync('/usr/bin/python3 /home/node/.openclaw/workspace/lstm_live.py', { timeout: 3600000, encoding: 'utf8' });
        
        // Run ICT
        log('Running ICT...');
        const ictOut = execSync('/usr/local/bin/node ' + SCANNER_FILE, { timeout: 30000, encoding: 'utf8' });
        
        // Parse signals
        const ictLines = ictOut.split('\n').filter(l => /^\s+[A-Z0-9.]+:\s+(Long|Short|None)/.test(l));
        const lstmLines = lstmOut.split('\n').filter(l => l.includes('Signal') || l.includes('Long') || l.includes('Short'));
        
        // Build message
        let msg = '🧠 <b>' + kz + ' KZ 開盤 - LSTM 信號</b>\n';
        msg += '📅 ' + hktTime() + '\n\n';
        if (lstmLines.length > 0) {
            msg += '<pre>' + lstmLines.slice(0,12).join('\n') + '</pre>\n';
        }
        msg += '<b>ICT:</b>\n<pre>' + ictLines.slice(0,9).join('\n') + '</pre>';
        
        await sendTelegram(msg);
        log('LSTM ' + kz + ' DONE');
        
    } catch(e) {
        log('LSTM ' + kz + ' ERROR: ' + e.message);
        try { await sendTelegram('❌ LSTM ' + kz + ' 失敗: ' + e.message); } catch(e2) {}
    }
}

main().catch(e => { log('FATAL: ' + e.message); process.exit(1); });
