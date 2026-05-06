#!/usr/bin/env node
/**
 * ICT Backtest v1 - 60 day walk-forward backtest
 * Tests the ICT strategy on historical data
 */
'use strict';

const fs = require('fs');

// ====== CONFIG ======
const POINT_VALUE = { 'MES.F':5, 'MNQ.F':2, 'M2K.F':5, 'MYM.F':0.5, 'M6E.F':12500, 'M6A.F':10000, 'MCL.F':100, 'MBT.F':10, 'MET.F':1 };
const CONTRACTS  = { 'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':2, 'M6A.F':2, 'MCL.F':1, 'MBT.F':2, 'MET.F':2 };
const SL_TICKS   = 10;
const TP1_TICKS  = 30;
const TP2_TICKS  = 60;
const DAILY_LOSS_LIMIT = 200;
const CSV_FILES  = { 'MES.F':'MES.F.csv','MNQ.F':'MNQ.F.csv','M2K.F':'M2K.F.csv','MYM.F':'MYM.F.csv','M6E.F':'M6E.F.csv','M6A.F':'M6A.F.csv','MCL.F':'MCL.F.csv','MBT.F':'MBT.F.csv','MET.F':'MET.F.csv' };

// ====== INDICATORS ======
function rsi(closes, period = 14) {
    const out = new Array(closes.length).fill(null);
    let avgG = 0, avgL = 0;
    for (let i = 1; i <= period; i++) { const d = closes[i] - closes[i-1]; if (d > 0) avgG += d; else avgL -= d; }
    avgG /= period; avgL /= period;
    for (let i = period; i < closes.length; i++) {
        if (i > period) { const d = closes[i] - closes[i-1]; avgG = (avgG*(period-1) + (d>0?d:0))/period; avgL = (avgL*(period-1) + (d<0?-d:0))/period; }
        out[i] = avgL === 0 ? 100 : 100 - 100/(1 + avgG/avgL);
    }
    return out;
}

function ema(closes, period) {
    const out = new Array(closes.length).fill(null);
    const k = 2/(period+1);
    for (let i = period-1; i < closes.length; i++) {
        out[i] = i === period-1 ? closes.slice(0,period).reduce((a,b)=>a+b,0)/period : closes[i]*k + out[i-1]*(1-k);
    }
    return out;
}

function atr(highs, lows, closes, period = 14) {
    const out = new Array(closes.length).fill(null);
    let sum = 0;
    for (let i = 1; i <= period; i++) sum += Math.max(highs[i]-lows[i], Math.abs(highs[i]-closes[i-1]), Math.abs(lows[i]-closes[i-1]));
    out[period] = sum/period;
    for (let i = period+1; i < closes.length; i++) {
        const tr = Math.max(highs[i]-lows[i], Math.abs(highs[i]-closes[i-1]), Math.abs(lows[i]-closes[i-1]));
        out[i] = (out[i-1]*(period-1) + tr)/period;
    }
    return out;
}

function isKillZone(utcStr) {
    const dt = new Date(utcStr + ' UTC');
    const est = new Date(dt.getTime() - 4*60*60*1000);
    const h = est.getUTCHours(), m = est.getUTCMinutes();
    if (h >= 3 && h < 4) return 'London';
    if ((h === 9 && m >= 30) || (h === 10 && m < 30)) return 'NY';
    return null;
}

// ====== MAIN BACKTEST ======
function backtestSymbol(sym, fname) {
    const data = fs.readFileSync(fname, 'utf8').trim().split('\n').slice(1)
        .map(line => { const v = line.split(','); return v.length >= 6 ? { datetime: v[0], open: +v[1], high: +v[2], low: +v[3], close: +v[4], volume: +v[5] } : null; })
        .filter(Boolean);

    if (data.length < 100) return null;

    const closes = data.map(d => d.close);
    const highs = data.map(d => d.high);
    const lows = data.map(d => d.low);
    const rsiVal = rsi(closes);
    const ema12 = ema(closes, 12);
    const ema26 = ema(closes, 26);
    const atrVal = atr(highs, lows, closes);

    const swingH = highs.map((_, i) => i >= 20 ? Math.max(...highs.slice(i-20, i)) : null);
    const swingL = lows.map((_, i) => i >= 20 ? Math.min(...lows.slice(i-20, i)) : null);
    const fibR = swingH.map((sh, i) => sh != null && swingL[i] != null ? sh - swingL[i] : null);
    const fvgBull = lows.map((_, i) => i >= 2 && lows[i-1] > highs[i-2] ? 1 : 0);
    const fvgBear = highs.map((_, i) => i >= 2 && highs[i-1] < lows[i-2] ? 1 : 0);
    const ote79B = swingL.map((sl, i) => sl != null && fibR[i] != null ? sl + fibR[i]*0.79 : null);
    const ote79Be = swingH.map((sh, i) => sh != null && fibR[i] != null ? sh - fibR[i]*0.79 : null);
    const inOteBull = swingL.map((sl, i) => sl != null && fibR[i] > 0 ? (closes[i] >= sl + fibR[i]*0.62 && closes[i] <= ote79B[i] ? 1 : 0) : 0);
    const inOteBear = swingH.map((sh, i) => sh != null && fibR[i] > 0 ? (closes[i] <= sh - fibR[i]*0.62 && closes[i] >= ote79Be[i] ? 1 : 0) : 0);

    const pv = POINT_VALUE[sym];
    const contracts = CONTRACTS[sym];
    const slDollar = DAILY_LOSS_LIMIT;
    const slTicks = slDollar / (pv * contracts);

    const trades = [];
    let pos = null; // null or {entry, sl, tp1, tp2, dir, date, entryPrice}
    let dailyPnL = 0;
    let dailyDates = new Set();
    let totalPnL = 0;
    let wins = 0, losses = 0;
    const dailyMaxLoss = { date: null, loss: 0 };

    for (let i = 50; i < data.length; i++) {
        const cur = closes[i], curAtr = atrVal[i] || 0;
        const curEma12 = ema12[i] || 0, curEma26 = ema26[i] || 0;
        const rsv = rsiVal[i] || 50;
        const curSwingH = swingH[i], curSwingL = swingL[i];
        const curFvgBull = fvgBull[i] || 0, curFvgBear = fvgBear[i] || 0;
        const curInOteBull = inOteBull[i] || 0, curInOteBear = inOteBear[i] || 0;
        const kz = isKillZone(data[i].datetime);

        const bullRSI = rsv < 60 && rsv > 30;
        const bearRSI = rsv > 40 && rsv < 70;
        const bullEMA = curEma12 > curEma26;
        const bearEMA = curEma12 < curEma26;
        const bullBreak = curSwingH != null && cur > curSwingH * 0.998;
        const bearBreak = curSwingL != null && cur < curSwingL * 1.002;

        const bullSignal = bullRSI && bullEMA && (curFvgBull === 1 || curInOteBull === 1 || bullBreak);
        const bearSignal = bearRSI && bearEMA && (curFvgBear === 1 || curInOteBear === 1 || bearBreak);

        // Daily loss reset
        const dateStr = data[i].datetime.split(' ')[0];
        if (!dailyDates.has(dateStr)) {
            dailyPnL = 0;
            dailyDates.add(dateStr);
        }

        // Check if position hit SL/TP
        if (pos) {
            let closed = false;
            let pnl = 0;
            if (pos.dir === 1) {
                if (cur <= pos.sl) { pnl = -slDollar; closed = true; }
                else if (cur >= pos.tp1) { pnl = slDollar * 3; closed = true; }
                else if (cur >= pos.tp2) { pnl = slDollar * 6; closed = true; }
            } else {
                if (cur >= pos.sl) { pnl = -slDollar; closed = true; }
                else if (cur <= pos.tp1) { pnl = slDollar * 3; closed = true; }
                else if (cur <= pos.tp2) { pnl = slDollar * 6; closed = true; }
            }

            if (closed) {
                trades.push({ date: data[i].datetime, sym, dir: pos.dir === 1 ? 'Long' : 'Short', entry: pos.entryPrice, exit: cur, pnl, kz: pos.kz });
                totalPnL += pnl;
                dailyPnL += pnl;
                if (pnl > 0) wins++;
                else {
                    losses++;
                    if (dailyPnL < dailyMaxLoss.loss) {
                        dailyMaxLoss.loss = dailyPnL;
                        dailyMaxLoss.date = dateStr;
                    }
                }
                pos = null;
            }
        }

        // Open new position
        if (!pos && kz) {
            if (bullSignal) {
                const entry = cur;
                const sl = entry - slTicks;
                pos = {
                    dir: 1, entryPrice: entry, sl, tp1: entry + slTicks, tp2: entry + slTicks * 2,
                    kz, date: data[i].datetime
                };
            } else if (bearSignal) {
                const entry = cur;
                const sl = entry + slTicks;
                pos = {
                    dir: -1, entryPrice: entry, sl, tp1: entry - slTicks, tp2: entry - slTicks * 2,
                    kz, date: data[i].datetime
                };
            }
        }
    }

    const winRate = trades.length > 0 ? (wins / trades.length * 100) : 0;
    return { sym, trades, totalPnL, wins, losses, winRate, count: trades.length, dailyMaxLoss, lastDate: data[data.length-1].datetime };
}

// ====== RUN ALL ======
function main() {
    const nowHK = new Date().toLocaleString('zh-HK', { timeZone: 'Asia/Hong_Kong' });
    console.log(`\n${'='*70}`);
    console.log(`📊 ICT Strategy 60-Day Backtest`);
    console.log(`🕒 ${nowHK}`);
    console.log(`$3K target | $200 Daily SL | Max 2 micro | MCL 1 contract`);
    console.log(`${'='*70}`);
    console.log(`Kill Zones: London 03:00-04:00 EST | NY 09:30-10:30 EST`);
    console.log(`${'='*70}\n`);

    let grandTotal = 0;
    let grandWins = 0, grandLosses = 0;
    let allTrades = [];

    for (const [sym, fname] of Object.entries(CSV_FILES)) {
        process.stdout.write(`${sym}... `);
        const result = backtestSymbol(sym, fname);
        if (!result) { console.log(`❌ 數據不足`); continue; }

        const { trades, totalPnL, wins, losses, winRate, count, dailyMaxLoss, lastDate } = result;
        const emoji = totalPnL >= 0 ? '✅' : '❌';
        console.log(`${emoji} ${count} trades | PnL: $${totalPnL.toFixed(2)} | WinRate: ${winRate.toFixed(1)}% | Last: ${lastDate}`);

        grandTotal += totalPnL;
        grandWins += wins;
        grandLosses += losses;
        allTrades.push(...trades);

        if (trades.length > 0) {
            console.log(`   → Wins: ${wins} | Losses: ${losses}`);
            if (dailyMaxLoss.date) console.log(`   → Worst Day: ${dailyMaxLoss.date} (-$${Math.abs(dailyMaxLoss.loss).toFixed(2)})`);
        }
    }

    const totalTrades = grandWins + grandLosses;
    const overallWinRate = totalTrades > 0 ? (grandWins / totalTrades * 100) : 0;

    console.log(`\n${'='*70}`);
    console.log(`📈 OVERALL RESULTS`);
    console.log(`${'='*70}`);
    console.log(`Total Trades: ${totalTrades}`);
    console.log(`Wins: ${grandWins} | Losses: ${grandLosses}`);
    console.log(`Overall Win Rate: ${overallWinRate.toFixed(1)}%`);
    console.log(`Total PnL: $${grandTotal.toFixed(2)}`);
    console.log(`${'='*70}`);

    // Save results
    if (allTrades.length > 0) {
        const df = allTrades.map(t => `${t.date},${t.sym},${t.dir},${t.entry.toFixed(4)},${t.exit.toFixed(4)},${t.pnl},${t.kz || ''}`);
        fs.writeFileSync('backtest_results.csv', `date,symbol,direction,entry,exit,pnl,killzone\n${df.join('\n')}`);
        console.log(`\n💾 Results saved to backtest_results.csv`);
    }
}

main();
