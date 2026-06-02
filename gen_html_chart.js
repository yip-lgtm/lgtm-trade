#!/usr/bin/env node
'use strict';
const fs = require('fs');
const SYM = process.argv[2] || 'MCL.F';
const OUT_FILE = `trade_chart_${SYM.replace('.','')}.html`;

const prices = fs.readFileSync(`${SYM}.csv`, 'utf8').trim().split('\n').slice(1).map(l => {
    const [dt,o,h,l_,c] = l.split(',');
    return {datetime:dt,open:+o,high:+h,low:+l_,close:+c};
});
const trades = fs.readFileSync('backtest_results.csv', 'utf8').trim().split('\n').slice(1).map(l => {
    const [date,symbol,direction,entry,exit,pnl,kz] = l.split(',');
    return {date,symbol,direction,entry:+entry,exit:+exit,pnl:+pnl,kz:kz||''};
}).filter(t => t.symbol === SYM);

const wins = trades.filter(t => t.pnl > 0).length;
const losses = trades.filter(t => t.pnl < 0).length;
const totalPnL = trades.reduce((a,t) => a + t.pnl, 0);
const wr = (wins / trades.length * 100).toFixed(1);
const pJSON = JSON.stringify(prices.slice(-400));
const tJSON = JSON.stringify(trades);

const html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ICT Chart - ${SYM}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{font-family:'Segoe UI',Arial,sans-serif;margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#e6edf3;padding:20px;max-width:1100px;margin:0 auto}
h1{font-size:1.3rem;margin-bottom:10px}
.stats{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.s{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 14px;flex:1;min-width:110px}
.s .l{color:#8b949e;font-size:0.68rem;text-transform:uppercase}
.s .v{font-size:1.15rem;font-weight:bold;margin-top:2px}
.pos{color:#3fb950}.neg{color:#f85149}.neu{color:#e6edf3}
canvas{max-width:100%}
select{background:#161b22;border:1px solid #30363d;color:#e6edf3;padding:5px 10px;border-radius:5px;font-size:0.8rem}
.item{display:flex;align-items:center;gap:10px;padding:6px 10px;border-bottom:1px solid #21262d;font-size:0.8rem}
.item:hover{background:#1c2128}
.n{color:#484f58;min-width:22px;text-align:right}
.dir{font-weight:bold;min-width:40px}
.lon{color:#58a6ff}.sho{color:#f97583}
.d{color:#8b949e;font-size:0.75rem}
.px{color:#6e7681;font-size:0.72rem}
.pnl{margin-left:auto;font-weight:bold;min-width:50px;text-align:right}
.win{color:#3fb950}.los{color:#f85149}
.kz{background:rgba(255,200,0,0.12);color:#ffc800;border-radius:3px;padding:1px 5px;font-size:0.65rem}
.legend{display:flex;gap:12px;margin-top:10px;font-size:0.72rem;color:#8b949e;flex-wrap:wrap}
.legend-item{display:flex;align-items:center;gap:4px}
.legend-line{width:12px;height:3px;border-radius:2px}
</style></head><body>
<h1>ICT Chart - ${SYM}</h1>
<div class="stats">
<div class="s"><div class="l">Total PnL</div><div class="v ${totalPnL>=0?'pos':'neg'}">$${totalPnL.toLocaleString()}</div></div>
<div class="s"><div class="l">Win Rate</div><div class="v ${wr>=50?'pos':'neg'}">${wr}%</div></div>
<div class="s"><div class="l">Trades</div><div class="v neu">${trades.length}</div></div>
<div class="s"><div class="l">W/L</div><div class="v ${wins>=losses?'pos':'neg'}">${wins}/${losses}</div></div>
</div>
<select id="flt" onchange="render()"><option value="all">All</option><option value="wins">Wins</option><option value="losses">Losses</option><option value="kz">Kill Zone</option></select>
<div style="height:10px"></div>
<div style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px;height:380px">
<canvas id="chart"></canvas>
</div>
<div id="list" style="margin-top:10px"></div>
<div class="legend">
<div class="legend-item"><div class="legend-line" style="background:#26a69a"></div>Bullish</div>
<div class="legend-item"><div class="legend-line" style="background:#ef5350"></div>Bearish</div>
<div class="legend-item"><div class="legend-line" style="background:#58a6ff"></div>Long Entry</div>
<div class="legend-item"><div class="legend-line" style="background:#f97583"></div>Short Entry</div>
<div class="legend-item"><div class="legend-line" style="background:#3fb950"></div>TP (Win)</div>
<div class="legend-item"><div class="legend-line" style="background:#f85149"></div>SL (Loss)</div>
</div>
<script>
const prices=${pJSON};
const trades=${tJSON};
let chart;
const flt=document.getElementById('flt');
function getF(){const v=flt.value;if(v==='wins')return trades.filter(t=>t.pnl>0);if(v==='losses')return trades.filter(t=>t.pnl<0);if(v==='kz')return trades.filter(t=>t.kz);return trades;}
function render(){
  const ft=getF();
  const list=document.getElementById('list');
  let html='';
  ft.slice(0,25).forEach((t,i)=>{
    const cls=t.direction==='Long'?'lon':'sho';
    const pcl=t.pnl>0?'win':'los';
    const kz=t.kz?'<span class="kz">'+t.kz+'</span>':'';
    html+='<div class="item"><span class="n">'+(i+1)+'.</span><span class="dir '+cls+'">'+t.direction+'</span><span class="d">'+t.date.split(' ')[0]+'</span><span class="px">E:'+t.entry.toFixed(4)+'</span><span class="px">X:'+t.exit.toFixed(4)+'</span>'+kz+'<span class="pnl '+pcl+'">$'+t.pnl.toFixed(0)+'</span></div>';
  });
  if(ft.length>25)html+='<div style="color:#484f58;font-size:0.72rem;padding:6px">…'+(ft.length-25)+' more</div>';
  list.innerHTML=html;
  const rec=prices.slice(-Math.min(prices.length,350));
  const labels=rec.map(p=>p.datetime.split(' ')[0]+' '+p.datetime.split(' ')[1].substring(0,5));
  const o=rec.map(p=>p.open),h=rec.map(p=>p.high),l=rec.map(p=>p.low),c=rec.map(p=>p.close);
  const cols=c.map((v,i)=>v>=o[i]?'#26a69a':'#ef5350');
  if(chart)chart.destroy();
  chart=new Chart(document.getElementById('chart'),{type:'candlestick',data:{labels,datasets:[{label:'Price',data:o.map((v,i)=>({open:v,high:h[i],low:l[i],close:c[i]})),color:cols.map(v=>v+'cc'),borderColor:cols,borderWidth:1}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>{const d=ctx.raw;return'O:'+d.open.toFixed(2)+' H:'+d.high.toFixed(2)+' L:'+d.low.toFixed(2)+' C:'+d.close.toFixed(2)}}}}},scales:{x:{ticks:{maxTicksLimit:10,color:'#6e7681',font:{size:9}},grid:{color:'#21262d'}},y:{ticks:{color:'#6e7681',font:{size:9}},grid:{color:'#21262d'}}}}});
  setTimeout(()=>{
    const ctx=document.getElementById('chart').getContext('2d');
    ft.forEach(t=>{
      const idx=rec.findIndex(p=>p.datetime.startsWith(t.date.split(' ')[0]));
      if(idx<0)return;
      const x=chart.scales.x.getPixelForValue(idx);
      const y=chart.scales.y.getPixelForValue(t.entry);
      ctx.fillStyle=t.pnl>0?'#3fb950':'#f85149';
      ctx.font='bold 12px Arial';
      ctx.fillText(t.direction==='Long'?'L':'S',x-3,y+4);
    });
  },300);
}
render();
</script></body></html>`;

fs.writeFileSync(OUT_FILE, html);
console.log('Saved: '+OUT_FILE);
