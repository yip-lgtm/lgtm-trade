#!/usr/bin/env node
/**
 * Trade Chart Generator - ASCII art + text summary
 * Generates a simple text-based trade visualization
 */
'use strict';

const fs = require('fs');

const SYM = process.argv[2] || 'MCL.F';
const PRICE_FILE = `${SYM}.csv`;
const TRADES_FILE = 'backtest_results.csv';

function main() {
    // Load trades for this symbol
    const tradesLines = fs.readFileSync(TRADES_FILE, 'utf8').trim().split('\n');
    const trades = tradesLines.slice(1).map(line => {
        const [date, symbol, direction, entry, exit, pnl] = line.split(',');
        return { date, symbol, direction, entry: +entry, exit: +exit, pnl: +pnl };
    }).filter(t => t.symbol === SYM);

    if (trades.length === 0) {
        console.log(`No trades for ${SYM}`);
        return;
    }

    // Load price data
    const priceLines = fs.readFileSync(PRICE_FILE, 'utf8').trim().split('\n');
    const prices = priceLines.slice(1).map(line => {
        const [dt, o, h, l, c, v] = line.split(',');
        return { datetime: dt, open: +o, high: +h, low: +l, close: +c };
    });

    console.log(`\n${'='*70}`);
    console.log(`📈 ${SYM} Trade Chart (ASCII Visualization)`);
    console.log(`${'='*70}`);

    // Simple price chart (last 100 candles)
    const recent = prices.slice(-100);
    const minPx = Math.min(...recent.map(p => p.low));
    const maxPx = Math.max(...recent.map(p => p.high));
    const range = maxPx - minPx;
    const width = 60;
    const height = 20;

    // Build ASCII chart
    const grid = Array.from({ length: height }, () => Array(width).fill(' '));
    const colStep = range / width;
    const rowStep = recent.length / height;

    // Plot candles
    for (let ri = 0; ri < recent.length; ri++) {
        const p = recent[ri];
        const col = Math.floor((p.close - minPx) / colStep);
        const boundedCol = Math.max(0, Math.min(width - 1, col));

        // Find row
        const row = Math.floor(ri / rowStep);
        const boundedRow = Math.max(0, Math.min(height - 1, row));

        if (p.close >= p.open) {
            grid[boundedRow][boundedCol] = '▲';
        } else {
            grid[boundedRow][boundedCol] = '▼';
        }
    }

    // Mark trade entries/exits
    trades.forEach(t => {
        const dt = t.date.split(' ')[0];
        const entryTime = dt + ' ' + t.date.split(' ')[1];
        const idx = prices.findIndex(p => p.datetime.startsWith(dt));
        if (idx >= 0) {
            const col = Math.floor((t.entry - minPx) / colStep);
            const row = Math.floor(idx / rowStep);
            const bRow = Math.max(0, Math.min(height - 1, row));
            const bCol = Math.max(0, Math.min(width - 1, Math.floor(col)));
            if (grid[bRow][bCol] === '▲' || grid[bRow][bCol] === '▼') {
                grid[bRow][bCol] = t.direction === 'Long' ? '●' : '○';
            }
        }
    });

    // Print chart
    console.log(`\n  ${maxPx.toFixed(2)}`);
    for (let r = 0; r < height; r++) {
        const priceLabel = (maxPx - (r / height) * range).toFixed(2);
        let line = priceLabel.padStart(8) + ' |';
        for (let c = 0; c < width; c++) {
            line += grid[r][c];
        }
        line += '|';
        if (r === Math.floor(height / 2)) line += ` ${(minPx + range/2).toFixed(2)} (mid)`;
        console.log(line);
    }
    console.log(`         +${'-'.repeat(width)}+`);
    console.log(`         ${minPx.toFixed(2)} (low)`);
    console.log(`\n  ▲=Bullish ▼=Bearish ●=LongEntry ○=ShortEntry`);

    // Trade list
    console.log(`\n${'='*70}`);
    console.log(`📋 Trade Details (${trades.length} trades)`);
    console.log(`${'='*70}`);
    trades.slice(0, 15).forEach((t, i) => {
        const emoji = t.pnl >= 0 ? '✅' : '❌';
        console.log(`${emoji} ${i+1}. ${t.date} | ${t.direction} | Entry:${t.entry.toFixed(4)} Exit:${t.exit.toFixed(4)} PnL:$${t.pnl.toFixed(0)}`);
    });
    if (trades.length > 15) console.log(`  ... and ${trades.length - 15} more trades`);

    const totalPnL = trades.reduce((a, t) => a + t.pnl, 0);
    const wins = trades.filter(t => t.pnl > 0).length;
    const wr = wins / trades.length * 100;
    console.log(`\n  Total PnL: $${totalPnL.toFixed(0)} | Win Rate: ${wr.toFixed(1)}%`);
    console.log(`${'='*70}\n`);
}

main();
