#!/usr/bin/env node
// dl_coinbase.cjs
// Coinbase Exchange API fetcher (no rate limits, public, real-time)
// Maps crypto pairs to futures symbols for ICT scanner

const https = require('https');
const fs = require('fs');
const path = require('path');

const BASE_DIR = '/home/node/.openclaw/workspace';

const SYMBOLS = {
    'MBT.F': 'BTC-USD',  // Bitcoin
    'MET.F': 'ETH-USD',  // Ethereum
};

function log(msg) {
    console.log(new Date().toISOString() + ' ' + msg);
}

function fetchCoinbase(productId, granularity = 900) {
    // 900 = 15min in seconds
    return new Promise((resolve) => {
        const url = `https://api.exchange.coinbase.com/products/${productId}/candles?granularity=${granularity}`;
        const req = https.get(url, {
            headers: {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
        }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => {
                if (res.statusCode !== 200) {
                    log(`[HTTP ${res.statusCode}] ${productId}`);
                    resolve(null);
                    return;
                }
                try {
                    // Format: [time, low, high, open, close, volume]
                    const arr = JSON.parse(data);
                    resolve(arr);
                } catch (e) {
                    log(`[PARSE_ERR] ${productId}: ${e.message}`);
                    resolve(null);
                }
            });
        });
        req.on('error', (e) => {
            log(`[REQ_ERR] ${productId}: ${e.message}`);
            resolve(null);
        });
        req.setTimeout(30000, () => {
            log(`[TIMEOUT] ${productId}`);
            req.destroy();
            resolve(null);
        });
    });
}

function parseExistingCsv(fname) {
    // Returns Map<isoTimestamp, [open, high, low, close, volume]>
    const map = new Map();
    if (!fs.existsSync(fname)) return map;
    try {
        const text = fs.readFileSync(fname, 'utf8');
        const lines = text.split('\n').filter(l => l.trim());
        if (lines.length < 2) return map;
        // Skip header
        for (let i = 1; i < lines.length; i++) {
            const parts = lines[i].split(',');
            if (parts.length < 6) continue;
            const ts = parts[0];
            const o = parseFloat(parts[1]);
            const h = parseFloat(parts[2]);
            const l = parseFloat(parts[3]);
            const c = parseFloat(parts[4]);
            const v = parseFloat(parts[5]);
            if (!isNaN(o) && !isNaN(c)) {
                map.set(ts, [o, h, l, c, v]);
            }
        }
    } catch (e) {
        log(`[READ_ERR] ${fname}: ${e.message}`);
    }
    return map;
}

function candlesToRows(candles) {
    // Coinbase format: [time, low, high, open, close, volume]
    // Returns Map<isoTimestamp, [open, high, low, close, volume]> (deduped by ts)
    const map = new Map();
    for (const c of candles) {
        const [ts, low, high, open, close, vol] = c;
        if (ts == null || open == null || close == null) continue;
        const dt = new Date(ts * 1000);
        const datePart = dt.toISOString().substring(0, 19);
        const key = `${datePart}-04:00`;
        map.set(key, [open, high, low, close, vol]);
    }
    return map;
}

function toCsv(rows) {
    // rows: Map<isoTimestamp, [o,h,l,c,v]> - already deduped
    const sorted = [...rows.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    const lines = ['datetime,open,high,low,close,volume'];
    for (const [ts, vals] of sorted) {
        const [o, h, l, c, v] = vals;
        lines.push(`${ts},${o},${h},${l},${c},${v}`);
    }
    return lines.join('\n');
}

async function main() {
    log('=== Coinbase 15min Download ===');
    let ok = 0, failed = 0;

    for (const [ourSym, cbSym] of Object.entries(SYMBOLS)) {
        const fname = path.join(BASE_DIR, `${ourSym.replace('.', '_')}_15min.csv`);

        const candles = await fetchCoinbase(cbSym, 900);  // 15min
        if (candles && candles.length > 0) {
            // Load existing CSV (historical bars) and merge with new candles (dedup by timestamp)
            const existing = parseExistingCsv(fname);
            const fresh = candlesToRows(candles);
            const merged = new Map([...existing, ...fresh]);  // fresh wins on collision
            const csv = toCsv(merged);
            fs.writeFileSync(fname, csv);
            const lastBar = candles[0];  // Coinbase returns desc order
            const lastTs = new Date(lastBar[0] * 1000).toISOString();
            log(`[OK] ${ourSym} (${cbSym}): fresh=${candles.length} merged=${merged.size} (existed=${existing.size}) last: ${lastTs}`);
            ok++;
        } else {
            log(`[FAIL] ${ourSym} (${cbSym})`);
            failed++;
        }
        await new Promise(r => setTimeout(r, 500));
    }

    log(`=== Done: ${ok} ok, ${failed} failed ===`);
}

main().catch(e => log('[FATAL] ' + e.message));
