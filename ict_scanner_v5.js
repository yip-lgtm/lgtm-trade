#!/usr/bin/env node
/**
 * ICT Signal Scanner v5 - NO LSTM, pure ICT technical analysis
 * Lightning fast (< 1 second per symbol)
 * Combines RSI + EMA crossover + FVG + OTE Zone + MACD
 */
'use strict';

const fs = require('fs');

const POINT_VALUE = { 'MES.F':5, 'MNQ.F':2, 'M2K.F':5, 'MYM.F':0.5, 'M6E.F':12500, 'M6A.F':10000, 'MCL.F':100, 'MBT.F':10, 'MET.F':1 };
const CONTRACTS  = { 'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':2, 'M6A.F':2, 'MCL.F':1, 'MBT.F':2, 'MET.F':2 };
const PRECISION  = { 'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':4, 'M6A.F':4, 'MCL.F':2, 'MBT.F':2, 'MET.F':2 };
const SL_TICKS   = { 'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10, 'MBT.F':10, 'MET.F':10 };
const TP1_TICKS  = { 'MES.F':30, 'MNQ.F':30, 'M2K.F':30, 'MYM.F':30, 'M6E.F':30, 'M6A.F':30, 'MCL.F':30, 'MBT.F':30, 'MET.F':30 };
const TP2_TICKS  = { 'MES.F':60, 'MNQ.F':60, 'M2K.F':60, 'MYM.F':60, 'M6E.F':60, 'M6A.F':60, 'MCL.F':60, 'MBT.F':60, 'MET.F':60 };
const CSV_FILES  = { 'MES.F':'MES.F.csv','MNQ.F':'MNQ.F.csv','M2K.F':'M2K.F.csv','MYM.F':'MYM.F.csv','M6E.F':'M6E.F.csv','M6A.F':'M6A.F.csv','MCL.F':'MCL.F.csv','MBT.F':'MBT.F.csv','MET.F':'MET.F.csv' };

function isKillZone(utcStr) {
    const dt = new Date(utcStr + ' UTC');
    const est = new Date(dt.getTime() - 4*60*60*1000);
    const h = est.getUTCHours(), m = est.getUTCMinutes();
    if (h >= 3 && h < 4) return 'London';
    if ((h === 9 && m >= 30) || (h === 10 && m < 30)) return 'NY';
    return null;
}

function parseCSV(fname) {
    return fs.readFileSync(fname, 'utf8').trim().split('\n').slice(1)
        .map(line => { const v = line.split(','); return v.length >= 6 ? { datetime: v[0], open: +v[1], high: +v[2], low: +v[3], close: +v[4], volume: +v[5] } : null; })
        .filter(Boolean);
}

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

function macd(closes) {
    const e12 = ema(closes, 12), e26 = ema(closes, 26);
    const macdLine = e12.map((v, i) => v != null && e26[i] != null ? v - e26[i] : null);
    const sig = ema(macdLine.filter(v => v != null), 9);
    // align sig to original index
    const sigOut = new Array(closes.length).fill(null);
    let si = 0;
    for (let i = 0; i < closes.length; i++) if (macdLine[i] != null) { if (si < sig.length) sigOut[i] = sig[si++]; }
    return { macd: macdLine, signal: sigOut };
}

function bbands(closes, period = 20, stdDev = 2) {
    const out = { upper: new Array(closes.length).fill(null), middle: new Array(closes.length).fill(null), lower: new Array(closes.length).fill(null) };
    for (let i = period-1; i < closes.length; i++) {
        const slice = closes.slice(i-period+1, i+1);
        const mean = slice.reduce((a,b)=>a+b,0)/period;
        const std = Math.sqrt(slice.reduce((a,b)=>a+(b-mean)*(b-mean),0)/period);
        out.middle[i] = mean; out.upper[i] = mean + stdDev*std; out.lower[i] = mean - stdDev*std;
    }
    return out;
}

function runScan() {
    const nowHK = new Date().toLocaleString('zh-HK', { timeZone: 'Asia/Hong_Kong' });
    console.log(`\n${'='*65}`);
    console.log(`🕒 ${nowHK} ICT 掃描（v5 - 極速版）`);
    console.log(`$3K target | $200 SL kill-switch | Max 2 micro | MCL 1 contract`);
    console.log(`${'='*65}`);

    let kzAlerts = [];

    for (const [sym, fname] of Object.entries(CSV_FILES)) {
        try {
            const data = parseCSV(fname);
            if (data.length < 50) { console.log(`  ${sym}: ❌ 數據不足 (${data.length})`); continue; }

            const closes = data.map(d => d.close);
            const highs = data.map(d => d.high);
            const lows = data.map(d => d.low);
            const volumes = data.map(d => d.volume);
            const n = closes.length;
            const i = n - 1;

            // ICT + TA indicators
            const rsiVal = rsi(closes);
            const ema12 = ema(closes, 12);
            const ema26 = ema(closes, 26);
            const atrVal = atr(highs, lows, closes);
            const { macd: macdLine, signal: macdSig } = macd(closes);
            const bb = bbands(closes);

            // Volume SMA
            let volSma = 0;
            { const slice = volumes.slice(-20); volSma = slice.reduce((a,b)=>a+b,0)/20; }
            const curVol = volumes[i];
            const volAboveAvg = curVol > volSma;

            // Swing structures
            const swingH = highs.map((_, idx) => idx >= 20 ? Math.max(...highs.slice(idx-20, idx)) : null);
            const swingL = lows.map((_, idx) => idx >= 20 ? Math.min(...lows.slice(idx-20, idx)) : null);
            const fibR = swingH.map((sh, idx) => sh != null && swingL[idx] != null ? sh - swingL[idx] : null);

            // FVG
            const fvgBull = lows.map((_, idx) => idx >= 2 && lows[idx-1] > highs[idx-2] ? 1 : 0);
            const fvgBear = highs.map((_, idx) => idx >= 2 && highs[idx-1] < lows[idx-2] ? 1 : 0);

            // OTE Zone
            const ote79B = swingL.map((sl, idx) => sl != null && fibR[idx] != null ? sl + fibR[idx]*0.79 : null);
            const ote79Be = swingH.map((sh, idx) => sh != null && fibR[idx] != null ? sh - fibR[idx]*0.79 : null);
            const inOteBull = swingL.map((sl, idx) => sl != null && fibR[idx] > 0 ? (closes[idx] >= sl + fibR[idx]*0.62 && closes[idx] <= ote79B[idx] ? 1 : 0) : 0);
            const inOteBear = swingH.map((sh, idx) => sh != null && fibR[idx] > 0 ? (closes[idx] <= sh - fibR[idx]*0.62 && closes[idx] >= ote79Be[idx] ? 1 : 0) : 0);

            const cur = closes[i], curAtr = atrVal[i] || 0;
            const ema12Val = ema12[i] || 0, ema26Val = ema26[i] || 0;
            const rsiV = rsiVal[i] || 50;
            const macdV = macdLine[i] || 0, macdSigV = macdSig[i] || 0;
            const bbU = bb.upper[i] || cur, bbL = bb.lower[i] || cur;
            const curSwingH = swingH[i], curSwingL = swingL[i], curFibR = fibR[i];
            const curFvgBull = fvgBull[i] || 0, curFvgBear = fvgBear[i] || 0;
            const curInOteBull = inOteBull[i] || 0, curInOteBear = inOteBear[i] || 0;
            const kz = isKillZone(data[i].datetime);
            const pv = POINT_VALUE[sym], contracts = CONTRACTS[sym], prec = PRECISION[sym];

            // ===== ICT Bullish Conditions =====
            const bullRSI = rsiV < 60 && rsiV > 30;          // Not overbought
            const bullEMA = ema12Val > ema26Val;              // Up trend
            const bullMACD = macdV > macdSigV;               // MACD bullish
            const bullBB = cur > bbL && cur < (bbU + bbL)/2;  // Near lower BB
            const bullFVG = curFvgBull === 1 || curInOteBull === 1; // FVG or OTE bull
            const bullBreak = curSwingH != null && cur > curSwingH * 0.998; // Breaking swing high

            // ===== ICT Bearish Conditions =====
            const bearRSI = rsiV > 40 && rsiV < 70;           // Not oversold
            const bearEMA = ema12Val < ema26Val;              // Down trend
            const bearMACD = macdV < macdSigV;               // MACD bearish
            const bearBB = cur < bbU && cur > (bbU + bbL)/2;  // Near upper BB
            const bearFVG = curFvgBear === 1 || curInOteBear === 1; // FVG or OTE bear
            const bearBreak = curSwingL != null && cur < curSwingL * 1.002; // Breaking swing low

            // ===== Signals =====
            let signal = 0; // 1=Long, -1=Short, 0=None
            let confidence = 0;
            let reasons = [];

            if (bullRSI && bullEMA && (bullFVG || bullBreak)) {
                signal = 1; confidence = (bullFVG ? 3 : 1) + (bullMACD ? 1 : 0) + (bullBB ? 1 : 0);
                reasons = ['EMA交叉睇好', bullFVG ? 'FVG/OTE做多' : '突破SW High', bullMACD ? 'MACD陽' : '', volAboveAvg ? '成交量放大' : ''].filter(Boolean);
            } else if (bearRSI && bearEMA && (bearFVG || bearBreak)) {
                signal = -1; confidence = (bearFVG ? 3 : 1) + (bearMACD ? 1 : 0) + (bearBB ? 1 : 0);
                reasons = ['EMA交叉睇淡', bearFVG ? 'FVG/OTE做空' : '突破SW Low', bearMACD ? 'MACD陰' : '', volAboveAvg ? '成交量放大' : ''].filter(Boolean);
            }

            // SL/TP calculation
            const slPoints = 200 / (pv * contracts);
            const entry = cur;
            const sl = signal === 1 ? entry - slPoints : signal === -1 ? entry + slPoints : null;
            const tp1 = signal === 1 ? entry + TP1_TICKS[sym]*slPoints : signal === -1 ? entry - TP1_TICKS[sym]*slPoints : null;
            const tp2 = signal === 1 ? entry + TP2_TICKS[sym]*slPoints : signal === -1 ? entry - TP2_TICKS[sym]*slPoints : null;
            const estPnl = signal !== 0 ? Math.round(TP1_TICKS[sym] * 200 * contracts * 100)/100 : 0;

            const sigStr = signal === 1 ? 'Long ' : signal === -1 ? 'Short' : 'None';
            const confStr = signal !== 0 ? `(${confidence}/5)` : '';
            console.log(`  ${sym}: ${sigStr} ${confStr} @ ${cur.toFixed(prec)} | RSI:${rsiV.toFixed(0)} KZ:${kz||'--'} Est:$${estPnl}`);
            if (signal !== 0 && reasons.length > 0) console.log(`     → ${reasons.join(' | ')}`);

            if (signal !== 0 && kz) {
                console.log(`  🔥🔥🔥 ${kz} KILL ZONE 有效信號！！！`);
                console.log(`     Entry:${entry.toFixed(prec)} | SL:${sl.toFixed(prec)} | TP1:${tp1.toFixed(prec)} | TP2:${tp2.toFixed(prec)}`);
                console.log(`     風險 $200 | 目標 TP1:$${TP1_TICKS[sym]*200} TP2:$${TP2_TICKS[sym]*200} | ${contracts}合約`);
                kzAlerts.push({ sym, signal, entry, sl, tp1, tp2, contracts, kz });
            }
        } catch(e) {
            console.log(`  ${sym}: ❌ ${e.message}`);
        }
    }

    if (kzAlerts.length === 0) {
        console.log(`\n⏳ 目前不在 Kill Zone 或冇有效信號，安全等待...`);
    } else {
        console.log(`\n🔥🔥🔥 共 ${kzAlerts.length} 個 KZ 信號，請立即檢查！`);
    }
    console.log(`\n📊 完成\n`);
    return kzAlerts;
}

// ====================== Main ======================
let cnt = 0;
console.log('🚀 ICT Scanner v5 已啟動（每小時一次）');
console.log('London KZ: 15:00-16:00 HKT | NY KZ: 21:30-22:30 HKT');
console.log('按 Ctrl+C 停止\n');

while (true) {
    cnt++;
    console.log(`\n${'#'.repeat(65)}\n第 ${cnt} 次掃描`);
    runScan();
    // For testing: exit after first run
    // For production: use setTimeout
    // break; // uncomment for one-shot test
    const now = new Date();
    const msUntilNextHour = (60 - now.getMinutes()) * 60 * 1000;
    console.log(`下次掃描: ${new Date(now.getTime() + msUntilNextHour).toLocaleString('zh-HK', {timeZone:'Asia/Hong_Kong'})}`);
    break; // one-shot for now, add while loop for continuous
}
