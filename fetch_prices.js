#!/usr/bin/env node
const https = require('https');
const fs = require('fs');

const yahoo_map = {
    'MES.F':'MES=F','MNQ.F':'MNQ=F','M2K.F':'M2K=F','M6E.F':'M6E=F',
    'M6A.F':'M6A=F','MCL.F':'MCL=F','MBT.F':'MBT=F','MET.F':'MET=F',
    'SIL.F':'SIL=F','MGC.F':'MGC=F'
};

function fetch(ticker) {
    return new Promise((resolve) => {
        const url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + ticker + '?interval=15m&range=1d';
        https.get(url, {headers:{'User-Agent':'Mozilla/5.0'}}, (res) => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => {
                try {
                    const j = JSON.parse(d);
                    const q = j.chart.result[0];
                    const closes = q.indicators.quote[0].close.filter(x => x != null);
                    resolve({ticker, price: closes.pop()});
                } catch(e) { resolve({ticker, price: null}); }
            });
        }).on('error', () => resolve({ticker, price: null}));
    });
}

async function main() {
    const tickers = Object.values(yahoo_map);
    const results = await Promise.all(tickers.map(fetch));
    const prices = {};
    results.forEach(r => { prices[r.ticker] = r.price; });
    console.log(JSON.stringify(prices));
}

main();
