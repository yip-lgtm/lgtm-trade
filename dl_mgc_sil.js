const https = require('https');
const fs = require('fs');

const tickers = {
    'MGC.F': 'MGC.F',  // Micro Gold
    'SIL.F': 'SIL.F',  // Micro Silver
};

function dl(ticker, name) {
    return new Promise((resolve) => {
        const url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + ticker + '?interval=15m&range=5d';
        https.get(url, {headers:{'User-Agent':'Mozilla/5.0'}}, (res) => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => {
                try {
                    const j = JSON.parse(d);
                    const q = j.chart.result[0];
                    const ts = q.timestamp;
                    const o = q.indicators.quote[0].open;
                    const h = q.indicators.quote[0].high;
                    const l = q.indicators.quote[0].low;
                    const c = q.indicators.quote[0].close;
                    const v = q.indicators.quote[0].volume;
                    
                    let csv = 'Datetime,open,high,low,close,volume\n';
                    for (let i = 0; i < ts.length; i++) {
                        if (c[i] == null) continue;
                        const dt = new Date(ts[i] * 1000).toISOString().replace('T',' ').slice(0,19);
                        csv += dt + ',' + o[i] + ',' + h[i] + ',' + l[i] + ',' + c[i] + ',' + (v[i]||0) + '\n';
                    }
                    fs.writeFileSync(name, csv);
                    resolve(name + ' saved (' + ts.length + ' bars)');
                } catch(e) { resolve(name + ': ERR ' + e.message); }
            });
        }).on('error', e => resolve(name + ': NET'));
    });
}

async function main() {
    const promises = Object.entries(tickers).map(([name, ticker]) => dl(ticker, name));
    const results = await Promise.all(promises);
    console.log(results.join('\n'));
}

main();
