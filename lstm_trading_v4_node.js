#!/usr/bin/env node
/**
 * LSTM Trading Signals v4 - Node.js Version (Fixed)
 * TensorFlow.js + Server-compatible (no Python needed!)
 */
'use strict';

const fs = require('fs');
const path = require('path');

let tf;
try {
    tf = require('/usr/local/lib/node_modules/@tensorflow/tfjs-node');
    console.log(`tfjs-node: ${tf.version.tfjs}`);
} catch(e) {
    try {
        tf = require('/usr/local/lib/node_modules/@tensorflow/tfjs');
        console.log(`tfjs: ${tf.version.tfjs}`);
    } catch(e2) {
        console.error('❌ tfjs not found'); process.exit(1);
    }
}

// ====================== Config ======================
const POINT_VALUE = { 'MES.F':5, 'MNQ.F':2, 'M2K.F':5, 'MYM.F':0.5, 'M6E.F':12500, 'M6A.F':10000, 'MCL.F':100 };
const CONTRACTS  = { 'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':2, 'M6A.F':2, 'MCL.F':1 };
const PRECISION  = { 'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':4, 'M6A.F':4, 'MCL.F':2 };
const SL_TICKS    = { 'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10 };
const TP1_TICKS   = { 'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10 };
const TP2_TICKS   = { 'MES.F':20, 'MNQ.F':20, 'M2K.F':20, 'MYM.F':20, 'M6E.F':20, 'M6A.F':20, 'MCL.F':20 };
const CSV_FILES = { 'MES.F':'MES.F.csv','MNQ.F':'MNQ.F.csv','M2K.F':'M2K.F.csv','MYM.F':'MYM.F.csv','M6E.F':'M6E.F.csv','M6A.F':'M6A.F.csv','MCL.F':'MCL.F.csv' };

// ====================== Utils ======================
function isKillZone(utcStr) {
    const dt = new Date(utcStr + ' UTC');
    const est = new Date(dt.getTime() - 4*60*60*1000);
    const h = est.getUTCHours(), m = est.getUTCMinutes();
    if (h >= 3 && h < 4) return 'London';
    if ((h === 9 && m >= 30) || (h === 10 && m < 30)) return 'NY';
    return null;
}

function parseCSV(fname) {
    const lines = fs.readFileSync(fname, 'utf8').trim().split('\n');
    return lines.slice(1).map(line => {
        const v = line.split(',');
        if (v.length >= 6) return { datetime: v[0], open: +v[1], high: +v[2], low: +v[3], close: +v[4], volume: +v[5] };
        return null;
    }).filter(Boolean);
}

function rsi(closes, period = 14) {
    const out = new Array(closes.length).fill(null);
    let avgG = 0, avgL = 0;
    for (let i = 1; i <= period; i++) {
        const d = closes[i] - closes[i-1];
        if (d > 0) avgG += d; else avgL -= d;
    }
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
    let cur = closes.slice(0, period).reduce((a,b)=>a+b,0)/period;
    for (let i = period-1; i < closes.length; i++) {
        if (i === period-1) cur = closes[i];
        else cur = closes[i]*k + cur*(1-k);
        out[i] = cur;
    }
    return out;
}

function atr(highs, lows, closes, period = 14) {
    const out = new Array(closes.length).fill(null);
    let sum = 0;
    for (let i = 1; i <= period; i++) {
        sum += Math.max(highs[i]-lows[i], Math.abs(highs[i]-(closes[i-1]||closes[i])), Math.abs(lows[i]-(closes[i-1]||closes[i])));
    }
    out[period] = sum/period;
    for (let i = period+1; i < closes.length; i++) {
        const tr = Math.max(highs[i]-lows[i], Math.abs(highs[i]-closes[i-1]), Math.abs(lows[i]-closes[i-1]));
        out[i] = (out[i-1]*(period-1) + tr)/period;
    }
    return out;
}

function sma(closes, period) {
    const out = new Array(closes.length).fill(null);
    for (let i = period-1; i < closes.length; i++) {
        let s = 0; for (let j = i-period+1; j <= i; j++) s += closes[j];
        out[i] = s/period;
    }
    return out;
}

function minMaxScale(arr) {
    const min = Math.min(...arr), max = Math.max(...arr), range = max - min || 1;
    return arr.map(v => (v - min)/range);
}

// ====================== LSTM ======================
async function trainAndPredict(closes, epochs = 1) {
    const seqLen = 60;
    const recent = closes.slice(-Math.min(closes.length - seqLen - 5, 500));
    const mean = recent.reduce((a,b)=>a+b,0)/recent.length;
    const std = Math.sqrt(recent.reduce((a,b)=>a+(b-mean)*(b-mean),0)/recent.length) || 1;
    const scaled = closes.map(v => (v - mean)/std);

    const trainSize = Math.floor(scaled.length * 0.92);
    const xTrain = [], yTrain = [];
    for (let i = seqLen; i < trainSize; i++) xTrain.push(scaled.slice(i-seqLen, i)), yTrain.push(scaled[i]);

    const model = tf.sequential();
    model.add(tf.layers.lstm({ units: 32, returnSequences: false, inputShape: [seqLen, 1] }));
    model.add(tf.layers.dense({ units: 16, activation: 'relu' }));
    model.add(tf.layers.dense({ units: 1 }));
    model.compile({ optimizer: tf.train.adam(0.01), loss: 'meanSquaredError' });

    const xt = tf.tensor3d(xTrain.map(s => s.map(v => [v])), [xTrain.length, seqLen, 1]);
    const yt = tf.tensor2d(yTrain, [yTrain.length, 1]);
    await model.fit(xt, yt, { epochs, batchSize: 8, verbose: 0 });

    const last60 = scaled.slice(-seqLen);
    const input = tf.tensor3d([last60.map(v => [v])], [1, seqLen, 1]);
    const pred = model.predict(input);
    const val = (await pred.data())[0];
    const actualPred = val * std + mean;

    await xt.dispose(); await yt.dispose(); await input.dispose(); await pred.dispose();
    await model.dispose();
    return actualPred;
}

// ====================== Scan ======================
async function runScan() {
    const nowHK = new Date().toLocaleString('zh-HK', { timeZone: 'Asia/Hong_Kong' });
    console.log(`\n${'='*70}`);
    console.log(`🕒 ${nowHK} LSTM 掃描`);
    console.log(`$3,000 target | $200 SL kill-switch | Max 2 micro | MCL 1 contract`);
    console.log(`${'='*70}`);

    for (const [sym, fname] of Object.entries(CSV_FILES)) {
        try {
            process.stdout.write(`  ${sym}... `);
            const data = parseCSV(fname);
            if (data.length < 100) { console.log(`❌ ${data.length} rows`); continue; }

            const closes = data.map(d => d.close);
            const highs = data.map(d => d.high);
            const lows = data.map(d => d.low);
            const n = closes.length;
            const i = n - 1;

            const rsiVal = rsi(closes);
            const ema12 = ema(closes, 12);
            const ema26 = ema(closes, 26);
            const atrVal = atr(highs, lows, closes);
            const volSma = sma(data.map(d => d.volume), 20);

            const swingHigh = highs.map((_, idx) => idx >= 20 ? Math.max(...highs.slice(idx-20, idx)) : null);
            const swingLow = lows.map((_, idx) => idx >= 20 ? Math.min(...lows.slice(idx-20, idx)) : null);
            const fibRange = swingHigh.map((sh, idx) => sh != null && swingLow[idx] != null ? sh - swingLow[idx] : null);

            const fvgBull = lows.map((_, idx) => idx >= 2 && lows[idx-1] > highs[idx-2] ? 1 : 0);
            const fvgBear = highs.map((_, idx) => idx >= 2 && highs[idx-1] < lows[idx-2] ? 1 : 0);

            const cur = closes[i], curAtr = atrVal[i], curEma12 = ema12[i], curEma26 = ema26[i];
            const curSwingH = swingHigh[i], curSwingL = swingLow[i], curFibR = fibRange[i];
            const ote79Bull = curSwingL != null && curFibR != null ? curSwingL + curFibR*0.79 : null;
            const ote79Bear = curSwingH != null && curFibR != null ? curSwingH - curFibR*0.79 : null;
            const inOteBull = curSwingL != null && curFibR > 0
                ? (cur >= curSwingL + curFibR*0.62 && cur <= ote79Bull ? 1 : 0) : 0;
            const inOteBear = curSwingH != null && curFibR > 0
                ? (cur <= curSwingH - curFibR*0.62 && cur >= ote79Bear ? 1 : 0) : 0;

            const pred = await trainAndPredict(closes, 1);
            const mlSignal = pred > cur + curAtr*0.3 ? 1 : (pred < cur - curAtr*0.3 ? -1 : 0);
            const trendBull = curEma12 > curEma26 ? 1 : 0;
            let hybrid = 0;
            if (mlSignal === 1 && trendBull === 1 && (fvgBull[i] === 1 || inOteBull === 1)) hybrid = 1;
            else if (mlSignal === -1 && trendBull === 0 && (fvgBear[i] === 1 || inOteBear === 1)) hybrid = -1;

            const kz = isKillZone(data[i].datetime);
            const pv = POINT_VALUE[sym], contracts = CONTRACTS[sym], prec = PRECISION[sym];
            const estPnl = Math.round((hybrid === 1 ? (pred - cur)*pv*contracts : (cur - pred)*pv*contracts)*100)/100;

            console.log(`Signal:${hybrid===1?'+':hybrid===-1?'-':'0'} Close:${cur.toFixed(prec)} Pred:${pred.toFixed(prec)} KZ:${kz||'None'} Est:$${estPnl}`);

            if (hybrid !== 0 && kz) {
                const slP = 200/(pv*contracts);
                const entry = cur, sl = hybrid===1 ? entry - slP : entry + slP;
                const tp1 = hybrid===1 ? entry + TP1_TICKS[sym]*slP : entry - TP1_TICKS[sym]*slP;
                const tp2 = hybrid===1 ? entry + TP2_TICKS[sym]*slP : entry - TP2_TICKS[sym]*slP;
                console.log(`  🔥 ${kz} KZ 有效！${hybrid===1?'Long':'Short'} @ ${entry.toFixed(prec)}`);
                console.log(`     SL:${sl.toFixed(prec)} TP1:${tp1.toFixed(prec)} TP2:${tp2.toFixed(prec)} | ${contracts}合約`);
            }
        } catch(e) {
            console.log(`❌ ${sym}: ${e.message}`);
        }
    }
    console.log(`\n📊 完成\n`);
}

// ====================== Main ======================
async function main() {
    console.log('🚀 LSTM v4 Node.js 已啟動（每小時一次）');
    console.log('London KZ: 15:00-16:00 HKT | NY KZ: 21:30-22:30 HKT');
    let cnt = 0;
    while (true) {
        cnt++;
        console.log(`\n${'#'.repeat(70)}\n第 ${cnt} 次`);
        await runScan();
        await new Promise(r => setTimeout(r, 3600*1000));
    }
}

main().catch(e => { console.error(e); process.exit(1); });
