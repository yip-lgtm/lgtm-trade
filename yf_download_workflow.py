#!/usr/bin/env python3
"""
Yahoo Finance Data Downloader - 分批下載 + Rate Limit 處理
每個 symbol 下載完後等待 60 秒，避免被 block

Usage:
 python3 yf_download_workflow.py
"""

import yfinance as yf
import pandas as pd
import os
import subprocess
from datetime import datetime
import time

# ====================== Config ======================
REPO_PATH = '/home/node/lgtm-trade'
GITHUB_REMOTE = 'https://github.com/yip-lgtm/lgtm-trade.git'

# 分批下載 - 每批 之後停 60 秒
SYMBOLS = {
    'MES.F': 'MES=F',
    'MNQ.F': 'MNQ=F',
    'M2K.F': 'M2K=F',
    'M6E.F': 'M6E=F',
    'M6A.F': 'M6A=F',
    'MCL.F': 'MCL=F',
    'MBT.F': 'BTC=F',
    'MET.F': 'ETH=F',
    'SIL.F': 'SIL=F',
    'MGC.F': 'GC=F',
}

BATCH_DELAY = 60  # 每批後等 60 秒
REQUEST_DELAY = 10  # 每個 request 前等 10 秒

# ====================== Functions ======================
def download_symbol(symbol, yf_ticker, days=60):
    """下載 15min 數據"""
    print(f'  Downloading {yf_ticker}...')

    time.sleep(REQUEST_DELAY)

    try:
        tk = yf.Ticker(yf_ticker)
        df = tk.history(period=f'{days}d', interval='15m')

        if df.empty or len(df) < 10:
            print(f'  ⚠️ {yf_ticker}: No data returned')
            return None

        df = df.reset_index()

        fname = f"{symbol}.csv"
        fpath = os.path.join(REPO_PATH, fname)
        df.to_csv(fpath, index=False)

        rows = len(df)
        last_date = df['Datetime'].iloc[-1]
        print(f'  ✅ {symbol}.csv: {rows} rows, last={last_date}')
        return fname

    except Exception as e:
        err = str(e)
        if '429' in err or 'rate' in err.lower():
            print(f'  ⏳ {yf_ticker}: Rate limited - waiting longer...')
            time.sleep(BATCH_DELAY * 2)
            return 'retry'
        else:
            print(f'  ❌ {symbol}: {err}')
            return None


def setup_repo():
    """Clone or update repo"""
    if os.path.exists(REPO_PATH):
        print(f'📁 Repo exists at {REPO_PATH}')
        try:
            subprocess.run(['git', 'pull', 'origin', 'main'], cwd=REPO_PATH, check=True, capture_output=True)
            print('✅ Pulled latest')
        except:
            print('⚠️ Could not pull')
    else:
        print(f'📥 Cloning {GITHUB_REMOTE}...')
        try:
            subprocess.run(['git', 'clone', GITHUB_REMOTE, REPO_PATH], check=True, capture_output=True)
            print('✅ Cloned')
        except Exception as e:
            print(f'❌ Clone failed: {e}')
            return False
    return True


def git_push(message=None):
    """Git add + commit + push"""
    if message is None:
        message = f"Update futures data {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    try:
        subprocess.run(['git', 'add', '*.csv'], cwd=REPO_PATH, check=True, capture_output=True)
        result = subprocess.run(['git', 'status', '--porcelain'], cwd=REPO_PATH, capture_output=True, text=True)
        if not result.stdout.strip():
            print('📝 No changes to commit')
            return False

        subprocess.run(['git', 'commit', '-m', message], cwd=REPO_PATH, check=True, capture_output=True)
        print(f'✅ Committed: {message}')

        result = subprocess.run(['git', 'push', 'origin', 'main'], cwd=REPO_PATH, capture_output=True, text=True)
        if result.returncode == 0:
            print('✅ Pushed to GitHub')
            return True
        else:
            print(f'⚠️ Push failed')
            return False
    except Exception as e:
        print(f'❌ Git error: {e}')
        return False


def main():
    print('='*50)
    print('Yahoo Finance 分批下載 (Rate Limit 處理)')
    print('='*50)

    if not setup_repo():
        print('❌ Repo setup failed')
        return

    os.chdir(REPO_PATH)

    print('\n📥 Downloading futures data...')
    print(f'每個 symbol 後等待 {REQUEST_DELAY} 秒')
    print(f'每批後等待 {BATCH_DELAY} 秒\n')

    downloaded = []
    failed = []
    total = len(SYMBOLS)

    for idx, (sym, yf_ticker) in enumerate(SYMBOLS.items(), 1):
        print(f'[{idx}/{total}] ', end='')
        result = download_symbol(sym, yf_ticker)

        if result == 'retry':
            result = download_symbol(sym, yf_ticker)

        if result and result != 'retry':
            downloaded.append(result)
        elif result is None:
            failed.append(sym)

        if idx % 3 == 0 and idx < total:
            print(f'\n⏳ Batch done, waiting {BATCH_DELAY}s...')
            time.sleep(BATCH_DELAY)

    print(f'\n📊 Downloaded: {len(downloaded)} symbols')
    if failed:
        print(f'❌ Failed: {failed}')

    if downloaded:
        print('\n🚀 Pushing to GitHub...')
        if git_push():
            print('\n✅ Workflow complete!')

    print('\n下一步: Server 可以 git pull 更新後的數據!')


if __name__ == '__main__':
    main()