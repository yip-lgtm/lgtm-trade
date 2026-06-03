#!/usr/bin/env node
// /tmp/dl_node.js
// Yahoo Finance CSV downloader for KZ scheduler

const https = require('https');
const fs = require('fs');
const path = require('path');

const BASE_DIR = '/home/node/.openclaw/workspace';

const SYMBOLS = {
    'MES.F': 'MES=F',
    'MNQ.F': 'MNQ=F',
    'M2K.F': 'M2K=F',
    'MYM.F': 'MYM=F',
    'M6E.F': '6E=F',
    'M6A.F': '6A=F',
    'MCL.F': 'CL=F',
    'MGC.F': 'GC=F',
    'MBT.F': 'BTC=F',
    'MET.F': 'ETH=F',
    'ES.F': 'ES=F',
    'NQ.F': 'NQ=F'
};

function log(msg) {
    console.log(new Date().toISOString() + ' ' + msg);
}

function fetchYahoo(yahooSym, range = '1y', interval = '1d') {
    return new Promise((resolve) => {
        const url = `https://query1.finance.yahoo.com/v8/finance/chart/${yahooSym}?interval=${interval}&range=${range}`;
        const req = https.get(url, {
            headers: { 'User-Agent': 'Mozilla/5.0' }
        }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => {
                if (res.statusCode !== 200) {
                    log(`[HTTP ${res.statusCode}] ${yahooSym}`);
                    resolve(null);
                    return;
                }
                try {
                    const j = JSON.parse(data);
                    const result = j.chart?.result?.[0];
                    if (!result) { log('[NO_DATA] ' + yahooSym); resolve(null); return; }
                    resolve(result);
                } catch (e) {
                    log('[PARSE_ERR] ' + yahooSym + ': ' + e.message);
                    resolve(null);
                }
            });
        });
        req.on('error', (e) => { log('[NET_ERR] ' + yahooSym + ': ' + e.message); resolve(null); });
        req.setTimeout(30000, () => { req.destroy(); log('[TIMEOUT] ' + yahooSym); resolve(null); });
    });
}

function resultToCSV(result) {
    if (!result) return null;
    const ts = result.timestamp || [];
    const q = result.indicators?.quote?.[0] || {};
    if (ts.length === 0) return null;
    let csv = 'datetime,open,high,low,close,volume\n';
    for (let i = 0; i < ts.length; i++) {
        const d = new Date(ts[i] * 1000).toISOString().replace('T', ' ').substr(0, 19);
        const o = q.open?.[i] ?? 0;
        const h = q.high?.[i] ?? 0;
        const l = q.low?.[i] ?? 0;
        const c = q.close?.[i] ?? 0;
        const v = q.volume?.[i] ?? 0;
        csv += `${d},${o},${h},${l},${c},${v}\n`;
    }
    return csv;
}

async function downloadOne(scannerSym, yahooSym) {
    const result = await fetchYahoo(yahooSym);
    if (!result) return false;
    const csv = resultToCSV(result);
    if (!csv) return false;
    const outputFile = path.join(BASE_DIR, scannerSym + '.csv');
    try {
        fs.writeFileSync(outputFile, csv);
        const lines = csv.split('\n').length - 1;
        log(`[SAVED] ${outputFile} (${lines} rows)`);
        return true;
    } catch (e) {
        log('[SAVE_ERR] ' + outputFile + ': ' + e.message);
        return false;
    }
}

async function main() {
    log('=== Yahoo Finance CSV Download ===');
    const entries = Object.entries(SYMBOLS);
    let success = 0, failed = 0;
    for (const [scannerSym, yahooSym] of entries) {
        const ok = await downloadOne(scannerSym, yahooSym);
        if (ok) success++; else failed++;
        await new Promise(r => setTimeout(r, 1500));
    }
    log(`=== Done: ${success} ok, ${failed} failed ===`);
}

main().catch(e => { log('[FATAL] ' + e.message); process.exit(1); });
