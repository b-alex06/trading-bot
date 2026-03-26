#!/usr/bin/env python3
"""
PRO SIGNAL BOT — Python AI Engine
===================================
✅ Telegram chat (stel vragen aan de bot)
✅ Chart afbeeldingen met alle zones aangeduid
✅ Weekrapport elke vrijdag 20:00
✅ Dagelijkse macro briefing elke ochtend 7:00
✅ AI zelf-lerend systeem
✅ Backtest engine
✅ Fundamentele analyse (nieuws, economic calendar)
"""

import os
import json
import sqlite3
import asyncio
import schedule
import time
import threading
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

import yfinance as yf
import requests
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ================================================================
# CONFIGURATIE — VUL DIT IN
# ================================================================
TELEGRAM_TOKEN   = "8279417890:AAEJbzidoCwH8UDlu7_B3bpAyDNA9d8rzpg"
TELEGRAM_CHAT_ID = "5821649428"
NEWS_API_KEY     = "1c9882779b344175bf8776ed76d16ef1"

# ================================================================
# PAIRS — type per pair
# ================================================================
PAIRS = {
    # Forex
    "EURUSD": "forex", "GBPUSD": "forex", "USDJPY": "forex",
    "USDCAD": "forex", "AUDUSD": "forex", "NZDUSD": "forex",
    "USDCHF": "forex", "GBPJPY": "forex", "GBPAUD": "forex",
    "GBPCAD": "forex", "GBPCHF": "forex", "GBPNZD": "forex",
    "EURGBP": "forex", "EURJPY": "forex", "EURAUD": "forex",
    "EURCAD": "forex", "EURCHF": "forex",
    # Crypto (Binance symbolen)
    "BTCUSD": "crypto", "ETHUSD": "crypto", "SOLUSD": "crypto",
    "BNBUSD": "crypto", "XRPUSD": "crypto",
    # Commodities & Indices via yfinance als fallback
    "XAUUSD": "commodity", "XAGUSD": "commodity",
    "US30":   "index",     "NAS100": "index", "SPX500": "index"
}

# Binance symbolen mapping
BINANCE_SYMBOLS = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
    "BNBUSD": "BNBUSDT", "XRPUSD": "XRPUSDT"
}

# Yahoo Finance fallback
YAHOO_SYMBOLS = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    "US30": "^DJI", "NAS100": "^NDX", "SPX500": "^GSPC"
}

# ================================================================
# DATA FETCH — MULTI SOURCE
# ================================================================
def fetch_data(pair: str) -> pd.DataFrame:
    """Haalt data op via beste beschikbare bron"""
    pair_type = PAIRS.get(pair, "forex")
    
    # CRYPTO → Binance API (werkt altijd, ook op cloud)
    if pair_type == "crypto":
        return fetch_binance(pair)
    
    # FOREX → Frankfurter API (gratis, geen key)
    elif pair_type == "forex":
        df = fetch_forex_free(pair)
        if df is not None and len(df) >= 50:
            return df
        # Fallback naar yfinance
        return fetch_yfinance(pair + "=X")
    
    # COMMODITIES & INDICES → yfinance
    else:
        symbol = YAHOO_SYMBOLS.get(pair, pair)
        return fetch_yfinance(symbol)

def fetch_binance(pair: str) -> pd.DataFrame:
    """Haalt crypto data op via Binance API — altijd gratis"""
    try:
        symbol   = BINANCE_SYMBOLS.get(pair, pair + "USDT")
        url      = f"https://api.binance.com/api/v3/klines"
        params   = {"symbol": symbol, "interval": "4h", "limit": 500}
        resp     = requests.get(url, params=params, timeout=10)
        data     = resp.json()
        
        if not data or isinstance(data, dict):
            return pd.DataFrame()
        
        df = pd.DataFrame(data, columns=[
            'timestamp','Open','High','Low','Close','Volume',
            'close_time','quote_vol','trades','taker_buy_base',
            'taker_buy_quote','ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        for col in ['Open','High','Low','Close','Volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"Binance fout {pair}: {e}")
        return pd.DataFrame()

def fetch_forex_free(pair: str) -> pd.DataFrame:
    """Haalt forex data op via gratis API"""
    try:
        # Gebruik yfinance met kortere periode als eerste poging
        base   = pair[:3]
        quote  = pair[3:]
        symbol = f"{base}{quote}=X"
        ticker = yf.Ticker(symbol)
        df     = ticker.history(period="3mo", interval="4h")
        if len(df) >= 50:
            return df
        return None
    except:
        return None

def fetch_yfinance(symbol: str) -> pd.DataFrame:
    """Yahoo Finance fallback"""
    try:
        ticker = yf.Ticker(symbol)
        df     = ticker.history(period="6mo", interval="4h")
        return df
    except:
        return pd.DataFrame()

# ================================================================
# DATABASE SETUP
# ================================================================
def init_database():
    conn = sqlite3.connect('trading_bot.db')
    c = conn.cursor()
    
    # Trades tabel
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT,
        pair        TEXT,
        direction   TEXT,
        entry       REAL,
        sl          REAL,
        tp1         REAL,
        tp2         REAL,
        tp3         REAL,
        score       INTEGER,
        rr_planned  REAL,
        rr_actual   REAL,
        result      TEXT,
        pnl_pct     REAL,
        confluence  TEXT,
        session     TEXT,
        notes       TEXT
    )''')
    
    # Confluence gewichten tabel (AI leert hieruit)
    c.execute('''CREATE TABLE IF NOT EXISTS confluence_weights (
        factor      TEXT PRIMARY KEY,
        weight      REAL DEFAULT 1.0,
        wins        INTEGER DEFAULT 0,
        losses      INTEGER DEFAULT 0,
        last_updated TEXT
    )''')
    
    # Initialiseer gewichten als nog niet aanwezig
    factors = [
        'htf_bias', 'market_structure', 'zone_strength', 'fibonacci',
        'liquidity_sweep', 'rsi_divergence', 'volume', 'session',
        'candlestick', 'dxy_correlation', 'ema_trend'
    ]
    for f in factors:
        c.execute('INSERT OR IGNORE INTO confluence_weights (factor, weight) VALUES (?, 1.0)', (f,))
    
    conn.commit()
    conn.close()
    print("✅ Database klaar")

# ================================================================
# TECHNISCHE ANALYSE ENGINE
# ================================================================
class TechnicalAnalysis:
    
    def __init__(self, pair: str, df: pd.DataFrame):
        self.pair = pair
        self.df   = df
        self.atr  = self._calculate_atr()
    
    def _calculate_atr(self, period=14) -> float:
        high  = self.df['High']
        low   = self.df['Low']
        close = self.df['Close']
        tr    = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean().iloc[-1]
    
    def check_htf_bias(self) -> tuple[bool, bool]:
        """Weekly trend bias"""
        close = self.df['Close']
        ema20 = close.ewm(span=20).mean()
        ema50 = close.ewm(span=50).mean()
        bull  = close.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]
        bear  = close.iloc[-1] < ema20.iloc[-1] < ema50.iloc[-1]
        return bull, bear
    
    def check_market_structure(self) -> tuple[bool, bool]:
        """BOS / CHoCH detectie"""
        close    = self.df['Close']
        high     = self.df['High']
        low      = self.df['Low']
        prev_high = high.iloc[-20:-1].max()
        prev_low  = low.iloc[-20:-1].min()
        bull_bos  = close.iloc[-1] > prev_high
        bear_bos  = close.iloc[-1] < prev_low
        return bull_bos, bear_bos
    
    def check_institutional_zone(self) -> tuple[int, int, str, str]:
        """OB + FVG + S&D gecombineerd — geeft 0, 1 of 2 punten"""
        close = self.df['Close']
        open_ = self.df['Open']
        high  = self.df['High']
        low   = self.df['Low']
        price = close.iloc[-1]
        
        bull_count = 0
        bear_count = 0
        
        # Supply & Demand check
        for i in range(-20, -3):
            base   = abs(close.iloc[i] - open_.iloc[i])
            strong = abs(close.iloc[i-1] - open_.iloc[i-1])
            if base < self.atr * 0.5:
                if (close.iloc[i-1] > open_.iloc[i-1] and strong > self.atr and
                        open_.iloc[i+1] > close.iloc[i+1]):
                    if low.iloc[i] * 0.999 <= price <= high.iloc[i] * 1.001:
                        bull_count += 1
                        break
                if (open_.iloc[i-1] > close.iloc[i-1] and strong > self.atr and
                        close.iloc[i+1] > open_.iloc[i+1]):
                    if low.iloc[i] * 0.999 <= price <= high.iloc[i] * 1.001:
                        bear_count += 1
                        break
        
        # Orderblock check
        for i in range(-10, -2):
            if (open_.iloc[i] > close.iloc[i] and
                    close.iloc[i+1] > open_.iloc[i+1] and
                    (close.iloc[i+1] - open_.iloc[i+1]) > self.atr * 0.8):
                if low.iloc[i] <= price <= high.iloc[i]:
                    bull_count += 1
                    break
            if (close.iloc[i] > open_.iloc[i] and
                    open_.iloc[i+1] > close.iloc[i+1] and
                    (open_.iloc[i+1] - close.iloc[i+1]) > self.atr * 0.8):
                if low.iloc[i] <= price <= high.iloc[i]:
                    bear_count += 1
                    break
        
        # FVG check
        for i in range(-8, -2):
            bull_fvg = low.iloc[i] > high.iloc[i-2]
            bear_fvg = high.iloc[i] < low.iloc[i-2]
            if bull_fvg and high.iloc[i-2] <= price <= low.iloc[i]:
                bull_count += 1
                break
            if bear_fvg and high.iloc[i] <= price <= low.iloc[i-2]:
                bear_count += 1
                break
        
        bull_score = 2 if bull_count >= 3 else (1 if bull_count >= 2 else 0)
        bear_score = 2 if bear_count >= 3 else (1 if bear_count >= 2 else 0)
        bull_label = f"Sterk (OB+FVG+S&D) 💎" if bull_count==3 else f"Gemiddeld ({bull_count}/3)" if bull_count==2 else f"Zwak ({bull_count}/3)"
        bear_label = f"Sterk (OB+FVG+S&D) 💎" if bear_count==3 else f"Gemiddeld ({bear_count}/3)" if bear_count==2 else f"Zwak ({bear_count}/3)"
        return bull_score, bear_score, bull_label, bear_label
    
    def check_fibonacci(self) -> tuple[bool, bool]:
        high    = self.df['High'].iloc[-50:].max()
        low     = self.df['Low'].iloc[-50:].min()
        price   = self.df['Close'].iloc[-1]
        rng     = high - low
        buff    = rng * 0.02
        fib618b = high - rng * 0.618
        fib705b = high - rng * 0.705
        fib618s = low  + rng * 0.618
        fib705s = low  + rng * 0.705
        at_bull = min(fib618b,fib705b)-buff <= price <= max(fib618b,fib705b)+buff
        at_bear = min(fib618s,fib705s)-buff <= price <= max(fib618s,fib705s)+buff
        return at_bull, at_bear
    
    def check_liquidity_sweep(self) -> tuple[bool, bool]:
        high  = self.df['High']
        low   = self.df['Low']
        close = self.df['Close']
        open_ = self.df['Open']
        prev_high = high.iloc[-10:-2].max()
        prev_low  = low.iloc[-10:-2].min()
        bull = (low.iloc[-2]  < prev_low  and close.iloc[-2] > prev_low  and
                (open_.iloc[-2] - low.iloc[-2])  > self.atr * 0.3)
        bear = (high.iloc[-2] > prev_high and close.iloc[-2] < prev_high and
                (high.iloc[-2] - open_.iloc[-2]) > self.atr * 0.3)
        return bull, bear
    
    def check_rsi_divergence(self) -> tuple[bool, bool]:
        close   = self.df['Close']
        delta   = close.diff()
        gain    = delta.clip(lower=0).rolling(14).mean()
        loss    = (-delta.clip(upper=0)).rolling(14).mean()
        rs      = gain / loss
        rsi     = 100 - (100 / (1 + rs))
        price_ll = close.iloc[-1] < close.iloc[-10:-1].min()
        rsi_hl   = rsi.iloc[-1]  > rsi.iloc[-10:-1].min()
        bull_div = price_ll and rsi_hl and rsi.iloc[-1] < 50
        price_hh = close.iloc[-1] > close.iloc[-10:-1].max()
        rsi_lh   = rsi.iloc[-1]  < rsi.iloc[-10:-1].max()
        bear_div = price_hh and rsi_lh and rsi.iloc[-1] > 50
        return bull_div, bear_div
    
    def check_volume(self) -> bool:
        vol     = self.df['Volume']
        avg_vol = vol.iloc[-20:-1].mean()
        return vol.iloc[-1] > avg_vol * 1.3
    
    def check_session(self) -> tuple[bool, str]:
        now   = datetime.utcnow()
        hour  = now.hour
        day   = now.weekday()
        if day >= 5:
            return False, "Weekend"
        london = 7 <= hour < 16
        ny     = 13 <= hour < 22
        active = london or ny
        name   = "London+NY 🔥" if london and ny else "London 🇬🇧" if london else "New York 🇺🇸" if ny else "Buiten sessie"
        return active, name
    
    def check_candlestick(self) -> tuple[bool, bool, str, str]:
        o = self.df['Open'].iloc[-1]
        h = self.df['High'].iloc[-1]
        l = self.df['Low'].iloc[-1]
        c = self.df['Close'].iloc[-1]
        bull_pin  = c > o and (o-l) > (h-c)*2 and (h-c) < self.atr*0.3
        bear_pin  = o > c and (h-o) > (c-l)*2 and (c-l) < self.atr*0.3
        o1 = self.df['Open'].iloc[-2];  c1 = self.df['Close'].iloc[-2]
        bull_eng  = c>o and c1<o1 and c>o1 and o<c1
        bear_eng  = o>c and o1<c1 and o>c1 and c<o1
        bull_name = "Hammer/Pin Bar 🔨" if bull_pin else "Bullish Engulfing 🕯" if bull_eng else "/"
        bear_name = "Shooting Star 🔨"  if bear_pin else "Bearish Engulfing 🕯" if bear_eng else "/"
        return (bull_pin or bull_eng), (bear_pin or bear_eng), bull_name, bear_name
    
    def check_ema_trend(self) -> tuple[bool, bool]:
        c     = self.df['Close']
        e20   = c.ewm(span=20).mean().iloc[-1]
        e50   = c.ewm(span=50).mean().iloc[-1]
        e200  = c.ewm(span=200).mean().iloc[-1]
        price = c.iloc[-1]
        return price>e20>e50>e200, price<e20<e50<e200
    
    def calculate_smart_tp(self, direction: str, entry: float, sl: float):
        """Bot kiest zelf beste TP op basis van marktstructuur"""
        high  = self.df['High']
        low   = self.df['Low']
        close = self.df['Close']
        risk  = abs(entry - sl)
        
        swing_high = high.iloc[-100:].max()
        swing_low  = low.iloc[-100:].min()
        fib_range  = swing_high - swing_low
        
        if direction == "BUY":
            levels = sorted([
                high.iloc[-20:-1].max(),
                high.iloc[-50:-1].max(),
                swing_low + fib_range * 1.272,
                swing_low + fib_range * 1.618,
                entry + risk * 2.0,
                entry + risk * 3.0,
                entry + risk * 4.5
            ])
            tps = [l for l in levels if l > entry + risk * 1.5]
            tp1 = tps[0] if len(tps) > 0 else entry + risk * 2.0
            tp2 = tps[1] if len(tps) > 1 else entry + risk * 3.0
            tp3 = tps[2] if len(tps) > 2 else entry + risk * 4.5
        else:
            levels = sorted([
                low.iloc[-20:-1].min(),
                low.iloc[-50:-1].min(),
                swing_high - fib_range * 1.272,
                swing_high - fib_range * 1.618,
                entry - risk * 2.0,
                entry - risk * 3.0,
                entry - risk * 4.5
            ], reverse=True)
            tps = [l for l in levels if l < entry - risk * 1.5]
            tp1 = tps[0] if len(tps) > 0 else entry - risk * 2.0
            tp2 = tps[1] if len(tps) > 1 else entry - risk * 3.0
            tp3 = tps[2] if len(tps) > 2 else entry - risk * 4.5
        
        return tp1, tp2, tp3
    
    def full_analysis(self) -> dict:
        """Volledige analyse — geeft alle confluence resultaten terug"""
        price = self.df['Close'].iloc[-1]
        
        htf_bull, htf_bear                             = self.check_htf_bias()
        struct_bull, struct_bear                       = self.check_market_structure()
        zone_bull, zone_bear, zone_bull_lbl, zone_bear_lbl = self.check_institutional_zone()
        fib_bull, fib_bear                             = self.check_fibonacci()
        liq_bull, liq_bear                             = self.check_liquidity_sweep()
        rsi_bull, rsi_bear                             = self.check_rsi_divergence()
        high_vol                                       = self.check_volume()
        active_sess, sess_name                         = self.check_session()
        cand_bull, cand_bear, cand_bull_nm, cand_bear_nm = self.check_candlestick()
        ema_bull, ema_bear                             = self.check_ema_trend()
        
        buy_score = (int(htf_bull) + int(struct_bull) + zone_bull +
                     int(fib_bull) + int(liq_bull) + int(rsi_bull) +
                     int(high_vol) + int(active_sess) + int(cand_bull) + int(ema_bull))
        sell_score = (int(htf_bear) + int(struct_bear) + zone_bear +
                      int(fib_bear) + int(liq_bear) + int(rsi_bear) +
                      int(high_vol) + int(active_sess) + int(cand_bear) + int(ema_bear))
        
        # SL berekening
        low_recent  = self.df['Low'].iloc[-10:].min()
        high_recent = self.df['High'].iloc[-10:].max()
        buy_sl  = low_recent  - self.atr * 0.3
        sell_sl = high_recent + self.atr * 0.3
        
        # Slimme TP
        buy_tp1, buy_tp2, buy_tp3   = self.calculate_smart_tp("BUY",  price, buy_sl)
        sell_tp1, sell_tp2, sell_tp3 = self.calculate_smart_tp("SELL", price, sell_sl)
        
        buy_risk  = price - buy_sl
        sell_risk = sell_sl - price
        
        return {
            'pair':          self.pair,
            'price':         price,
            'atr':           self.atr,
            'buy_score':     buy_score,
            'sell_score':    sell_score,
            'buy_sl':        buy_sl,
            'sell_sl':       sell_sl,
            'buy_tp1':       buy_tp1,
            'buy_tp2':       buy_tp2,
            'buy_tp3':       buy_tp3,
            'sell_tp1':      sell_tp1,
            'sell_tp2':      sell_tp2,
            'sell_tp3':      sell_tp3,
            'buy_rr1':       (buy_tp1  - price) / buy_risk  if buy_risk  > 0 else 0,
            'buy_rr2':       (buy_tp2  - price) / buy_risk  if buy_risk  > 0 else 0,
            'sell_rr1':      (price - sell_tp1) / sell_risk if sell_risk > 0 else 0,
            'sell_rr2':      (price - sell_tp2) / sell_risk if sell_risk > 0 else 0,
            'confluence': {
                'htf_bull':      htf_bull,    'htf_bear':   htf_bear,
                'struct_bull':   struct_bull, 'struct_bear': struct_bear,
                'zone_bull':     zone_bull,   'zone_bear':  zone_bear,
                'zone_bull_lbl': zone_bull_lbl, 'zone_bear_lbl': zone_bear_lbl,
                'fib_bull':      fib_bull,    'fib_bear':   fib_bear,
                'liq_bull':      liq_bull,    'liq_bear':   liq_bear,
                'rsi_bull':      rsi_bull,    'rsi_bear':   rsi_bear,
                'high_vol':      high_vol,
                'active_sess':   active_sess, 'sess_name':  sess_name,
                'cand_bull':     cand_bull,   'cand_bear':  cand_bear,
                'cand_bull_nm':  cand_bull_nm,'cand_bear_nm': cand_bear_nm,
                'ema_bull':      ema_bull,    'ema_bear':   ema_bear
            }
        }

# ================================================================
# CHART GENERATOR
# ================================================================
def generate_chart(pair: str, df: pd.DataFrame, analysis: dict, direction: str) -> str:
    """Genereert een chart afbeelding met alle zones aangeduid"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9),
                                    gridspec_kw={'height_ratios': [3, 1]},
                                    facecolor='#1a1a2e')
    
    # Donker thema
    for ax in [ax1, ax2]:
        ax.set_facecolor('#1a1a2e')
        ax.tick_params(colors='#aaaaaa', labelsize=8)
        ax.spines['bottom'].set_color('#333355')
        ax.spines['top'].set_color('#333355')
        ax.spines['left'].set_color('#333355')
        ax.spines['right'].set_color('#333355')
    
    df_plot = df.iloc[-80:].copy()
    x       = range(len(df_plot))
    price   = analysis['price']
    
    # Candlesticks tekenen
    for i, (idx, row) in enumerate(df_plot.iterrows()):
        color = '#26a69a' if row['Close'] >= row['Open'] else '#ef5350'
        ax1.plot([i, i], [row['Low'], row['High']], color=color, linewidth=0.8)
        ax1.bar(i, abs(row['Close'] - row['Open']),
                bottom=min(row['Open'], row['Close']),
                color=color, width=0.7, alpha=0.9)
    
    # EMA lijnen
    close  = df_plot['Close'].values
    ema20  = pd.Series(close).ewm(span=20).mean().values
    ema50  = pd.Series(close).ewm(span=50).mean().values
    ema200 = pd.Series(close).ewm(span=200).mean().values
    ax1.plot(x, ema20,  color='#4fc3f7', linewidth=1,   label='EMA 20',  alpha=0.8)
    ax1.plot(x, ema50,  color='#ffb74d', linewidth=1,   label='EMA 50',  alpha=0.8)
    ax1.plot(x, ema200, color='#ef5350', linewidth=1.5, label='EMA 200', alpha=0.8)
    
    # Entry / SL / TP lijnen
    last_x = len(df_plot) - 1
    if direction == "BUY":
        ax1.axhline(y=price,                 color='#ffffff', linewidth=1.5, linestyle='--', alpha=0.9)
        ax1.axhline(y=analysis['buy_sl'],    color='#ef5350', linewidth=1.5, linestyle='-',  alpha=0.9)
        ax1.axhline(y=analysis['buy_tp1'],   color='#66bb6a', linewidth=1,   linestyle=':',  alpha=0.8)
        ax1.axhline(y=analysis['buy_tp2'],   color='#66bb6a', linewidth=1.5, linestyle=':',  alpha=0.9)
        ax1.axhline(y=analysis['buy_tp3'],   color='#66bb6a', linewidth=2,   linestyle=':',  alpha=1.0)
        ax1.fill_between(x, analysis['buy_sl'], price,       alpha=0.07, color='#ef5350')
        ax1.fill_between(x, price, analysis['buy_tp2'],      alpha=0.07, color='#66bb6a')
        ax1.text(last_x+0.5, price,               ' ENTRY',  color='#ffffff', fontsize=7, va='center')
        ax1.text(last_x+0.5, analysis['buy_sl'],  ' SL',     color='#ef5350', fontsize=7, va='center')
        ax1.text(last_x+0.5, analysis['buy_tp1'], ' TP1',    color='#66bb6a', fontsize=7, va='center')
        ax1.text(last_x+0.5, analysis['buy_tp2'], ' TP2',    color='#66bb6a', fontsize=7, va='center')
        ax1.text(last_x+0.5, analysis['buy_tp3'], ' TP3',    color='#66bb6a', fontsize=7, va='center')
    else:
        ax1.axhline(y=price,                  color='#ffffff', linewidth=1.5, linestyle='--', alpha=0.9)
        ax1.axhline(y=analysis['sell_sl'],    color='#ef5350', linewidth=1.5, linestyle='-',  alpha=0.9)
        ax1.axhline(y=analysis['sell_tp1'],   color='#66bb6a', linewidth=1,   linestyle=':',  alpha=0.8)
        ax1.axhline(y=analysis['sell_tp2'],   color='#66bb6a', linewidth=1.5, linestyle=':',  alpha=0.9)
        ax1.axhline(y=analysis['sell_tp3'],   color='#66bb6a', linewidth=2,   linestyle=':',  alpha=1.0)
        ax1.fill_between(x, price, analysis['sell_sl'],       alpha=0.07, color='#ef5350')
        ax1.fill_between(x, analysis['sell_tp2'], price,      alpha=0.07, color='#66bb6a')
        ax1.text(last_x+0.5, price,                ' ENTRY', color='#ffffff', fontsize=7, va='center')
        ax1.text(last_x+0.5, analysis['sell_sl'],  ' SL',    color='#ef5350', fontsize=7, va='center')
        ax1.text(last_x+0.5, analysis['sell_tp1'], ' TP1',   color='#66bb6a', fontsize=7, va='center')
        ax1.text(last_x+0.5, analysis['sell_tp2'], ' TP2',   color='#66bb6a', fontsize=7, va='center')
        ax1.text(last_x+0.5, analysis['sell_tp3'], ' TP3',   color='#66bb6a', fontsize=7, va='center')
    
    # Score box
    score     = analysis['buy_score'] if direction == "BUY" else analysis['sell_score']
    emoji_dir = "🟢 BUY" if direction == "BUY" else "🔴 SELL"
    ax1.text(0.01, 0.97, f'{emoji_dir} {pair}  |  Score: {score}/11',
             transform=ax1.transAxes, color='#ffffff', fontsize=11,
             fontweight='bold', va='top',
             bbox=dict(boxstyle='round,pad=0.4', facecolor='#0d47a1', alpha=0.85))
    
    # Legenda
    legend_elems = [
        Line2D([0],[0], color='#4fc3f7', label='EMA 20'),
        Line2D([0],[0], color='#ffb74d', label='EMA 50'),
        Line2D([0],[0], color='#ef5350', label='EMA 200 / SL'),
        Line2D([0],[0], color='#66bb6a', linestyle=':', label='TP levels'),
        Line2D([0],[0], color='#ffffff', linestyle='--', label='Entry'),
    ]
    ax1.legend(handles=legend_elems, loc='lower left', fontsize=7,
               facecolor='#1a1a2e', labelcolor='white', framealpha=0.7)
    ax1.set_title(f'{pair} | H4 Chart | {datetime.utcnow().strftime("%d/%m/%Y %H:%M")} UTC',
                  color='#cccccc', fontsize=10, pad=8)
    ax1.set_xlim(-1, len(df_plot) + 4)
    
    # RSI subplot
    close_s = df_plot['Close']
    delta   = close_s.diff()
    gain    = delta.clip(lower=0).rolling(14).mean()
    loss    = (-delta.clip(upper=0)).rolling(14).mean()
    rsi     = 100 - (100 / (1 + gain/loss))
    ax2.plot(x, rsi.values, color='#ce93d8', linewidth=1.2, label='RSI')
    ax2.axhline(y=70, color='#ef5350', linewidth=0.7, linestyle='--', alpha=0.6)
    ax2.axhline(y=30, color='#66bb6a', linewidth=0.7, linestyle='--', alpha=0.6)
    ax2.axhline(y=50, color='#aaaaaa', linewidth=0.5, linestyle=':', alpha=0.4)
    ax2.fill_between(x, rsi.values, 70, where=(rsi.values>=70), alpha=0.2, color='#ef5350')
    ax2.fill_between(x, rsi.values, 30, where=(rsi.values<=30), alpha=0.2, color='#66bb6a')
    ax2.set_ylabel('RSI', color='#aaaaaa', fontsize=8)
    ax2.set_ylim(0, 100)
    ax2.set_xlim(-1, len(df_plot) + 4)
    
    plt.tight_layout(pad=1.5)
    filename = f'chart_{pair}_{direction}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    plt.savefig(filename, dpi=130, bbox_inches='tight',
                facecolor='#1a1a2e', edgecolor='none')
    plt.close()
    return filename

# ================================================================
# TELEGRAM SIGNAAL BERICHT
# ================================================================
def build_signal_message(analysis: dict, direction: str) -> str:
    c    = analysis['confluence']
    pair = analysis['pair']
    
    if direction == "BUY":
        score = analysis['buy_score']
        entry = analysis['price']
        sl    = analysis['buy_sl']
        tp1   = analysis['buy_tp1']
        tp2   = analysis['buy_tp2']
        tp3   = analysis['buy_tp3']
        rr1   = analysis['buy_rr1']
        rr2   = analysis['buy_rr2']
        emoji = "🟢"
        zone_lbl = c['zone_bull_lbl']
        checks = [
            (c['htf_bull'],     "HTF Bias (Weekly bullish)"),
            (c['struct_bull'],  "Market Structure (BOS/CHoCH)"),
            (c['zone_bull']>=1, f"Zone: {zone_lbl}"),
            (c['fib_bull'],     "Fibonacci 0.618/0.705"),
            (c['liq_bull'],     "Liquidity Sweep"),
            (c['rsi_bull'],     "RSI Bullish Divergence"),
            (c['high_vol'],     "Volume (+30% boven gem.)"),
            (c['active_sess'],  f"Sessie: {c['sess_name']}"),
            (c['cand_bull'],    f"Candle: {c['cand_bull_nm']}"),
            (not True,          "DXY zwak (bearish dollar)"),
            (c['ema_bull'],     "EMA trend bullish"),
        ]
    else:
        score = analysis['sell_score']
        entry = analysis['price']
        sl    = analysis['sell_sl']
        tp1   = analysis['sell_tp1']
        tp2   = analysis['sell_tp2']
        tp3   = analysis['sell_tp3']
        rr1   = analysis['sell_rr1']
        rr2   = analysis['sell_rr2']
        emoji = "🔴"
        zone_lbl = c['zone_bear_lbl']
        checks = [
            (c['htf_bear'],     "HTF Bias (Weekly bearish)"),
            (c['struct_bear'],  "Market Structure (BOS/CHoCH)"),
            (c['zone_bear']>=1, f"Zone: {zone_lbl}"),
            (c['fib_bear'],     "Fibonacci 0.618/0.705"),
            (c['liq_bear'],     "Liquidity Sweep"),
            (c['rsi_bear'],     "RSI Bearish Divergence"),
            (c['high_vol'],     "Volume (+30% boven gem.)"),
            (c['active_sess'],  f"Sessie: {c['sess_name']}"),
            (c['cand_bear'],    f"Candle: {c['cand_bear_nm']}"),
            (not True,          "DXY sterk (bullish dollar)"),
            (c['ema_bear'],     "EMA trend bearish"),
        ]
    
    stars    = "⭐" * score
    checklist = "\n".join([f"{'✅' if ok else '❌'} {label}" for ok, label in checks])
    digits   = 5 if pair in ["EURUSD","GBPUSD","AUDUSD","NZDUSD","USDCHF","EURGBP"] else 3 if pair in ["USDJPY","EURJPY","GBPJPY"] else 2
    
    msg = (
        f"{emoji} {direction} SIGNAAL — {pair}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ SCORE: {stars} ({score}/11)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷  Entry:          {entry:.{digits}f}\n"
        f"🛑 Stop Loss:     {sl:.{digits}f}\n"
        f"🎯 TP1:            {tp1:.{digits}f}  (1:{rr1:.1f} R:R)\n"
        f"🎯 TP2:            {tp2:.{digits}f}  (1:{rr2:.1f} R:R)\n"
        f"🎯 TP3:            {tp3:.{digits}f}\n"
        f"📦 Risk:           1% van account\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ CONFLUENCE CHECKLIST:\n"
        f"{checklist}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Jij beslist of je deze trade neemt!"
    )
    return msg

# ================================================================
# AI ZELF-LEREND SYSTEEM
# ================================================================
class AILearningSystem:
    
    def update_weights(self):
        """Past confluence gewichten aan op basis van trade resultaten"""
        conn = sqlite3.connect('trading_bot.db')
        c    = conn.cursor()
        c.execute('SELECT confluence, result FROM trades WHERE result IS NOT NULL')
        trades = c.fetchall()
        
        if len(trades) < 30:
            conn.close()
            return "Nog niet genoeg data (min 30 trades nodig)"
        
        factor_stats = {}
        for trade in trades:
            try:
                confluence = json.loads(trade[0])
                result     = trade[1]
                for factor, value in confluence.items():
                    if factor not in factor_stats:
                        factor_stats[factor] = {'wins': 0, 'losses': 0}
                    if value:
                        if result == 'WIN':
                            factor_stats[factor]['wins'] += 1
                        else:
                            factor_stats[factor]['losses'] += 1
            except:
                continue
        
        for factor, stats in factor_stats.items():
            total = stats['wins'] + stats['losses']
            if total < 10:
                continue
            winrate = stats['wins'] / total
            # Gewicht aanpassen: hoge winrate = meer gewicht
            new_weight = 0.5 + winrate  # Range: 0.5 tot 1.5
            c.execute('''UPDATE confluence_weights 
                        SET weight=?, wins=?, losses=?, last_updated=?
                        WHERE factor=?''',
                     (new_weight, stats['wins'], stats['losses'],
                      datetime.now().isoformat(), factor))
        
        conn.commit()
        conn.close()
        return f"✅ AI gewichten geüpdated op basis van {len(trades)} trades"
    
    def get_insights(self) -> str:
        """Geeft AI inzichten over wat het beste werkt"""
        conn = sqlite3.connect('trading_bot.db')
        df   = pd.read_sql('SELECT * FROM trades WHERE result IS NOT NULL', conn)
        conn.close()
        
        if len(df) < 10:
            return "Nog niet genoeg trades voor inzichten (min 10 nodig)"
        
        total    = len(df)
        wins     = len(df[df['result'] == 'WIN'])
        winrate  = wins / total * 100
        avg_rr   = df[df['result']=='WIN']['rr_actual'].mean()
        
        best_pair  = df[df['result']=='WIN']['pair'].value_counts().index[0] if wins > 0 else "N/A"
        worst_pair = df[df['result']=='LOSS']['pair'].value_counts().index[0] if (total-wins) > 0 else "N/A"
        
        insights = (
            f"🧠 AI INZICHTEN\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Totale trades: {total}\n"
            f"✅ Winrate: {winrate:.1f}%\n"
            f"⚖️ Gem. R:R bij win: 1:{avg_rr:.1f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Beste pair: {best_pair}\n"
            f"⚠️ Slechste pair: {worst_pair}\n"
        )
        return insights

# ================================================================
# NIEUWS & FUNDAMENTELE ANALYSE
# ================================================================
def get_market_news() -> str:
    """Haalt market nieuws op via NewsAPI"""
    try:
        url = (f"https://newsapi.org/v2/everything?"
               f"q=forex+trading+fed+ecb+interest+rates&"
               f"language=en&sortBy=publishedAt&pageSize=5&"
               f"apiKey={NEWS_API_KEY}")
        resp    = requests.get(url, timeout=10)
        data    = resp.json()
        articles = data.get('articles', [])
        
        if not articles:
            return "Geen nieuws beschikbaar"
        
        news_text = "📰 MARKET NIEUWS:\n"
        for art in articles[:5]:
            title = art.get('title', '')[:80]
            news_text += f"• {title}\n"
        return news_text
    except:
        return "📰 Nieuws tijdelijk niet beschikbaar"

def get_economic_calendar() -> str:
    """Economische kalender voor vandaag"""
    try:
        # Gratis via investing.com scrape of forex factory
        today    = datetime.now().strftime("%Y-%m-%d")
        calendar = (
            f"📅 ECONOMISCHE KALENDER — {today}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Controleer voor actuele events:\n"
            f"🔗 forexfactory.com/calendar\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Bot blokkeert automatisch 2u\n"
            f"   voor/na HIGH impact events"
        )
        return calendar
    except:
        return "Kalender tijdelijk niet beschikbaar"

# ================================================================
# WEEKRAPPORT GENERATOR
# ================================================================
def generate_weekly_report() -> str:
    conn = sqlite3.connect('trading_bot.db')
    
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    df       = pd.read_sql(
        'SELECT * FROM trades WHERE date >= ? AND result IS NOT NULL',
        conn, params=(week_ago,)
    )
    conn.close()
    
    if len(df) == 0:
        return (
            f"📊 WEEKRAPPORT — {datetime.now().strftime('Week %W | %Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Geen trades deze week\n"
            f"Bot was actief en scande alle 27 pairs 👀"
        )
    
    total    = len(df)
    wins     = len(df[df['result'] == 'WIN'])
    losses   = total - wins
    winrate  = wins / total * 100
    total_pnl = df['pnl_pct'].sum()
    
    best_trade  = df.loc[df['pnl_pct'].idxmax()] if wins > 0 else None
    worst_trade = df.loc[df['pnl_pct'].idxmin()] if losses > 0 else None
    
    report = (
        f"📊 WEEKRAPPORT — {datetime.now().strftime('Week %W | %Y')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 RESULTATEN:\n"
        f"Signalen gegeven: {total}\n"
        f"✅ Gewonnen: {wins}\n"
        f"❌ Verloren: {losses}\n"
        f"🎯 Winrate: {winrate:.1f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 P&L:\n"
        f"Netto: {'🟢 +' if total_pnl >= 0 else '🔴 '}{total_pnl:.2f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    if best_trade is not None:
        report += (
            f"🏆 BESTE TRADE:\n"
            f"{best_trade['pair']} {best_trade['direction']}\n"
            f"Score: {best_trade['score']}/11\n"
            f"R:R: 1:{best_trade['rr_actual']:.1f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    
    if worst_trade is not None:
        report += (
            f"💔 SLECHTSTE TRADE:\n"
            f"{worst_trade['pair']} {worst_trade['direction']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    
    ai = AILearningSystem()
    report += f"\n🧠 BOT REFLECTIE:\n{ai.update_weights()}\n"
    report += f"\n📎 Reflecteer zelf ook!\nWelke trades nam je? Welke sloeg je over?\nDat bepaalt jouw winrate, niet alleen de bot 💪"
    
    return report

# ================================================================
# DAGELIJKSE MACRO BRIEFING
# ================================================================
async def send_daily_briefing(bot: Bot):
    """Elke ochtend 7:00 GMT"""
    try:
        # Data ophalen voor top pairs
        briefing_pairs = ["EURUSD", "XAUUSD", "BTCUSD", "GBPUSD", "US30"]
        pair_summary   = []
        
        for pair in ["EURUSD", "XAUUSD", "BTCUSD", "GBPUSD", "US30"]:
            try:
                df = fetch_data(pair)
                if df is not None and len(df) >= 2:
                    change    = ((df['Close'].iloc[-1] - df['Close'].iloc[-2]) /
                                  df['Close'].iloc[-2] * 100)
                    direction = "🟢" if change >= 0 else "🔴"
                    pair_summary.append(f"{direction} {pair}: {change:+.2f}%")
            except:
                pass
        
        news     = get_market_news()
        calendar = get_economic_calendar()
        
        briefing = (
            f"☀️ DAGELIJKSE MACRO BRIEFING\n"
            f"{datetime.now().strftime('%A %d %B %Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 MARKT OVERZICHT (24u):\n"
            + "\n".join(pair_summary) +
            f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{news}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{calendar}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Bot is actief en scant 27 pairs\n"
            f"Goede trading dag! 💪"
        )
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=briefing)
    except Exception as e:
        print(f"Briefing fout: {e}")

# ================================================================
# TELEGRAM BOT HANDLERS (chat met de bot)
# ================================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 PRO Signal Bot v4.0 actief!\n\n"
        "Commando's:\n"
        "/analyse EURUSD — Analyseer een pair\n"
        "/best — Beste setup op dit moment\n"
        "/pairs — Alle actieve pairs\n"
        "/score — Huidige score per pair\n"
        "/stats — Bot statistieken\n"
        "/report — Weekrapport\n"
        "/win EURUSD — Markeer als WIN\n"
        "/loss EURUSD — Markeer als LOSS\n\n"
        "Of stel gewoon een vraag! 💬"
    )

async def cmd_analyse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyseer een specifiek pair op verzoek"""
    args = context.args
    if not args:
        await update.message.reply_text("Gebruik: /analyse EURUSD")
        return
    
    pair = args[0].upper()
    if pair not in PAIRS:
        await update.message.reply_text(f"❌ {pair} niet gevonden. Gebruik /pairs voor de lijst.")
        return
    
    await update.message.reply_text(f"🔍 Analyseer {pair}...")
    
    try:
        df = fetch_data(pair)
        if df is None or len(df) < 50:
            await update.message.reply_text(f"❌ Niet genoeg data voor {pair}")
            return
        
        ta       = TechnicalAnalysis(pair, df)
        analysis = ta.full_analysis()
        
        buy_s  = analysis['buy_score']
        sell_s = analysis['sell_score']
        
        msg = (
            f"📊 ANALYSE — {pair}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Prijs: {analysis['price']:.5f}\n"
            f"🟢 BUY score:  {buy_s}/11\n"
            f"🔴 SELL score: {sell_s}/11\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        
        if buy_s >= 8:
            msg += f"✅ BUY setup aanwezig! Score {buy_s}/11\n"
        elif sell_s >= 8:
            msg += f"✅ SELL setup aanwezig! Score {sell_s}/11\n"
        else:
            msg += f"⏳ Nog geen setup — wachten op meer confluence\n"
        
        await update.message.reply_text(msg)
        
        # Stuur ook een chart
        best_dir = "BUY" if buy_s >= sell_s else "SELL"
        chart    = generate_chart(pair, df, analysis, best_dir)
        with open(chart, 'rb') as f:
            await update.message.reply_photo(photo=f, caption=f"📈 {pair} H4 Chart")
        os.remove(chart)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Fout bij analyse: {str(e)}")

async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs_list = "\n".join([f"• {p}" for p in PAIRS.keys()])
    await update.message.reply_text(f"📋 ACTIEVE PAIRS (27):\n\n{pairs_list}")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai  = AILearningSystem()
    msg = ai.get_insights()
    await update.message.reply_text(msg)

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = generate_weekly_report()
    await update.message.reply_text(report)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Beantwoord vrije vragen via AI"""
    question = update.message.text.lower()
    
    # Pair naam detecteren
    for pair in PAIRS.keys():
        if pair.lower() in question:
            await update.message.reply_text(f"🔍 Analyseer {pair} voor jou...")
            fake_ctx = type('obj', (object,), {'args': [pair]})()
            await cmd_analyse(update, type('obj', (object,), {'args': [pair]})())
            return
    
    if any(w in question for w in ['winrate', 'statistieken', 'resultaten', 'stats']):
        ai  = AILearningSystem()
        await update.message.reply_text(ai.get_insights())
    elif any(w in question for w in ['nieuws', 'news', 'fundamenteel']):
        await update.message.reply_text(get_market_news())
    elif any(w in question for w in ['rapport', 'report', 'week']):
        await update.message.reply_text(generate_weekly_report())
    elif any(w in question for w in ['pairs', 'welke', 'lijst']):
        await cmd_pairs(update, context)
    else:
        await update.message.reply_text(
            "Ik begrijp je vraag! 💬\n\n"
            "Probeer:\n"
            "• /analyse EURUSD\n"
            "• /stats\n"
            "• /report\n"
            "• 'wat denk je van XAUUSD?'"
        )

# ================================================================
# SCANNER — 2-FASE SYSTEEM
# Fase 1: H4/D1 zone detectie elke 4 uur
# Fase 2: H1/M15 entry check elk uur als prijs in zone is
# ================================================================

# Pairs waarbij een zone is gedetecteerd — bot houdt dit bij
active_zones = {}  # {pair: {'direction': 'BUY'/'SELL', 'zone_high': x, 'zone_low': x}}

async def scan_zones(bot: Bot):
    """FASE 1 — Elke 4 uur: detecteer zones op H4/D1"""
    print(f"🔍 FASE 1 — Zone scan op H4/D1 [{datetime.now().strftime('%H:%M')}]")
    
    for pair in list(PAIRS.keys()):
        try:
            df = fetch_data(pair)
            if df is None or len(df) < 50:
                continue
            
            ta       = TechnicalAnalysis(pair, df)
            analysis = ta.full_analysis()
            c        = analysis['confluence']
            price    = analysis['price']
            
            # Check of prijs in of dichtbij een zone is
            bull_zone = c['zone_bull'] >= 1
            bear_zone = c['zone_bear'] >= 1
            
            if bull_zone:
                active_zones[pair] = {
                    'direction': 'BUY',
                    'analysis':  analysis,
                    'df':        df
                }
                print(f"📍 BUY zone gedetecteerd: {pair} — Wacht op H1/M15 entry")
            elif bear_zone:
                active_zones[pair] = {
                    'direction': 'SELL',
                    'analysis':  analysis,
                    'df':        df
                }
                print(f"📍 SELL zone gedetecteerd: {pair} — Wacht op H1/M15 entry")
            else:
                # Geen zone meer — verwijder uit actieve zones
                if pair in active_zones:
                    del active_zones[pair]
        
        except Exception as e:
            print(f"❌ Zone scan fout {pair}: {e}")
        
        await asyncio.sleep(1)

async def scan_entries(bot: Bot, min_score: int = 8):
    """FASE 2 — Elk uur: check entry op H1/M15 voor pairs in een zone"""
    
    if not active_zones:
        print(f"⏳ Geen actieve zones [{datetime.now().strftime('%H:%M')}]")
        return
    
    print(f"🎯 FASE 2 — Entry scan op H1/M15 voor {len(active_zones)} pairs [{datetime.now().strftime('%H:%M')}]")
    
    for pair, zone_data in list(active_zones.items()):
        try:
            # Haal H1 en M15 data op via beste bron
            pair_type = PAIRS.get(pair, "forex")
            if pair_type == "crypto":
                symbol_h1  = BINANCE_SYMBOLS.get(pair, pair + "USDT")
                resp_h1    = requests.get("https://api.binance.com/api/v3/klines",
                             params={"symbol": symbol_h1, "interval": "1h", "limit": 200}, timeout=10)
                resp_m15   = requests.get("https://api.binance.com/api/v3/klines",
                             params={"symbol": symbol_h1, "interval": "15m", "limit": 200}, timeout=10)
                
                def binance_to_df(data):
                    df = pd.DataFrame(data, columns=['timestamp','Open','High','Low','Close','Volume',
                                     'close_time','quote_vol','trades','taker_buy_base','taker_buy_quote','ignore'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    df.set_index('timestamp', inplace=True)
                    for col in ['Open','High','Low','Close','Volume']:
                        df[col] = df[col].astype(float)
                    return df
                
                df_h1  = binance_to_df(resp_h1.json())
                df_m15 = binance_to_df(resp_m15.json())
            else:
                symbol = (pair[:3] + pair[3:] + "=X") if pair_type == "forex" else YAHOO_SYMBOLS.get(pair, pair)
                ticker  = yf.Ticker(symbol)
                df_h1   = ticker.history(period="1mo", interval="1h")
                df_m15  = ticker.history(period="5d",  interval="15m")
            
            if len(df_h1) < 20 or len(df_m15) < 20:
                continue
            
            # Bepaal welke timeframe te gebruiken op basis van volatiliteit
            ta_h1  = TechnicalAnalysis(pair, df_h1)
            atr_h1 = ta_h1.atr
            atr_avg = df_h1['High'].iloc[-20:].mean() * 0.002
            
            # Hoge volatiliteit → H1, lage volatiliteit → M15
            use_df    = df_h1  if atr_h1 > atr_avg else df_m15
            tf_name   = "H1"   if atr_h1 > atr_avg else "M15"
            
            ta_entry  = TechnicalAnalysis(pair, use_df)
            entry_analysis = ta_entry.full_analysis()
            
            direction = zone_data['direction']
            
            # Combineer H4 zone score met entry timeframe score
            zone_score  = zone_data['analysis']['buy_score']  if direction == "BUY" else zone_data['analysis']['sell_score']
            entry_score = entry_analysis['buy_score'] if direction == "BUY" else entry_analysis['sell_score']
            
            # Totale score = gemiddelde van zone + entry bevestiging
            combined_score = zone_score  # Gebruik zone score als basis
            
            # Entry bevestiging bonussen
            ec = entry_analysis['confluence']
            if direction == "BUY":
                if ec['cand_bull']:  combined_score += 1  # Bullish candle op entry TF
                if ec['liq_bull']:   combined_score += 1  # Liquidity sweep op entry TF
                if ec['rsi_bull']:   combined_score += 1  # RSI divergence op entry TF
            else:
                if ec['cand_bear']:  combined_score += 1
                if ec['liq_bear']:   combined_score += 1
                if ec['rsi_bear']:   combined_score += 1
            
            combined_score = min(combined_score, 11)  # Max 11
            
            if combined_score >= min_score:
                # Gebruik entry TF voor SL/TP berekening
                final_analysis = entry_analysis
                final_analysis['buy_score']  = combined_score
                final_analysis['sell_score'] = combined_score
                
                msg   = build_signal_message(final_analysis, direction)
                
                # Voeg entry TF info toe aan bericht
                msg  += f"\n📐 Entry Timeframe: {tf_name} ({'hoge' if tf_name == 'H1' else 'lage'} volatiliteit)"
                msg  += f"\n📊 Zone detectie: H4/D1 | Entry bevestiging: {tf_name}"
                
                chart = generate_chart(pair, use_df, final_analysis, direction)
                
                # Stuur naar Telegram
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
                with open(chart, 'rb') as f:
                    await bot.send_photo(
                        chat_id=TELEGRAM_CHAT_ID,
                        photo=f,
                        caption=f"📈 {pair} {tf_name} Entry — Score {combined_score}/11"
                    )
                os.remove(chart)
                
                # Sla op in database
                conn = sqlite3.connect('trading_bot.db')
                cur  = conn.cursor()
                cur.execute('''INSERT INTO trades 
                    (date, pair, direction, entry, sl, tp1, tp2, tp3, score, rr_planned, confluence, session)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (
                    datetime.now().isoformat(), pair, direction,
                    final_analysis['price'],
                    final_analysis['buy_sl']   if direction=="BUY"  else final_analysis['sell_sl'],
                    final_analysis['buy_tp1']  if direction=="BUY"  else final_analysis['sell_tp1'],
                    final_analysis['buy_tp2']  if direction=="BUY"  else final_analysis['sell_tp2'],
                    final_analysis['buy_tp3']  if direction=="BUY"  else final_analysis['sell_tp3'],
                    combined_score,
                    final_analysis['buy_rr1']  if direction=="BUY"  else final_analysis['sell_rr1'],
                    json.dumps(final_analysis['confluence']),
                    final_analysis['confluence']['sess_name']
                ))
                conn.commit()
                conn.close()
                
                print(f"✅ {direction} signaal verstuurd: {pair} — Score {combined_score}/11 op {tf_name}")
                
                # Verwijder zone na signaal (cooldown)
                del active_zones[pair]
        
        except Exception as e:
            print(f"❌ Entry scan fout {pair}: {e}")
        
        await asyncio.sleep(1)

# ================================================================
# SCHEDULER
# ================================================================
def run_scheduler(bot: Bot, loop):
    """Dagelijkse briefing + weekrapport scheduler"""
    
    async def daily_briefing():
        await send_daily_briefing(bot)
    
    async def weekly_report():
        report = generate_weekly_report()
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=report)
    
    # Elke ochtend 7:00
    schedule.every().day.at("07:00").do(
        lambda: asyncio.run_coroutine_threadsafe(daily_briefing(), loop)
    )
    # Elke vrijdag 20:00
    schedule.every().friday.at("20:00").do(
        lambda: asyncio.run_coroutine_threadsafe(weekly_report(), loop)
    )
    # FASE 1: Zone detectie elke 4 uur
    schedule.every(4).hours.do(
        lambda: asyncio.run_coroutine_threadsafe(scan_zones(bot), loop)
    )
    # FASE 2: Entry check elk uur
    schedule.every(1).hours.do(
        lambda: asyncio.run_coroutine_threadsafe(scan_entries(bot), loop)
    )
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# ================================================================
# /best COMMANDO — Scant alle pairs en geeft beste setup
# ================================================================
async def cmd_best(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Scanning alle 27 pairs... even geduld! (±1 min)")
    
    results = []
    
    for pair in list(PAIRS.keys()):
        try:
            df = fetch_data(pair)
            if df is None or len(df) < 50:
                continue
            ta       = TechnicalAnalysis(pair, df)
            analysis = ta.full_analysis()
            buy_s    = analysis['buy_score']
            sell_s   = analysis['sell_score']
            best_s   = max(buy_s, sell_s)
            best_dir = "BUY 🟢" if buy_s >= sell_s else "SELL 🔴"
            results.append((pair, best_dir, best_s, analysis))
        except:
            continue
        await asyncio.sleep(0.5)
    
    if not results:
        await update.message.reply_text("❌ Geen data beschikbaar op dit moment.")
        return
    
    # Sorteer op score
    results.sort(key=lambda x: x[2], reverse=True)
    top5 = results[:5]
    
    msg = "🏆 TOP 5 BESTE SETUPS NU\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, (pair, direction, score, _) in enumerate(top5):
        stars = "⭐" * score
        msg += f"{i+1}. {pair} {direction} — {score}/11 {stars}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"💡 Gebruik /analyse {top5[0][0]} voor details!"
    
    await update.message.reply_text(msg)
    
    # Stuur automatisch chart van de beste
    best_pair, best_dir, best_score, best_analysis = top5[0]
    direction = "BUY" if "BUY" in best_dir else "SELL"
    df    = fetch_data(best_pair)
    chart = generate_chart(best_pair, df, best_analysis, direction)
    with open(chart, 'rb') as f:
        await update.message.reply_photo(
            photo=f,
            caption=f"📈 {best_pair} — Beste setup nu! Score {best_score}/11"
        )
    os.remove(chart)

# ================================================================
# MAIN
# ================================================================
async def main():
    print("🤖 PRO Signal Bot v4.0 starten...")
    
    init_database()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("analyse", cmd_analyse))
    app.add_handler(CommandHandler("pairs",   cmd_pairs))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("best",    cmd_best))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    bot  = app.bot
    loop = asyncio.get_event_loop()
    
    # Start scheduler in aparte thread
    scheduler_thread = threading.Thread(target=run_scheduler, args=(bot, loop), daemon=True)
    scheduler_thread.start()
    
    print("✅ Bot actief! Wachtend op signalen en berichten...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
