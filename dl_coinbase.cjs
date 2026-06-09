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

function toCsv(candles, symbol) {
    // Coinbase format: [time, low, high, open, close, volume]
    // Sort ascending by time
    const sorted = [...candles].sort((a, b) => a[0] - b[0]);
    const lines = ['datetime,open,high,low,close,volume'];
    for (const c of sorted) {
        const [ts, low, high, open, close, vol] = c;
        const dt = new Date(ts * 1000);
        // ET timezone offset for compatibility
        const datePart = dt.toISOString().substring(0, 19);
        lines.push(`${datePart}-04:00,${open},${high},${low},${close},${vol}`);
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
            const csv = toCsv(candles, ourSym);
            fs.writeFileSync(fname, csv);
            const lastBar = candles[0];  // Coinbase returns desc order
            const lastTs = new Date(lastBar[0] * 1000).toISOString();
            log(`[OK] ${ourSym} (${cbSym}): ${candles.length} bars, last: ${lastTs}`);
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
