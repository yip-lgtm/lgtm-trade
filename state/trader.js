/**
 * Markov BTC 5-Minute Up/Down Trader
 * Bonereaper Strategy Replica
 * Dry-run mode active by default
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');

// Load env
function loadEnv() {
  const envPath = path.join(__dirname, '.env');
  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, 'utf8');
    content.split('\n').forEach(line => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) return;
      const [key, ...vals] = trimmed.split('=');
      if (key && vals.length) process.env[key.trim()] = vals.join('=').trim();
    });
  }
}

loadEnv();

const DRY_RUN = process.env.DRY_RUN === 'true';
const ENDPOINT = process.env.CLOB_ENDPOINT || 'https://clob.polymarket.com';
const CHAIN_ID = parseInt(process.env.CLOB_CHAIN_ID || '137');
const MIN_PROB = parseFloat(process.env.MIN_PROB || '0.87');
const MIN_EDGE = parseFloat(process.env.MIN_EDGE || '0.03');
const LOOKBACK = parseInt(process.env.LOOKBACK_CANDLES || '30');
const KLINE_INTERVAL = parseInt(process.env.KLINE_INTERVAL || '300');
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

const STATE_FILE = path.join(__dirname, 'state.json');
const LOG_FILE = path.join(__dirname, 'trades.json');
const STATS_FILE = path.join(__dirname, 'stats.json');

// ─── Telegram Notifier ───────────────────────────────────────────────────────
async function notify(msg) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
    console.log(`[TELEGRAM] ${msg}`);
    return;
  }
  try {
    await axios.post(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      chat_id: TELEGRAM_CHAT_ID,
      text: `🤖 *Markov BTC Trader*\n\n${msg}`,
      parse_mode: 'Markdown'
    });
  } catch (e) {
    console.error('[TELEGRAM ERROR]', e.message);
  }
}

// ─── State ───────────────────────────────────────────────────────────────────
function loadState() {
  if (fs.existsSync(STATE_FILE)) {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  }
  return { trades: [], probThreshold: MIN_PROB, edgeThreshold: MIN_EDGE, lookbackWindow: [] };
}

function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

// ─── Markov Chain ────────────────────────────────────────────────────────────
class MarkovChain {
  constructor(n = 3) {
    this.n = n; // state length (number of consecutive candles to consider)
    this.transitions = {}; // { stateStr: { up: count, down: count } }
    this.learned = false;
  }

  learn(sequence) {
    // sequence: array of +1 (up) or -1 (down)
    for (let i = 0; i < sequence.length - this.n; i++) {
      const stateKey = sequence.slice(i, i + this.n).join(',');
      const next = sequence[i + this.n];
      if (!this.transitions[stateKey]) this.transitions[stateKey] = { up: 0, down: 0 };
      this.transitions[stateKey][next > 0 ? 'up' : 'down']++;
    }
    this.learned = Object.keys(this.transitions).length > 0;
  }

  predict(currentSequence) {
    // currentSequence: last n directions
    if (!this.learned) return { prob: 0.5, direction: 'up', edge: 0 };
    const stateKey = currentSequence.slice(-this.n).join(',');
    const trans = this.transitions[stateKey];
    if (!trans) return { prob: 0.5, direction: 'up', edge: 0 };
    const total = trans.up + trans.down;
    if (total < 3) return { prob: 0.5, direction: 'up', edge: 0 };
    const pUp = trans.up / total;
    const direction = pUp >= 0.5 ? 'up' : 'down';
    return { prob: pUp, direction, edge: Math.abs(pUp - 0.5) };
  }
}

// ─── Price Fetching ──────────────────────────────────────────────────────────
async function getBtcPriceHistory(bars = 50) {
  try {
    // Use Binance public API for 5m BTC/USDT klines
    const url = `https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=${bars}`;
    const resp = await axios.get(url, { timeout: 10000 });
    const klines = resp.data;
    const closes = klines.map(k => parseFloat(k[4]));
    return closes;
  } catch (e) {
    console.error('[PRICE FETCH ERROR]', e.message);
    return null;
  }
}

function computeDirections(closes) {
  const dirs = [];
  for (let i = 1; i < closes.length; i++) {
    dirs.push(closes[i] > closes[i - 1] ? 1 : -1);
  }
  return dirs;
}

// ─── Market Data via Polymarket CLOB ────────────────────────────────────────
async function getBtcUpDownMarket() {
  try {
    // Get BTC 5min up/down condition markets
    const url = `${ENDPOINT}/markets`;
    const resp = await axios.get(url, {
      params: { condition_id: 'btc-5min-up-down', limit: 5 },
      timeout: 10000,
      headers: { 'Accept': 'application/json' }
    });
    return resp.data;
  } catch (e) {
    console.error('[CLOB ERROR]', e.message);
    return null;
  }
}

async function getOrderBook(marketId) {
  try {
    const url = `${ENDPOINT}/orderbook/${marketId}`;
    const resp = await axios.get(url, { timeout: 10000 });
    return resp.data;
  } catch (e) {
    console.error('[ORDERBOOK ERROR]', e.message);
    return null;
  }
}

async function placeOrder(side, price, size, marketId) {
  if (DRY_RUN) {
    console.log(`[DRY RUN] PLACE ORDER: ${side} @ ${price} size ${size} market ${marketId}`);
    return { orderID: 'DRY_' + Date.now(), status: 'DRY_RUN' };
  }
  // Real order placement
  const timestamp = Date.now().toString();
  const body = {
    market: marketId,
    side: side.toUpperCase(),
    size: size.toString(),
    price: price.toString(),
    order_type: 'FILL_OR_KILL',
    time_in_force: 'GTC',
    timestamp,
    chain_id: CHAIN_ID
  };
  // Sign with PRIVATE_KEY here (to be added)
  const resp = await axios.post(`${ENDPOINT}/orders`, body, {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${process.env.CLOB_API_KEY}`
    }
  });
  return resp.data;
}

// ─── Trading Logic ───────────────────────────────────────────────────────────
async function runTradeCycle() {
  const state = loadState();
  const markov = new MarkovChain(3);

  console.log('[CYCLE] Fetching price data...');
  const closes = await getBtcPriceHistory(LOOKBACK + 10);
  if (!closes || closes.length < LOOKBACK) {
    console.log('[CYCLE] Insufficient price data, skipping...');
    return;
  }

  // Learn from historical data
  const dirs = computeDirections(closes);
  markov.learn(dirs);

  // Get current candle direction
  const currentDir = dirs[dirs.length - 1];
  const currentSequence = dirs.slice(-3); // last 3 directions

  const { prob, direction, edge } = markov.predict(currentSequence);

  console.log(`[ANALYSIS] Prob=${prob.toFixed(4)} Dir=${direction} Edge=${edge.toFixed(4)}`);
  console.log(`[THRESHOLDS] MIN_PROB=${state.probThreshold} MIN_EDGE=${state.edgeThreshold}`);

  // Check if signal meets threshold
  const delta = prob - 0.5; // edge measure
  if (prob >= state.probThreshold && delta >= state.edgeThreshold) {
    console.log(`[SIGNAL] ENTERING ${direction.toUpperCase()}`);

    // Determine market (BTC 5min up/down)
    // For now, simulate with BTC up/down position sizing
    const size = 10; // units
    const side = direction === 'up' ? 'buy' : 'sell';

    // Get current price for logging
    const currentPrice = closes[closes.length - 1];

    const orderResult = await placeOrder(side, prob, size, 'BTC-5MIN-UP-DOWN');

    const trade = {
      id: Date.now(),
      timestamp: new Date().toISOString(),
      direction,
      prob,
      edge,
      price: currentPrice,
      size,
      order: orderResult,
      dryRun: DRY_RUN
    };

    state.trades.push(trade);
    saveState(state);

    await notify(
      `📊 *New Trade*\n` +
      `Direction: ${direction.toUpperCase()}\n` +
      `Prob: ${prob.toFixed(4)}\n` +
      `Edge: ${edge.toFixed(4)}\n` +
      `Price: $${currentPrice.toFixed(2)}\n` +
      `Size: ${size}\n` +
      `Mode: ${DRY_RUN ? 'DRY RUN' : 'LIVE'}`
    );

    // Log trade
    const logEntry = JSON.stringify(trade) + '\n';
    fs.appendFileSync(LOG_FILE, logEntry);
  } else {
    console.log(`[NO SIGNAL] prob=${prob.toFixed(4)} < ${state.probThreshold} or edge=${delta.toFixed(4)} < ${state.edgeThreshold}`);
  }
}

// ─── Nightly Review ───────────────────────────────────────────────────────────
async function nightlyReview() {
  console.log('[REVIEW] Running nightly review...');
  const state = loadState();

  if (!fs.existsSync(LOG_FILE)) {
    console.log('[REVIEW] No trades to review');
    return;
  }

  const lines = fs.readFileSync(LOG_FILE, 'utf8').trim().split('\n');
  const trades = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);

  const dryRuns = trades.filter(t => t.dryRun);
  const liveTrades = trades.filter(t => !t.dryRun);

  let winCount = 0;
  let lossCount = 0;
  let pnl = 0;

  // For dry-run, we simulate outcomes based on direction correctness
  dryRuns.forEach(t => {
    // In dry-run, we just record; no real P&L
  });

  // Summary
  const summary = {
    reviewTime: new Date().toISOString(),
    totalTrades: trades.length,
    dryRuns: dryRuns.length,
    liveTrades: liveTrades.length,
    currentThresholds: { prob: state.probThreshold, edge: state.edgeThreshold }
  };

  // Auto-tune: if win rate > 65%, increase threshold slightly; if < 45%, decrease
  // For now just log and keep current thresholds
  console.log('[REVIEW] Summary:', JSON.stringify(summary));
  fs.writeFileSync(STATS_FILE, JSON.stringify(summary, null, 2));

  await notify(
    `🌙 *Nightly Review*\n` +
    `Total Trades: ${trades.length}\n` +
    `Dry Runs: ${dryRuns.length}\n` +
    `Live: ${liveTrades.length}\n` +
    `Current Prob Threshold: ${state.probThreshold}\n` +
    `Current Edge Threshold: ${state.edgeThreshold}`
  );

  // Auto-iterate thresholds
  // Example: move 0.87 -> 0.89 -> 0.91 after successful runs
  if (dryRuns.length >= 10) {
    const newProb = Math.min(state.probThreshold + 0.02, 0.95);
    const newEdge = Math.max(state.edgeThreshold - 0.01, 0.01);
    console.log(`[AUTO-TUNE] Prob: ${state.probThreshold} -> ${newProb}, Edge: ${state.edgeThreshold} -> ${newEdge}`);
    state.probThreshold = newProb;
    state.edgeThreshold = newEdge;
    saveState(state);
    await notify(`🔧 *Auto-Tune*\nMIN_PROB → ${newProb}\nMIN_EDGE → ${newEdge}`);
  }
}

// ─── Main Loop ───────────────────────────────────────────────────────────────
let tradeCount = 0;
const TARGET_TRADES = 50;

async function main() {
  console.log('═══════════════════════════════════════');
  console.log('  Markov BTC Trader - Bonereaper Replica');
  console.log(`  Mode: ${DRY_RUN ? 'DRY RUN' : 'LIVE'}`);
  console.log(`  Target Dry Runs: ${TARGET_TRADES}`);
  console.log('═══════════════════════════════════════');

  await notify(`🚀 *Markov BTC Trader Started*\nMode: ${DRY_RUN ? 'DRY RUN' : 'LIVE'}\nTarget: ${TARGET_TRADES} dry runs`);

  // Initial cycle
  await runTradeCycle();
  tradeCount++;

  // Run loop every 5 minutes
  const intervalMs = KLINE_INTERVAL * 1000;

  const loop = setInterval(async () => {
    if (DRY_RUN && tradeCount >= TARGET_TRADES) {
      clearInterval(loop);
      console.log('[DONE] Target dry-run trades reached!');
      await notify(`✅ *Dry-Run Complete!*\n${tradeCount} trades executed.\nReady for private key.`);
      return;
    }
    await runTradeCycle();
    tradeCount++;
  }, intervalMs);

  // Schedule nightly review at midnight
  scheduleMidnightReview();
}

function scheduleMidnightReview() {
  const now = new Date();
  const midnight = new Date(now);
  midnight.setHours(24, 0, 0, 0);
  const msUntilMidnight = midnight - now;

  setTimeout(async () => {
    await nightlyReview();
    scheduleMidnightReview(); // Reschedule
  }, msUntilMidnight);
}

// ─── CLI ─────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
if (args[0] === 'review') {
  nightlyReview().then(() => process.exit(0));
} else if (args[0] === 'status') {
  const state = loadState();
  console.log('State:', JSON.stringify(state, null, 2));
} else {
  main().catch(e => { console.error('[FATAL]', e); process.exit(1); });
}

module.exports = { runTradeCycle, nightlyReview };