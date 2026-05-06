#!/usr/bin/env node
/**
 * LSTM Trading Signals v4 - Node.js FAST Version
 * Optimized for speed (no GPU / tfjs-node needed)
 */
'use strict';

const fs = require('fs');
const tf = require('/usr/local/lib/node_modules/@tensorflow/tfjs');

const POINT_VALUE = { 'MES.F':5, 'MNQ.F':2, 'M2K.F':5, 'MYM.F':0.5, 'M6E.F':12500, 'M6A.F':10000, 'MCL.F':100 };
const CONTRACTS  = { 'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':2, 'M6A.F':2, 'MCL.F':1 };
const PRECISION  = { 'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':4, 'M6A.F':4, 'MCL.F':2 };
const SL_TICKS   = { 'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10 };
const TP1_TICKS  = { 'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10 };
const TP2_TICKS  = { 'MES.F':20, 'MNQ.F':20, 'M2K.F':20, 'MYM.F':20, 'M6E.F':20, 'M6A.F':20, 'MCL.F':20 };
const CSV_FILES  = { 'MES.F':'MES.F.csv','MNQ.F':'MNQ.F.csv','M2K.F':'M2K.F.csv','MYM.F':'MYM.F.csv','M6E.F':'M6E.F.csv','M6A.F':'M6A.F.csv','MCL.F':'MCL.F.csv' };

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
        .map(line => { const v = line.split(','); return v.length >= 6 ? { datetime: v[0], close: +v[4], high: +v[2], low: +v[3] } : null; })
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
    let cur = closes.slice(0, period).reduce((a,b)=>a+b,0)/period;
    for (let i = period-1; i < closes.length; i++) {
        cur = i === period-1 ? closes[i] : closes[i]*k + cur*(1-k);
        out[i] = cur;
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

async function trainAndPredict(closes, highs, lows) {
    const seqLen = 30; // reduced from 60
    const n = closes.length;
    const recentN = Math.min(n, 400); // use last 400 points
    const recent = closes.slice(-recentN);
    const mean = recent.reduce((a,b)=>a+b,0)/recent.length;
    const std = Math.sqrt(recent.reduce((a,b)=>a+(b-mean)*(b-mean),0)/recent.length) || 1;
    const scaled = closes.map(v => (v - mean)/std);

    const trainSize = Math.floor(scaled.length * 0.9);
    const xT=[], yT=[];
    for (let i = seqLen; i < trainSize; i++) xT.push(scaled.slice(i-seqLen,i)), yT.push(scaled[i]);

    // Smaller/faster LSTM model
    const model = tf.sequential();
    model.add(tf.layers.lstm({ units: 24, returnSequences: false, inputShape: [seqLen, 1] }));
    model.add(tf.layers.dense({ units: 12, activation: 'relu' }));
    model.add(tf.layers.dense({ units: 1 }));
    model.compile({ optimizer: tf.train.adam(0.02), loss: 'meanSquaredError' });

    const xt = tf.tensor3d(xT.map(s => s.map(v => [v])), [xT.length, seqLen, 1]);
    const yt = tf.tensor2d(yT, [yT.length, 1]);
    await model.fit(xt, yt, { epochs: 1, batchSize: 4, verbose: 0 });

    const lastSeq = scaled.slice(-seqLen);
    const input = tf.tensor3d([lastSeq.map(v => [v])], [1, seqLen, 1]);
    const pred = model.predict(input);
    const val = (await pred.data())[0];
    const actualPred = val * std + mean;

    await xt.dispose(); await yt.dispose(); await input.dispose(); await pred.dispose(); await model.dispose();
    return actualPred;
}

async function runScan() {
    const nowHK = new Date().toLocaleString('zh-HK', { timeZone: 'Asia/Hong_Kong' });
    console.log(`\n${'='*60}`);
    console.log(`🕒 ${nowHK} LSTM 掃描`);
    console.log(`$3K target | $200 SL | Max 2 micro | MCL 1 contract`);
    console.log(`${'='*60}`);

    for (const [sym, fname] of Object.entries(CSV_FILES)) {
        try {
            process.stdout.write(`  ${sym}... `);
            const data = parseCSV(fname);
            if (data.length < 80) { console.log(`❌ ${data.length} rows`); continue; }

            const closes = data.map(d => d.close);
            const highs = data.map(d => d.high);
            const lows = data.map(d => d.low);
            const n = closes.length;
            const i = n - 1;

            const rsiVal = rsi(closes);
            const ema12 = ema(closes, 12);
            const ema26 = ema(closes, 26);
            const atrVal = atr(highs, lows, closes);

            const fvgBull = lows.map((_, idx) => idx >= 2 && lows[idx-1] > highs[idx-2] ? 1 : 0);
            const fvgBear = highs.map((_, idx) => idx >= 2 && highs[idx-1] < lows[idx-2] ? 1 : 0);

            const swingH = highs.map((_, idx) => idx >= 20 ? Math.max(...highs.slice(idx-20, idx)) : null);
            const swingL = lows.map((_, idx) => idx >= 20 ? Math.min(...lows.slice(idx-20, idx)) : null);
            const fibR = swingH.map((sh, idx) => sh != null && swingL[idx] != null ? sh - swingL[idx] : null);

            const cur = closes[i], curAtr = atrVal[i] || 0, curEma12 = ema12[i] || 0, curEma26 = ema26[i] || 0;
            const curSwingH = swingH[i], curSwingL = swingL[i], curFibR = fibR[i];
            const ote79B = curSwingL != null && curFibR != null ? curSwingL + curFibR*0.79 : null;
            const ote79Be = curSwingH != null && curFibR != null ? curSwingH - curFibR*0.79 : null;
            const inOteBull = curSwingL != null && curFibR > 0 ? (cur >= curSwingL + curFibR*0.62 && cur <= ote79B ? 1 : 0) : 0;
            const inOteBear = curSwingH != null && curFibR > 0 ? (cur <= curSwingH - curFibR*0.62 && cur >= ote79Be ? 1 : 0) : 0;

            const pred = await trainAndPredict(closes, highs, lows);
            const mlSignal = pred > cur + curAtr*0.3 ? 1 : (pred < cur - curAtr*0.3 ? -1 : 0);
            const trendBull = curEma12 > curEma26 ? 1 : 0;
            let hybrid = 0;
            if (mlSignal === 1 && trendBull === 1 && (fvgBull[i] === 1 || inOteBull === 1)) hybrid = 1;
            else if (mlSignal === -1 && trendBull === 0 && (fvgBear[i] === 1 || inOteBear === 1)) hybrid = -1;

            const kz = isKillZone(data[i].datetime);
            const pv = POINT_VALUE[sym], contracts = CONTRACTS[sym], prec = PRECISION[sym];
            const estPnl = Math.round((hybrid === 1 ? (pred - cur)*pv*contracts : (cur - pred)*pv*contracts)*100)/100;

            const sig = hybrid === 1 ? '+' : hybrid === -1 ? '-' : '0';
            console.log(`Signal:${sig} Close:${cur.toFixed(prec)} Pred:${pred.toFixed(prec)} KZ:${kz||'None'} Est:$${estPnl}`);

            if (hybrid !== 0 && kz) {
                const slP = 200/(pv*contracts);
                const entry = cur, sl = hybrid===1 ? entry - slP : entry + slP;
                const tp1 = hybrid===1 ? entry + TP1_TICKS[sym]*slP : entry - TP1_TICKS[sym]*slP;
                const tp2 = hybrid===1 ? entry + TP2_TICKS[sym]*slP : entry - TP2_TICKS[sym]*slP;
                console.log(`  🔥 ${kz} KZ 有效！${hybrid===1?'Long':'Short'} @ ${entry.toFixed(prec)}`);
                console.log(`     SL:${sl.toFixed(prec)} TP1:${tp1.toFixed(prec)} TP2:${tp2.toFixed(prec)} | ${contracts}合約`);
                console.log(`     風險 $200 | TP1:$${TP1_TICKS[sym]*200} TP2:$${TP2_TICKS[sym]*200}`);
            }
        } catch(e) {
            console.log(`❌ ${sym}: ${e.message}`);
        }
    }
    console.log(`\n📊 完成\n`);
}

async function main() {
    console.log('🚀 LSTM v4 (FAST) 已啟動');
    let cnt = 0;
    while (true) {
        cnt++;
        console.log(`\n${'#'.repeat(60)}\n第 ${cnt} 次`);
        await runScan();
        await new Promise(r => setTimeout(r, 3600*1000));
    }
}

main().catch(e => { console.error(e); process.exit(1); });
