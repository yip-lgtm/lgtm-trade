#!/usr/bin/env node
// dl_polygon.cjs
// Polygon.io data fetcher for ICT scanner (fallback when Yahoo is rate limited)
// Supports crypto (X:BTCUSD, X:ETHUSD) and tries futures (I:MNQ, I:M2K)

const https = require('https');
const fs = require('fs');
const path = require('path');

const BASE_DIR = '/home/node/.openclaw/workspace';
const API_KEY = 'qhcML6ARpe0IWfGY57LnAsrZ1zTr3Ej0';

const SYMBOLS = {
    'MBT.F': 'X:BTCUSD',  // Bitcoin
    'MET.F': 'X:ETHUSD',  // Ethereum
    // Free tier doesn't have futures, but try anyway
    'MNQ.F': 'I:MNQ',
    'M2K.F': 'I:M2K',
};

function log(msg) {
    console.log(new Date().toISOString() + ' ' + msg);
}

function fetchPolygon(ticker, fromDate, toDate, multiplier = 15, timespan = 'minute') {
    return new Promise((resolve) => {
        const url = `https://api.polygon.io/v2/aggs/ticker/${ticker}/range/${multiplier}/${timespan}/${fromDate}/${toDate}?adjusted=true&sort=asc&limit=5000&apiKey=${API_KEY}`;
        const req = https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => {
                if (res.statusCode !== 200) {
                    log(`[HTTP ${res.statusCode}] ${ticker}`);
                    resolve(null);
                    return;
                }
                try {
                    const j = JSON.parse(data);
                    if (!j.results) {
                        log(`[NO_RESULTS] ${ticker}: ${j.status || '?'}`);
                        resolve(null);
                        return;
                    }
                    resolve(j.results);
                } catch (e) {
                    log(`[PARSE_ERR] ${ticker}: ${e.message}`);
                    resolve(null);
                }
            });
        });
        req.on('error', (e) => {
            log(`[REQ_ERR] ${ticker}: ${e.message}`);
            resolve(null);
        });
        req.setTimeout(30000, () => {
            log(`[TIMEOUT] ${ticker}`);
            req.destroy();
            resolve(null);
        });
    });
}

function resultsToCsv(results, symbol) {
    // Polygon: t=timestamp ms, o=open, h=high, l=low, c=close, v=volume
    const lines = ['datetime,open,high,low,close,volume'];
    for (const bar of results) {
        const dt = new Date(bar.t);
        // Format: YYYY-MM-DD HH:MM:SS-04:00 (US ET for compatibility with existing files)
        const iso = dt.toISOString();
        const datePart = iso.substring(0, 19);
        lines.push(`${datePart}-04:00,${bar.o},${bar.h},${bar.l},${bar.c},${bar.v}`);
    }
    return lines.join('\n');
}

async function main() {
    log('=== Polygon.io 15min Download ===');

    // Date range: last 30 days
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);
    const fromDate = start.toISOString().substring(0, 10);
    const toDate = end.toISOString().substring(0, 10);

    let ok = 0, failed = 0;

    for (const [ourSym, polySym] of Object.entries(SYMBOLS)) {
        // Use underscore in filename to match existing convention
        const fname = path.join(BASE_DIR, `${ourSym.replace('.', '_')}_15min.csv`);

        let results = await fetchPolygon(polySym, fromDate, toDate, 15, 'minute');
        let resolution = '15min';
        if (!results || results.length === 0) {
            log(`[15min empty] ${ourSym}, trying 60min...`);
            results = await fetchPolygon(polySym, fromDate, toDate, 60, 'minute');
            resolution = '60min';
        }
        if (results && results.length > 0) {
            const csv = resultsToCsv(results, ourSym);
            fs.writeFileSync(fname, csv);
            const lastBar = results[results.length - 1];
            const lastDt = new Date(lastBar.t).toISOString();
            log(`[OK] ${ourSym} (${polySym}): ${results.length} bars, last: ${lastDt}, file: ${fname}`);
            ok++;
        } else {
            log(`[FAIL] ${ourSym} (${polySym})`);
            failed++;
        }
        // Rate limit
        await new Promise(r => setTimeout(r, 500));
    }

    log(`=== Done: ${ok} ok, ${failed} failed ===`);
}

main().catch(e => log('[FATAL] ' + e.message));
