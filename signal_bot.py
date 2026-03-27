#!/usr/bin/env python3
"""
PRO SIGNAL BOT v5.0 — DEFINITIEVE VERSIE
==========================================
✅ Avond briefing elke dag om 19:00
✅ Briefing bij opstart als gemist
✅ Scant terug in tijd vanaf laatste scan
✅ Gemiste signalen worden alsnog gestuurd
✅ Interessante setups morgen in briefing
✅ Automatische win/loss detectie
✅ /best commando
✅ Chart afbeeldingen
✅ AI zelf-lerend systeem
✅ Weekrapport elke vrijdag 20:00
"""

import os
import json
import sqlite3
import asyncio
import schedule
import time
import threading
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import yfinance as yf
import requests
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ================================================================
# CONFIGURATIE — VUL DIT IN
# ================================================================
TELEGRAM_TOKEN   = "8279417890:AAGyx2PI8wJlmvHy6SiVky2jSw14E9XiwE0"
TELEGRAM_CHAT_ID = "5821649428"
NEWS_API_KEY     = "1c9882779b344175bf8776ed76d16ef1"
TWELVE_DATA_KEY  = "246fb77f58cc4952af953a8de63cb449"

# ================================================================
# TWELVE DATA — FOREX DATA (werkt op Railway!)
# ================================================================

# Twelve Data symbool mapping
TWELVE_SYMBOLS = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "USDCAD": "USD/CAD", "AUDUSD": "AUD/USD", "NZDUSD": "NZD/USD",
    "USDCHF": "USD/CHF", "GBPJPY": "GBP/JPY", "GBPAUD": "GBP/AUD",
    "GBPCAD": "GBP/CAD", "GBPCHF": "GBP/CHF", "GBPNZD": "GBP/NZD",
    "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY", "EURAUD": "EUR/AUD",
    "EURCAD": "EUR/CAD", "EURCHF": "EUR/CHF",
    "XAUUSD": "XAU/USD", "XAGUSD": "XAG/USD",
    "US30":   "DJ30",    "NAS100": "NDX",      "SPX500": "SPX500",
    "DXY":    "DXY"
}

def get_data_twelvedata(pair: str, interval: str = "4h", outputsize: int = 200) -> pd.DataFrame:
    """Haal data op via Twelve Data API"""
    symbol = TWELVE_SYMBOLS.get(pair, pair)
    url    = (f"https://api.twelvedata.com/time_series?"
              f"symbol={symbol}&interval={interval}&outputsize={outputsize}"
              f"&apikey={TWELVE_DATA_KEY}&format=JSON")
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
        if 'values' not in data:
            return pd.DataFrame()
        values = data['values']
        df = pd.DataFrame(values)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.set_index('datetime').sort_index()
        df = df.rename(columns={
            'open': 'Open', 'high': 'High',
            'low':  'Low',  'close': 'Close', 'volume': 'Volume'
        })
        for col in ['Open','High','Low','Close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        if 'Volume' not in df.columns:
            df['Volume'] = 1000
        else:
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(1000)
        return df.dropna()
    except Exception as e:
        print(f"Twelve Data fout {pair}: {e}")
        return pd.DataFrame()

def get_data_yfinance(pair: str, interval: str = "4h") -> pd.DataFrame:
    """Fallback naar Yahoo Finance als Twelve Data faalt"""
    yahoo_map = {
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
        "USDCAD": "USDCAD=X", "AUDUSD": "AUDUSD=X", "NZDUSD": "NZDUSD=X",
        "USDCHF": "USDCHF=X", "GBPJPY": "GBPJPY=X", "GBPAUD": "GBPAUD=X",
        "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", "GBPNZD": "GBPNZD=X",
        "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURAUD": "EURAUD=X",
        "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X",
        "XAUUSD": "GC=F",     "XAGUSD": "SI=F",
        "US30":   "^DJI",     "NAS100": "^NDX",     "SPX500": "^GSPC"
    }
    try:
        sym    = yahoo_map.get(pair, pair)
        ticker = yf.Ticker(sym)
        df     = ticker.history(period="6mo", interval=interval)
        return df
    except:
        return pd.DataFrame()

def get_data(pair: str, interval: str = "4h") -> pd.DataFrame:
    """Gebruik Twelve Data als primaire bron, Yahoo Finance als fallback"""
    # Interval mapping voor Twelve Data
    interval_map = {
        "4h": "4h", "1h": "1h", "15m": "15min",
        "15min": "15min", "1d": "1day", "1day": "1day"
    }
    td_interval = interval_map.get(interval, interval)

    # Probeer altijd eerst Twelve Data
    if TWELVE_DATA_KEY and TWELVE_DATA_KEY != "JOUW_TWELVE_DATA_KEY_HIER":
        df = get_data_twelvedata(pair, td_interval)
        if len(df) >= 20:
            return df

    # Fallback Yahoo Finance (werkt alleen lokaal)
    yf_interval_map = {"4h": "4h", "1h": "1h", "15min": "15m", "1day": "1d"}
    yf_interval = yf_interval_map.get(td_interval, "4h")
    return get_data_yfinance(pair, yf_interval)

# ================================================================
# NIEUWS FILTER — HIGH IMPACT EVENTS
# ================================================================

# High impact keywords
HIGH_IMPACT_KEYWORDS = [
    'nonfarm', 'nfp', 'payroll', 'cpi', 'inflation', 'fed', 'federal reserve',
    'interest rate', 'fomc', 'ecb', 'bank of england', 'boe', 'gdp',
    'unemployment', 'retail sales', 'pmi', 'rate decision', 'rate hike',
    'rate cut', 'powell', 'lagarde', 'emergency', 'recession', 'crash'
]

news_block_until = None  # Globale variabele — tot wanneer geblokkeerd

def check_high_impact_news() -> tuple[bool, str]:
    """Check of er high impact nieuws is de komende 2 uur"""
    global news_block_until
    try:
        url  = (f"https://newsapi.org/v2/everything?"
                f"q=federal+reserve+ecb+interest+rate+nfp+cpi&"
                f"language=en&sortBy=publishedAt&pageSize=10&"
                f"apiKey={NEWS_API_KEY}")
        resp = requests.get(url, timeout=10)
        data = resp.json()
        arts = data.get('articles', [])
        now  = datetime.utcnow()
        for art in arts:
            title   = art.get('title', '').lower()
            desc    = art.get('description', '').lower()
            content = title + " " + desc
            for kw in HIGH_IMPACT_KEYWORDS:
                if kw in content:
                    # Publicatietijd checken
                    pub_str = art.get('publishedAt', '')
                    if pub_str:
                        try:
                            pub_time = datetime.strptime(pub_str, '%Y-%m-%dT%H:%M:%SZ')
                            diff     = abs((now - pub_time).total_seconds() / 3600)
                            if diff <= 2:  # Binnen 2 uur
                                news_block_until = now + timedelta(hours=2)
                                return True, art.get('title', '')[:80]
                        except: pass
        return False, ""
    except:
        return False, ""

def is_news_blocked() -> tuple[bool, str]:
    """Check of trading geblokkeerd is door nieuws"""
    global news_block_until
    if news_block_until and datetime.utcnow() < news_block_until:
        remaining = int((news_block_until - datetime.utcnow()).total_seconds() / 60)
        return True, f"High impact nieuws — nog {remaining} min geblokkeerd"
    blocked, title = check_high_impact_news()
    if blocked:
        return True, f"⚠️ High impact nieuws: {title}"
    return False, ""

# ================================================================
# PAIRS
# ================================================================
PAIRS = {
    # Forex Majors
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCAD": "USDCAD=X", "AUDUSD": "AUDUSD=X", "NZDUSD": "NZDUSD=X",
    "USDCHF": "USDCHF=X",
    # Forex Crosses GBP
    "GBPJPY": "GBPJPY=X", "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X",
    "GBPCHF": "GBPCHF=X", "GBPNZD": "GBPNZD=X",
    # Forex Crosses EUR
    "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURAUD": "EURAUD=X",
    "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X",
    # Commodities
    "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    # Indices
    "US30": "^DJI", "NAS100": "^NDX", "SPX500": "^GSPC"
}

# ================================================================
# DATABASE
# ================================================================
def init_database():
    conn = sqlite3.connect('trading_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, pair TEXT, direction TEXT,
        entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
        score INTEGER, rr_planned REAL, rr_actual REAL,
        result TEXT, pnl_pct REAL, confluence TEXT, session TEXT, notes TEXT,
        trade_taken INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_state (
        key TEXT PRIMARY KEY, value TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS confluence_weights (
        factor TEXT PRIMARY KEY, weight REAL DEFAULT 1.0,
        wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, last_updated TEXT
    )''')
    # Voeg trade_taken kolom toe als hij nog niet bestaat
    try:
        c.execute('ALTER TABLE trades ADD COLUMN trade_taken INTEGER DEFAULT 0')
    except: pass
    for f in ['htf_bias','market_structure','zone_strength','fibonacci',
              'liquidity_sweep','rsi_divergence','volume','session',
              'candlestick','dxy_correlation','ema_trend']:
        c.execute('INSERT OR IGNORE INTO confluence_weights (factor, weight) VALUES (?, 1.0)', (f,))
    conn.commit()
    conn.close()
    print("✅ Database klaar")

def get_state(key, default=None):
    try:
        conn = sqlite3.connect('trading_bot.db')
        c    = conn.cursor()
        c.execute('SELECT value FROM bot_state WHERE key=?', (key,))
        row  = c.fetchone()
        conn.close()
        return row[0] if row else default
    except:
        return default

def set_state(key, value):
    conn = sqlite3.connect('trading_bot.db')
    c    = conn.cursor()
    c.execute('INSERT OR REPLACE INTO bot_state (key, value) VALUES (?,?)', (key, value))
    conn.commit()
    conn.close()

# ================================================================
# TECHNISCHE ANALYSE
# ================================================================
class TechnicalAnalysis:
    def __init__(self, pair, df):
        self.pair = pair
        self.df   = df
        self.atr  = self._atr()

    def _atr(self, p=14):
        h = self.df['High']; l = self.df['Low']; c = self.df['Close']
        tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(p).mean().iloc[-1]

    def check_htf_bias(self):
        c = self.df['Close']
        e20 = c.ewm(span=20).mean(); e50 = c.ewm(span=50).mean()
        return c.iloc[-1]>e20.iloc[-1]>e50.iloc[-1], c.iloc[-1]<e20.iloc[-1]<e50.iloc[-1]

    def check_market_structure(self):
        h = self.df['High']; l = self.df['Low']; c = self.df['Close']
        return c.iloc[-1]>h.iloc[-20:-1].max(), c.iloc[-1]<l.iloc[-20:-1].min()

    def check_institutional_zone(self):
        c=self.df['Close']; o=self.df['Open']; h=self.df['High']; l=self.df['Low']
        price=c.iloc[-1]; bc=sc=0
        for i in range(-20,-3):
            base=abs(c.iloc[i]-o.iloc[i]); strong=abs(c.iloc[i-1]-o.iloc[i-1])
            if base<self.atr*0.5:
                if c.iloc[i-1]>o.iloc[i-1] and strong>self.atr and o.iloc[i+1]>c.iloc[i+1]:
                    if l.iloc[i]*0.999<=price<=h.iloc[i]*1.001: bc+=1; break
                if o.iloc[i-1]>c.iloc[i-1] and strong>self.atr and c.iloc[i+1]>o.iloc[i+1]:
                    if l.iloc[i]*0.999<=price<=h.iloc[i]*1.001: sc+=1; break
        for i in range(-10,-2):
            if o.iloc[i]>c.iloc[i] and c.iloc[i+1]>o.iloc[i+1] and (c.iloc[i+1]-o.iloc[i+1])>self.atr*0.8:
                if l.iloc[i]<=price<=h.iloc[i]: bc+=1; break
            if c.iloc[i]>o.iloc[i] and o.iloc[i+1]>c.iloc[i+1] and (o.iloc[i+1]-c.iloc[i+1])>self.atr*0.8:
                if l.iloc[i]<=price<=h.iloc[i]: sc+=1; break
        for i in range(-8,-2):
            if l.iloc[i]>h.iloc[i-2] and h.iloc[i-2]<=price<=l.iloc[i]: bc+=1; break
            if h.iloc[i]<l.iloc[i-2] and h.iloc[i]<=price<=l.iloc[i-2]: sc+=1; break
        bs=2 if bc>=3 else 1 if bc>=2 else 0
        ss=2 if sc>=3 else 1 if sc>=2 else 0
        bl=f"Sterk 💎" if bc==3 else f"Gemiddeld ({bc}/3)" if bc>=2 else f"Zwak ({bc}/3)"
        sl=f"Sterk 💎" if sc==3 else f"Gemiddeld ({sc}/3)" if sc>=2 else f"Zwak ({sc}/3)"
        return bs, ss, bl, sl

    def check_fibonacci(self):
        sh=self.df['High'].iloc[-50:].max(); sl=self.df['Low'].iloc[-50:].min()
        p=self.df['Close'].iloc[-1]; r=sh-sl; buf=r*0.02
        return (min(sh-r*.618,sh-r*.705)-buf<=p<=max(sh-r*.618,sh-r*.705)+buf,
                min(sl+r*.618,sl+r*.705)-buf<=p<=max(sl+r*.618,sl+r*.705)+buf)

    def check_liquidity_sweep(self):
        h=self.df['High']; l=self.df['Low']; c=self.df['Close']; o=self.df['Open']
        ph=h.iloc[-10:-2].max(); pl=l.iloc[-10:-2].min()
        return (l.iloc[-2]<pl and c.iloc[-2]>pl and (o.iloc[-2]-l.iloc[-2])>self.atr*.3,
                h.iloc[-2]>ph and c.iloc[-2]<ph and (h.iloc[-2]-o.iloc[-2])>self.atr*.3)

    def check_rsi_divergence(self):
        c=self.df['Close']; d=c.diff()
        g=d.clip(lower=0).rolling(14).mean(); ls=(-d.clip(upper=0)).rolling(14).mean()
        rsi=100-(100/(1+g/ls))
        bull=c.iloc[-1]<c.iloc[-10:-1].min() and rsi.iloc[-1]>rsi.iloc[-10:-1].min() and rsi.iloc[-1]<50
        bear=c.iloc[-1]>c.iloc[-10:-1].max() and rsi.iloc[-1]<rsi.iloc[-10:-1].max() and rsi.iloc[-1]>50
        return bull, bear

    def check_volume(self):
        v=self.df['Volume']; return v.iloc[-1]>v.iloc[-20:-1].mean()*1.3

    def check_session(self):
        now=datetime.utcnow(); h=now.hour; d=now.weekday()
        if d>=5: return False,"Weekend"
        lon=7<=h<16; ny=13<=h<22; active=lon or ny
        name="London+NY 🔥" if lon and ny else "London 🇬🇧" if lon else "New York 🇺🇸" if ny else "Buiten sessie"
        return active, name

    def check_candlestick(self):
        o=self.df['Open'].iloc[-1]; h=self.df['High'].iloc[-1]
        l=self.df['Low'].iloc[-1];  c=self.df['Close'].iloc[-1]
        o1=self.df['Open'].iloc[-2];c1=self.df['Close'].iloc[-2]
        bp=c>o and (o-l)>(h-c)*2 and (h-c)<self.atr*.3
        sp=o>c and (h-o)>(c-l)*2 and (c-l)<self.atr*.3
        be=c>o and c1<o1 and c>o1 and o<c1
        se=o>c and o1<c1 and o>c1 and c<o1
        return (bp or be),(sp or se),("Hammer 🔨" if bp else "Engulfing 🕯" if be else "/"),("Shooting Star 🔨" if sp else "Engulfing 🕯" if se else "/")

    def check_ema_trend(self):
        c=self.df['Close']
        e20=c.ewm(span=20).mean().iloc[-1]; e50=c.ewm(span=50).mean().iloc[-1]; e200=c.ewm(span=200).mean().iloc[-1]; p=c.iloc[-1]
        return p>e20>e50>e200, p<e20<e50<e200

    def smart_tp(self, direction, entry, sl):
        h=self.df['High']; l=self.df['Low']; risk=abs(entry-sl)
        sh=h.iloc[-100:].max(); slo=l.iloc[-100:].min(); rng=sh-slo
        if direction=="BUY":
            lvls=sorted([h.iloc[-20:-1].max(),h.iloc[-50:-1].max(),slo+rng*1.272,slo+rng*1.618,entry+risk*2,entry+risk*3,entry+risk*4.5])
            tps=[x for x in lvls if x>entry+risk*1.5]
            return (tps[0] if tps else entry+risk*2),(tps[1] if len(tps)>1 else entry+risk*3),(tps[2] if len(tps)>2 else entry+risk*4.5)
        else:
            lvls=sorted([l.iloc[-20:-1].min(),l.iloc[-50:-1].min(),sh-rng*1.272,sh-rng*1.618,entry-risk*2,entry-risk*3,entry-risk*4.5],reverse=True)
            tps=[x for x in lvls if x<entry-risk*1.5]
            return (tps[0] if tps else entry-risk*2),(tps[1] if len(tps)>1 else entry-risk*3),(tps[2] if len(tps)>2 else entry-risk*4.5)

    def full_analysis(self):
        price=self.df['Close'].iloc[-1]
        htfb,htfs=self.check_htf_bias()
        sb,sb2=self.check_market_structure()
        zb,zs,zbl,zsl=self.check_institutional_zone()
        fb,fs=self.check_fibonacci()
        lb,ls=self.check_liquidity_sweep()
        rb,rs=self.check_rsi_divergence()
        hv=self.check_volume()
        asess,sname=self.check_session()
        cb,cs,cbn,csn=self.check_candlestick()
        eb,es=self.check_ema_trend()
        try:
            dxy_df = get_data_twelvedata("DXY", "1h")
            if len(dxy_df) > 5:
                dxy_ema = dxy_df['Close'].ewm(span=20).mean().iloc[-1]
                dxy_b   = dxy_df['Close'].iloc[-1] > dxy_ema
                dxy_s   = not dxy_b
            else: dxy_b=dxy_s=False
            else: dxy_b=dxy_s=False
        except: dxy_b=dxy_s=False
        buys=int(htfb)+int(sb)+zb+int(fb)+int(lb)+int(rb)+int(hv)+int(asess)+int(cb)+int(dxy_s)+int(eb)
        sells=int(htfs)+int(sb2)+zs+int(fs)+int(ls)+int(rs)+int(hv)+int(asess)+int(cs)+int(dxy_b)+int(es)
        lr=self.df['Low'].iloc[-10:].min(); hr=self.df['High'].iloc[-10:].max()
        bsl=lr-self.atr*.3; ssl=hr+self.atr*.3
        bt1,bt2,bt3=self.smart_tp("BUY",price,bsl)
        st1,st2,st3=self.smart_tp("SELL",price,ssl)
        br=price-bsl; sr=ssl-price
        return {
            'pair':self.pair,'price':price,'atr':self.atr,
            'buy_score':buys,'sell_score':sells,
            'buy_sl':bsl,'sell_sl':ssl,
            'buy_tp1':bt1,'buy_tp2':bt2,'buy_tp3':bt3,
            'sell_tp1':st1,'sell_tp2':st2,'sell_tp3':st3,
            'buy_rr1':(bt1-price)/br if br>0 else 0,'buy_rr2':(bt2-price)/br if br>0 else 0,
            'sell_rr1':(price-st1)/sr if sr>0 else 0,'sell_rr2':(price-st2)/sr if sr>0 else 0,
            'confluence':{
                'htf_bull':htfb,'htf_bear':htfs,'struct_bull':sb,'struct_bear':sb2,
                'zone_bull':zb,'zone_bear':zs,'zone_bull_lbl':zbl,'zone_bear_lbl':zsl,
                'fib_bull':fb,'fib_bear':fs,'liq_bull':lb,'liq_bear':ls,
                'rsi_bull':rb,'rsi_bear':rs,'high_vol':hv,'active_sess':asess,'sess_name':sname,
                'cand_bull':cb,'cand_bear':cs,'cand_bull_nm':cbn,'cand_bear_nm':csn,
                'ema_bull':eb,'ema_bear':es,'dxy_bull':dxy_b,'dxy_bear':dxy_s
            }
        }

# ================================================================
# CHART
# ================================================================
def generate_chart(pair, df, analysis, direction):
    fig,(ax1,ax2)=plt.subplots(2,1,figsize=(14,9),gridspec_kw={'height_ratios':[3,1]},facecolor='#1a1a2e')
    for ax in [ax1,ax2]:
        ax.set_facecolor('#1a1a2e'); ax.tick_params(colors='#aaaaaa',labelsize=8)
        for s in ax.spines.values(): s.set_color('#333355')
    df_plot=df.iloc[-80:].copy(); x=range(len(df_plot))
    for i,(_,row) in enumerate(df_plot.iterrows()):
        col='#26a69a' if row['Close']>=row['Open'] else '#ef5350'
        ax1.plot([i,i],[row['Low'],row['High']],color=col,linewidth=0.8)
        ax1.bar(i,abs(row['Close']-row['Open']),bottom=min(row['Open'],row['Close']),color=col,width=0.7,alpha=0.9)
    close=df_plot['Close'].values
    ax1.plot(x,pd.Series(close).ewm(span=20).mean().values,color='#4fc3f7',linewidth=1,label='EMA20')
    ax1.plot(x,pd.Series(close).ewm(span=50).mean().values,color='#ffb74d',linewidth=1,label='EMA50')
    ax1.plot(x,pd.Series(close).ewm(span=200).mean().values,color='#ef5350',linewidth=1.5,label='EMA200')
    last_x=len(df_plot)-1; price=analysis['price']
    if direction=="BUY":
        for level,col,lbl,lw,ls in [(price,'#ffffff','ENTRY',1.5,'--'),(analysis['buy_sl'],'#ef5350','SL',1.5,'-'),(analysis['buy_tp1'],'#66bb6a','TP1',1,':'),(analysis['buy_tp2'],'#66bb6a','TP2',1.5,':'),(analysis['buy_tp3'],'#66bb6a','TP3',2,':')]:
            ax1.axhline(y=level,color=col,linewidth=lw,linestyle=ls)
            ax1.text(last_x+0.5,level,f' {lbl}',color=col,fontsize=7,va='center')
    else:
        for level,col,lbl,lw,ls in [(price,'#ffffff','ENTRY',1.5,'--'),(analysis['sell_sl'],'#ef5350','SL',1.5,'-'),(analysis['sell_tp1'],'#66bb6a','TP1',1,':'),(analysis['sell_tp2'],'#66bb6a','TP2',1.5,':'),(analysis['sell_tp3'],'#66bb6a','TP3',2,':')]:
            ax1.axhline(y=level,color=col,linewidth=lw,linestyle=ls)
            ax1.text(last_x+0.5,level,f' {lbl}',color=col,fontsize=7,va='center')
    score=analysis['buy_score'] if direction=="BUY" else analysis['sell_score']
    ax1.text(0.01,0.97,f'{"🟢 BUY" if direction=="BUY" else "🔴 SELL"} {pair}  |  Score: {score}/11',
             transform=ax1.transAxes,color='#ffffff',fontsize=11,fontweight='bold',va='top',
             bbox=dict(boxstyle='round,pad=0.4',facecolor='#0d47a1',alpha=0.85))
    ax1.legend(loc='lower left',fontsize=7,facecolor='#1a1a2e',labelcolor='white',framealpha=0.7)
    ax1.set_title(f'{pair} | H4 | {datetime.utcnow().strftime("%d/%m/%Y %H:%M")} UTC',color='#cccccc',fontsize=10,pad=8)
    ax1.set_xlim(-1,len(df_plot)+4)
    cs=df_plot['Close']; d=cs.diff(); g=d.clip(lower=0).rolling(14).mean(); lo=(-d.clip(upper=0)).rolling(14).mean()
    rsi=100-(100/(1+g/lo))
    ax2.plot(x,rsi.values,color='#ce93d8',linewidth=1.2)
    ax2.axhline(y=70,color='#ef5350',linewidth=0.7,linestyle='--',alpha=0.6)
    ax2.axhline(y=30,color='#66bb6a',linewidth=0.7,linestyle='--',alpha=0.6)
    ax2.set_ylabel('RSI',color='#aaaaaa',fontsize=8); ax2.set_ylim(0,100); ax2.set_xlim(-1,len(df_plot)+4)
    plt.tight_layout(pad=1.5)
    fn=f'chart_{pair}_{direction}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    plt.savefig(fn,dpi=130,bbox_inches='tight',facecolor='#1a1a2e',edgecolor='none'); plt.close()
    return fn

# ================================================================
# SIGNAAL BERICHT
# ================================================================
def calculate_lotsize(account_balance, risk_pct, entry, sl):
    """Berekent lotsize op basis van risk percentage"""
    risk_amount = account_balance * (risk_pct / 100)
    sl_pips     = abs(entry - sl)
    if sl_pips <= 0: return 0.01
    # Standaard pip waarde voor forex (~$10 per pip per lot)
    lot = risk_amount / (sl_pips * 10000)
    lot = round(max(0.01, min(100, lot)), 2)
    return lot

def build_signal_message(analysis, direction, account_balance=10000):
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
        checks = [
            (c['htf_bull'],     "HTF Bias bullish"),
            (c['struct_bull'],  "Market Structure BOS"),
            (c['zone_bull']>=1, f"Zone: {c['zone_bull_lbl']}"),
            (c['fib_bull'],     "Fibonacci 0.618/0.705"),
            (c['liq_bull'],     "Liquidity Sweep"),
            (c['rsi_bull'],     "RSI Divergence"),
            (c['high_vol'],     "Volume +30%"),
            (c['active_sess'],  f"Sessie: {c['sess_name']}"),
            (c['cand_bull'],    f"Candle: {c['cand_bull_nm']}"),
            (c['dxy_bear'],     "DXY zwak"),
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
        checks = [
            (c['htf_bear'],     "HTF Bias bearish"),
            (c['struct_bear'],  "Market Structure BOS"),
            (c['zone_bear']>=1, f"Zone: {c['zone_bear_lbl']}"),
            (c['fib_bear'],     "Fibonacci 0.618/0.705"),
            (c['liq_bear'],     "Liquidity Sweep"),
            (c['rsi_bear'],     "RSI Divergence"),
            (c['high_vol'],     "Volume +30%"),
            (c['active_sess'],  f"Sessie: {c['sess_name']}"),
            (c['cand_bear'],    f"Candle: {c['cand_bear_nm']}"),
            (c['dxy_bull'],     "DXY sterk"),
            (c['ema_bear'],     "EMA trend bearish"),
        ]

    # Risk % op basis van score
    if score >= 8:   risk_pct = 3.0
    elif score >= 6: risk_pct = 2.0
    else:            risk_pct = 1.0

    lots      = calculate_lotsize(account_balance, risk_pct, entry, sl)
    checklist = "\n".join([f"{'✅' if ok else '❌'} {lbl}" for ok, lbl in checks])
    d = 5 if pair in ["EURUSD","GBPUSD","AUDUSD","NZDUSD","USDCHF","EURGBP"] else 3 if "JPY" in pair else 2

    return (
        f"*{'🟢 BUY' if direction=='BUY' else '🔴 SELL'} — {pair}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Score: {score}/10\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷  Entry:   {entry:.{d}f}\n"
        f"🛑 SL:      {sl:.{d}f}\n"
        f"🎯 TP1:     {tp1:.{d}f}  (1:{rr1:.1f})\n"
        f"🎯 TP2:     {tp2:.{d}f}  (1:{rr2:.1f})\n"
        f"🎯 TP3:     {tp3:.{d}f}\n"
        f"📦 Lots:    {lots} ({risk_pct}% risk)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ CONFLUENCE:\n{checklist}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Jij beslist!"
    )

# ================================================================
# AUTO WIN/LOSS DETECTIE
# ================================================================
async def check_trade_results(bot):
    conn=sqlite3.connect('trading_bot.db'); c=conn.cursor()
    c.execute('SELECT id,pair,direction,entry,sl,tp1,tp2,date FROM trades WHERE result IS NULL')
    trades=c.fetchall(); conn.close()
    for t in trades:
        id_,pair,direction,entry,sl,tp1,tp2,date=t
        try:
            ticker=yf.Ticker(PAIRS[pair]); df=ticker.history(period="5d",interval="1h")
            if len(df)<5: continue
            td=datetime.fromisoformat(date); df_after=df[df.index>td.strftime('%Y-%m-%d')]
            if len(df_after)<2: continue
            result=None; rr=0; risk=abs(entry-sl)
            for _,row in df_after.iterrows():
                if direction=="BUY":
                    if row['Low']<=sl: result='LOSS'; rr=-1; break
                    if row['High']>=tp2: result='WIN'; rr=abs(tp2-entry)/risk; break
                    if row['High']>=tp1: result='WIN'; rr=abs(tp1-entry)/risk; break
                else:
                    if row['High']>=sl: result='LOSS'; rr=-1; break
                    if row['Low']<=tp2: result='WIN'; rr=abs(entry-tp2)/risk; break
                    if row['Low']<=tp1: result='WIN'; rr=abs(entry-tp1)/risk; break
            if result:
                conn=sqlite3.connect('trading_bot.db'); c=conn.cursor()
                c.execute('UPDATE trades SET result=?,rr_actual=?,pnl_pct=? WHERE id=?',(result,rr,rr,id_))
                conn.commit(); conn.close()
                e="✅ WIN" if result=='WIN' else "❌ LOSS"
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID,
                    text=f"{e} — {pair} {direction}\nR:R: 1:{rr:.1f}\nAutomatisch gedetecteerd 🤖")
        except Exception as e: print(f"Win/loss fout {pair}: {e}")

# ================================================================
# TRADE GENOMEN / NIET GENOMEN
# ================================================================
def mark_trade_taken(trade_id: int, taken: bool):
    conn = sqlite3.connect('trading_bot.db')
    c    = conn.cursor()
    c.execute('UPDATE trades SET trade_taken=? WHERE id=?', (1 if taken else 0, trade_id))
    conn.commit()
    conn.close()

def get_last_signal_id() -> int:
    conn = sqlite3.connect('trading_bot.db')
    c    = conn.cursor()
    c.execute('SELECT id FROM trades ORDER BY id DESC LIMIT 1')
    row  = c.fetchone()
    conn.close()
    return row[0] if row else 0

# ================================================================
# MAANDELIJKSE REFLECTIE
# ================================================================
def generate_monthly_report() -> str:
    conn      = sqlite3.connect('trading_bot.db')
    now       = datetime.now()
    # Eerste dag van deze maand
    first_day = now.replace(day=1, hour=0, minute=0, second=0).isoformat()
    
    df_all    = pd.read_sql('SELECT * FROM trades WHERE date >= ?', conn, params=(first_day,))
    df_taken  = df_all[df_all['trade_taken'] == 1]
    df_result = df_taken[df_taken['result'].notna()]
    conn.close()

    maand     = now.strftime('%B %Y')
    
    if len(df_all) == 0:
        return (f"📅 MAANDRAPPORT — {maand}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Geen signalen deze maand.")

    # Statistieken signalen
    total_signals = len(df_all)
    taken         = len(df_taken)
    not_taken     = total_signals - taken
    skip_rate     = (not_taken / total_signals * 100) if total_signals > 0 else 0

    # Statistieken resultaten
    wins   = len(df_result[df_result['result'] == 'WIN'])
    losses = len(df_result[df_result['result'] == 'LOSS'])
    total_results = wins + losses
    winrate = (wins / total_results * 100) if total_results > 0 else 0
    total_pnl = df_result['pnl_pct'].sum() if len(df_result) > 0 else 0

    # Beste en slechtste trade
    best_trade  = df_result.loc[df_result['pnl_pct'].idxmax()] if wins > 0 else None
    worst_trade = df_result.loc[df_result['pnl_pct'].idxmin()] if losses > 0 else None

    # Beste pair
    best_pair = df_result[df_result['result']=='WIN']['pair'].value_counts().index[0] if wins > 0 else "N/A"

    # Gemiste signalen analyse
    missed_df = df_all[df_all['trade_taken'] == 0]
    missed_wins = 0
    if len(missed_df) > 0:
        for _, row in missed_df.iterrows():
            if row['result'] == 'WIN':
                missed_wins += 1

    report = (
        f"📅 MAANDRAPPORT — {maand}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 SIGNALEN:\n"
        f"Totaal gegeven: {total_signals}\n"
        f"✅ Genomen: {taken}\n"
        f"⏭ Overgeslagen: {not_taken} ({skip_rate:.0f}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 RESULTATEN (genomen trades):\n"
        f"✅ Winst: {wins}\n"
        f"❌ Verlies: {losses}\n"
        f"🎯 Winrate: {winrate:.1f}%\n"
        f"💵 Netto P&L: {'🟢 +' if total_pnl >= 0 else '🔴 '}{total_pnl:.2f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if best_trade is not None:
        report += (f"🏆 BESTE TRADE:\n"
                   f"{best_trade['pair']} {best_trade['direction']} "
                   f"+{best_trade['pnl_pct']:.2f}%\n"
                   f"━━━━━━━━━━━━━━━━━━━━━━\n")

    if worst_trade is not None:
        report += (f"💔 SLECHTSTE TRADE:\n"
                   f"{worst_trade['pair']} {worst_trade['direction']} "
                   f"{worst_trade['pnl_pct']:.2f}%\n"
                   f"━━━━━━━━━━━━━━━━━━━━━━\n")

    report += (
        f"🏅 Beste pair: {best_pair}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 BOT REFLECTIE:\n"
    )

    if winrate >= 60:
        report += "Uitstekende maand! Strategie werkt goed. 🔥\n"
    elif winrate >= 50:
        report += "Winstgevende maand. Blijf consistent. 💪\n"
    else:
        report += "Moeilijke maand. Analyseer je verliezen. 📚\n"

    if skip_rate > 50:
        report += f"Je sloeg {skip_rate:.0f}% van de signalen over — vertrouw de bot meer! 👀\n"

    if missed_wins > 0:
        report += f"⚠️ Je miste {missed_wins} winnende trades door ze over te slaan!\n"

    report += f"━━━━━━━━━━━━━━━━━━━━━━\n📎 Reflecteer en pas je strategie aan! 💪"
    return report

async def send_monthly_report(bot):
    """Stuurt maandrapport en slaat datum op"""
    report = generate_monthly_report()
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=report)
    set_state('last_monthly_report', datetime.now().strftime('%Y-%m'))
    print("✅ Maandrapport verstuurd")

async def check_missed_monthly_report(bot):
    """Bij opstart: check of maandrapport gemist was vorige maand"""
    last      = get_state('last_monthly_report', '')
    now       = datetime.now()
    current_m = now.strftime('%Y-%m')
    prev_m    = (now.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

    # Eerste keer ooit → sla huidige maand op, stuur niks
    if last == '':
        set_state('last_monthly_report', current_m)
        return

    # Laatste dag van deze maand en nog niet verstuurd → stuur
    last_day = (now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    if now.day == last_day.day and last != current_m:
        print("📅 Maandrapport versturen — laatste dag van maand!")
        await send_monthly_report(bot)

    # Vorige maand rapport gemist → stuur alsnog
    elif last == prev_m and last != current_m and now.day >= 2:
        print("📅 Gemist maandrapport vorige maand — nu versturen!")
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"📅 Gemist maandrapport van {prev_m}:\n\n" + generate_monthly_report()
        )
        set_state('last_monthly_report', current_m)

# ================================================================
# NIEUWS & SETUPS MORGEN
# ================================================================
def get_market_news():
    try:
        url=f"https://newsapi.org/v2/everything?q=forex+fed+ecb&language=en&sortBy=publishedAt&pageSize=5&apiKey={NEWS_API_KEY}"
        resp=requests.get(url,timeout=10); data=resp.json(); arts=data.get('articles',[])
        if not arts: return "Geen nieuws beschikbaar"
        return "📰 NIEUWS VANDAAG:\n"+"".join([f"• {a.get('title','')[:80]}\n" for a in arts[:5]])
    except: return "📰 Nieuws tijdelijk niet beschikbaar"

def get_upcoming_setups():
    interesting = []
    for pair in list(PAIRS.keys())[:12]:
        try:
            df = get_data(pair, "4h")
            if len(df) < 50: continue
            a  = TechnicalAnalysis(pair, df).full_analysis()
            best_s = max(a['buy_score'], a['sell_score'])
            if best_s >= 5:
                d = "BUY 🟢" if a['buy_score'] >= a['sell_score'] else "SELL 🔴"
                interesting.append((pair, d, best_s))
        except: continue
    if not interesting: return "Geen opvallende setups voor morgen"
    interesting.sort(key=lambda x: x[2], reverse=True)
    return "👀 INTERESSANT VOOR MORGEN:\n" + "".join([f"• {p} {d} — nadert setup ({min(s,10)}/10)\n" for p,d,s in interesting[:5]])

# ================================================================
# AVOND BRIEFING
# ================================================================
async def send_evening_briefing(bot):
    try:
        today   = datetime.now().strftime('%A %d %B %Y')
        summary = []
        for pair in ["EURUSD", "XAUUSD", "GBPUSD", "US30", "NAS100"]:
            try:
                df = get_data(pair, "1day")
                if len(df) >= 2:
                    ch = (df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2] * 100
                    summary.append(f"{'🟢' if ch >= 0 else '🔴'} {pair}: {ch:+.2f}%")
            except: pass

        # Nieuws check voor morgen
        blocked, reason = is_news_blocked()
        news_warning = f"\n⚠️ LET OP: {reason}" if blocked else ""

        briefing = (
            f"🌙 AVOND BRIEFING — {today}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 MARKT VANDAAG:\n" + "\n".join(summary) +
            f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{get_market_news()}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{get_upcoming_setups()}\n"
            f"{news_warning}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 {len(PAIRS)} pairs gescand | Goede avond! 💪"
        )
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text=briefing)
        set_state('last_briefing_date',datetime.now().strftime('%Y-%m-%d'))
        print("✅ Avond briefing verstuurd")
    except Exception as e: print(f"Briefing fout: {e}")

async def check_missed_briefing(bot):
    last=get_state('last_briefing_date',''); today=datetime.now().strftime('%Y-%m-%d')
    if last!=today and datetime.now().hour>=19:
        print("📬 Gemiste briefing — nu versturen!")
        await send_evening_briefing(bot)

# ================================================================
# WEEKRAPPORT
# ================================================================
def generate_weekly_report():
    conn=sqlite3.connect('trading_bot.db')
    week_ago=(datetime.now()-timedelta(days=7)).isoformat()
    df=pd.read_sql('SELECT * FROM trades WHERE date >= ? AND result IS NOT NULL',conn,params=(week_ago,))
    conn.close()
    if len(df)==0:
        return (f"📊 WEEKRAPPORT — {datetime.now().strftime('Week %W | %Y')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\nGeen trades deze week\nBot scande alle 27 pairs 👀")
    total=len(df); wins=len(df[df['result']=='WIN']); pnl=df['pnl_pct'].sum()
    ai=AILearningSystem()
    return (f"📊 WEEKRAPPORT — {datetime.now().strftime('Week %W | %Y')}\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Trades: {total} | ✅ {wins} | ❌ {total-wins}\n🎯 Winrate: {wins/total*100:.1f}%\n"
            f"💰 Netto: {'🟢 +' if pnl>=0 else '🔴 '}{pnl:.2f}%\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧠 {ai.update_weights()}\n\n📎 Reflecteer ook zelf! 💪")

# ================================================================
# AI
# ================================================================
class AILearningSystem:
    def update_weights(self):
        conn=sqlite3.connect('trading_bot.db'); c=conn.cursor()
        c.execute('SELECT confluence,result FROM trades WHERE result IS NOT NULL')
        trades=c.fetchall()
        if len(trades)<30: conn.close(); return "Nog niet genoeg data (min 30)"
        fs={}
        for t in trades:
            try:
                conf=json.loads(t[0]); res=t[1]
                for f,v in conf.items():
                    if f not in fs: fs[f]={'wins':0,'losses':0}
                    if v:
                        if res=='WIN': fs[f]['wins']+=1
                        else: fs[f]['losses']+=1
            except: continue
        for f,s in fs.items():
            total=s['wins']+s['losses']
            if total<10: continue
            c.execute('UPDATE confluence_weights SET weight=?,wins=?,losses=?,last_updated=? WHERE factor=?',
                     (0.5+s['wins']/total,s['wins'],s['losses'],datetime.now().isoformat(),f))
        conn.commit(); conn.close()
        return f"AI gewichten geüpdated ({len(trades)} trades)"

    def get_insights(self):
        conn=sqlite3.connect('trading_bot.db')
        df=pd.read_sql('SELECT * FROM trades WHERE result IS NOT NULL',conn); conn.close()
        if len(df)<10: return "Nog niet genoeg trades (min 10)"
        total=len(df); wins=len(df[df['result']=='WIN']); wr=wins/total*100
        avg=df[df['result']=='WIN']['rr_actual'].mean() if wins>0 else 0
        best=df[df['result']=='WIN']['pair'].value_counts().index[0] if wins>0 else "N/A"
        worst=df[df['result']=='LOSS']['pair'].value_counts().index[0] if (total-wins)>0 else "N/A"
        return (f"🧠 AI INZICHTEN\n━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Trades: {total} | ✅ Winrate: {wr:.1f}%\n⚖️ Gem. R:R: 1:{avg:.1f}\n"
                f"🏆 Beste: {best} | ⚠️ Slechtste: {worst}")

# ================================================================
# SCANNER
# ================================================================
active_zones = {}

async def scan_zones(bot):
    """Scant alle pairs op vroege setups — geen zone vereist meer"""
    print(f"🔍 Scan [{datetime.now().strftime('%H:%M')}]")
    set_state('last_scan_time', datetime.now().isoformat())

    # Check nieuws blokkering
    blocked, reason = is_news_blocked()
    if blocked:
        print(f"⛔ Scan geblokkeerd: {reason}")
        return

    for pair in PAIRS.keys():
        try:
            df = get_data(pair, "4h")
            if len(df) < 50: continue
            a  = TechnicalAnalysis(pair, df).full_analysis()
            c  = a['confluence']

            # VROEG SIGNAAL LOGICA — 5 van 6 kernfactoren moeten kloppen
            for direction in ["BUY", "SELL"]:
                if direction == "BUY":
                    core = [
                        c['htf_bull'],      # 1. HTF Bias
                        c['struct_bull'],   # 2. Market Structure
                        c['ema_bull'],      # 3. EMA Trend
                        c['high_vol'],      # 4. Volume
                        c['active_sess'],   # 5. Sessie
                        (c['zone_bull']>=1 or c['cand_bull'] or c['liq_bull'])  # 6. Zone OF Candle OF Sweep
                    ]
                else:
                    core = [
                        c['htf_bear'],
                        c['struct_bear'],
                        c['ema_bear'],
                        c['high_vol'],
                        c['active_sess'],
                        (c['zone_bear']>=1 or c['cand_bear'] or c['liq_bear'])
                    ]

                core_score = sum([int(x) for x in core])

                # Signaal als 5 of meer kernfactoren kloppen EN totale score minstens 6/10
                if core_score >= 5:
                    buy_s  = min(a['buy_score'],  10)
                    sell_s = min(a['sell_score'], 10)
                    display_score = buy_s if direction == "BUY" else sell_s

                    # Minimum totale score van 6/10
                    if display_score < 6:
                        continue

                    # Sla op in active_zones voor entry tracking
                    active_zones[pair] = {
                        'direction': direction,
                        'analysis':  a,
                        'df':        df,
                        'core_score': core_score
                    }
                    print(f"📍 {direction} vroeg signaal: {pair} — Kern {core_score}/6")
                    break

            # Verwijder als geen vroege setup meer
            if pair in active_zones:
                stored_dir = active_zones[pair]['direction']
                if stored_dir == "BUY":
                    core_check = [c['htf_bull'], c['struct_bull'], c['ema_bull']]
                else:
                    core_check = [c['htf_bear'], c['struct_bear'], c['ema_bear']]
                if sum([int(x) for x in core_check]) < 2:
                    del active_zones[pair]

        except Exception as e:
            print(f"Scan fout {pair}: {e}")
        await asyncio.sleep(1)

async def scan_entries(bot, min_score=5):
    if not active_zones:
        print(f"⏳ Geen setups [{datetime.now().strftime('%H:%M')}]")
        return

    # Check nieuws blokkering
    blocked, reason = is_news_blocked()
    if blocked:
        print(f"⛔ Entry scan geblokkeerd: {reason}")
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"⛔ TRADE GEBLOKKEERD\n{reason}\nBot wacht tot nieuws voorbij is."
        )
        return

    print(f"🎯 Entry scan [{datetime.now().strftime('%H:%M')}]")
    for pair, zd in list(active_zones.items()):
        try:
            dfh1  = get_data(pair, "1h")
            dfm15 = get_data(pair, "15min")
            if len(dfh1) < 20 or len(dfm15) < 20: continue

            tah1    = TechnicalAnalysis(pair, dfh1)
            atr_avg = dfh1['High'].iloc[-20:].mean() * 0.002
            use_df  = dfh1  if tah1.atr > atr_avg else dfm15
            tf      = "H1"  if tah1.atr > atr_avg else "M15"

            ea        = TechnicalAnalysis(pair, use_df).full_analysis()
            direction = zd['direction']
            ec        = ea['confluence']
            core_score = zd['core_score']

            # Verstuur signaal als kernfactoren kloppen EN score minimum 6/10
            if core_score >= 5:
                display_score = min(ea['buy_score'] if direction=="BUY" else ea['sell_score'], 10)
                ea['buy_score'] = ea['sell_score'] = display_score

                # Stop als score te laag
                if display_score < 6:
                    if pair in active_zones: del active_zones[pair]
                    continue

                msg   = build_signal_message(ea, direction)
                msg  += f"\n📐 Entry TF: {tf}"
                msg  += f"\n⚡ Vroeg signaal — {core_score}/6 kernfactoren"

                # Inline knoppen — genomen of niet
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Genomen", callback_data=f"genomen_{display_score}"),
                    InlineKeyboardButton("⏭ Overgeslagen", callback_data=f"overgeslagen_{display_score}")
                ]])

                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode='Markdown', reply_markup=keyboard)

                conn = sqlite3.connect('trading_bot.db')
                cur  = conn.cursor()
                cur.execute(
                    'INSERT INTO trades (date,pair,direction,entry,sl,tp1,tp2,tp3,score,rr_planned,confluence,session) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (datetime.now().isoformat(), pair, direction, ea['price'],
                     ea['buy_sl']   if direction=="BUY" else ea['sell_sl'],
                     ea['buy_tp1']  if direction=="BUY" else ea['sell_tp1'],
                     ea['buy_tp2']  if direction=="BUY" else ea['sell_tp2'],
                     ea['buy_tp3']  if direction=="BUY" else ea['sell_tp3'],
                     display_score,
                     ea['buy_rr1']  if direction=="BUY" else ea['sell_rr1'],
                     json.dumps(ea['confluence']),
                     ea['confluence']['sess_name'])
                )
                conn.commit()
                conn.close()

                print(f"✅ {direction} signaal: {pair} Kern {core_score}/6 {tf}")
                if pair in active_zones:
                    del active_zones[pair]

        except Exception as e:
            print(f"Entry fout {pair}: {e}")
        await asyncio.sleep(1)

async def full_scan(bot):
    """Volledige scan — zones + entries in één keer"""
    await scan_zones(bot)
    await asyncio.sleep(2)
    await scan_entries(bot)

async def check_missed_signals(bot):
    """Bij opstart: check gemiste signalen"""
    last = get_state('last_scan_time', '')
    if not last: return
    hours = (datetime.now() - datetime.fromisoformat(last)).seconds // 3600
    if hours < 1: return
    print(f"⏰ {hours}u offline — terugscanning...")
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"⏰ Bot was {hours}u offline\n🔍 Terugscanning op gemiste setups...")
    await full_scan(bot)

# ================================================================
# TELEGRAM HANDLERS
# ================================================================
async def cmd_start(update, context):
    await update.message.reply_text(
        "🤖 PRO Signal Bot v5.0 actief!\n\n"
        "Commando's:\n"
        "/best — Beste setup nu\n"
        "/analyse EURUSD — Analyseer een pair\n"
        "/pairs — Alle 27 pairs\n"
        "/stats — Bot statistieken\n"
        "/report — Weekrapport\n"
        "/maand — Maandelijks rapport\n\n"
        "Na elk signaal:\n"
        "/genomen — Trade genomen ✅\n"
        "/overgeslagen — Trade overgeslagen ⏭\n\n"
        "✅ Win/loss automatisch gedetecteerd!\n"
        "Of stel gewoon een vraag! 💬"
    )

async def cmd_genomen(update, context):
    """Markeer laatste signaal als genomen"""
    trade_id = get_last_signal_id()
    if trade_id == 0:
        await update.message.reply_text("❌ Geen recent signaal gevonden.")
        return
    mark_trade_taken(trade_id, True)
    await update.message.reply_text(f"✅ Trade #{trade_id} gemarkeerd als GENOMEN!\nBot houdt het resultaat bij. 💪")

async def cmd_overgeslagen(update, context):
    """Markeer laatste signaal als overgeslagen"""
    trade_id = get_last_signal_id()
    if trade_id == 0:
        await update.message.reply_text("❌ Geen recent signaal gevonden.")
        return
    mark_trade_taken(trade_id, False)
    await update.message.reply_text(f"⏭ Trade #{trade_id} gemarkeerd als OVERGESLAGEN.\nOk, volgende keer beter! 👀")

async def cmd_maand(update, context):
    """Maandelijks rapport op verzoek"""
    await update.message.reply_text(generate_monthly_report())

async def handle_callback(update, context):
    """Verwerkt knop klikken — genomen of overgeslagen"""
    query    = update.callback_query
    await query.answer()
    data     = query.data
    trade_id = get_last_signal_id()

    if data.startswith("genomen"):
        mark_trade_taken(trade_id, True)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"✅ Trade gemarkeerd als GENOMEN! Bot houdt resultaat bij. 💪")
    elif data.startswith("overgeslagen"):
        mark_trade_taken(trade_id, False)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"⏭ Trade overgeslagen. Ok, volgende keer! 👀")

async def cmd_best(update, context):
    await update.message.reply_text(f"🔍 Scanning alle {len(PAIRS)} pairs... (±1 min)")

    # Check nieuws blokkering
    blocked, reason = is_news_blocked()
    if blocked:
        await update.message.reply_text(f"⛔ {reason}\nGeen signalen tijdens high impact nieuws!")

    results = []
    for pair in PAIRS.keys():
        try:
            df = get_data(pair, "4h")
            if len(df) < 50: continue
            a  = TechnicalAnalysis(pair, df).full_analysis()
            bs = max(a['buy_score'], a['sell_score'])
            results.append((pair, "BUY 🟢" if a['buy_score'] >= a['sell_score'] else "SELL 🔴", bs, a, df))
        except: continue
        await asyncio.sleep(0.5)

    if not results:
        await update.message.reply_text("❌ Geen data beschikbaar.")
        return

    results.sort(key=lambda x: x[2], reverse=True)
    top5 = results[:5]

    msg = "🏆 TOP 5 BESTE SETUPS NU\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, (pair, d, s, _, __) in enumerate(top5):
        emoji = "🔥" if s >= 6 else ""
        msg += f"{i+1}. {pair} {d} — {min(s,10)}/10 {emoji}\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━\n💡 /analyse {top5[0][0]} voor details!"
    await update.message.reply_text(msg)

    # Stuur automatisch signaal voor pairs met score 6+
    signals_sent = 0
    for pair, direction, score, analysis, df in results:
        if min(score, 10) >= 7 and signals_sent < 3:
            dir_clean = "BUY" if "BUY" in direction else "SELL"
            analysis['buy_score'] = analysis['sell_score'] = min(score, 10)
            msg_signal = build_signal_message(analysis, dir_clean)
            msg_signal += f"\n⚡ Setup gevonden via /best"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Genomen", callback_data=f"genomen_{min(score,10)}"),
                InlineKeyboardButton("⏭ Overgeslagen", callback_data=f"overgeslagen_{min(score,10)}")
            ]])
            await update.message.reply_text(msg_signal, parse_mode='Markdown', reply_markup=keyboard)
            signals_sent += 1
            await asyncio.sleep(1)

    if signals_sent == 0:
        await update.message.reply_text("⏳ Geen setups met score 6+ gevonden. Probeer later opnieuw!")

async def cmd_analyse(update, context):
    pair = "ONBEKEND"
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Gebruik: /analyse EURUSD")
            return
        pair = args[0].upper()
        if pair not in PAIRS:
            await update.message.reply_text(f"❌ {pair} niet gevonden. Gebruik /pairs voor de lijst.")
            return
        await update.message.reply_text(f"🔍 Analyseer {pair}...")
        df = get_data(pair, "4h")
        if len(df) < 50:
            await update.message.reply_text(f"❌ Niet genoeg data voor {pair}")
            return
        a  = TechnicalAnalysis(pair, df).full_analysis()
        bs = min(a['buy_score'],  10)
        ss = min(a['sell_score'], 10)
        c  = a['confluence']
        buy_checks = [
            (c['htf_bull'],     "HTF Bias bullish"),
            (c['struct_bull'],  "Market Structure BOS"),
            (c['zone_bull']>=1, f"Zone: {c['zone_bull_lbl']}"),
            (c['fib_bull'],     "Fibonacci 0.618/0.705"),
            (c['liq_bull'],     "Liquidity Sweep"),
            (c['rsi_bull'],     "RSI Divergence"),
            (c['high_vol'],     "Volume +30%"),
            (c['active_sess'],  f"Sessie: {c['sess_name']}"),
            (c['cand_bull'],    f"Candle: {c['cand_bull_nm']}"),
            (c['dxy_bear'],     "DXY zwak"),
            (c['ema_bull'],     "EMA trend bullish"),
        ]
        sell_checks = [
            (c['htf_bear'],     "HTF Bias bearish"),
            (c['struct_bear'],  "Market Structure BOS"),
            (c['zone_bear']>=1, f"Zone: {c['zone_bear_lbl']}"),
            (c['fib_bear'],     "Fibonacci 0.618/0.705"),
            (c['liq_bear'],     "Liquidity Sweep"),
            (c['rsi_bear'],     "RSI Divergence"),
            (c['high_vol'],     "Volume +30%"),
            (c['active_sess'],  f"Sessie: {c['sess_name']}"),
            (c['cand_bear'],    f"Candle: {c['cand_bear_nm']}"),
            (c['dxy_bull'],     "DXY sterk"),
            (c['ema_bear'],     "EMA trend bearish"),
        ]
        best_checks = buy_checks if bs >= ss else sell_checks
        checklist   = "\n".join([f"{'✅' if ok else '❌'} {lbl}" for ok, lbl in best_checks])
        msg = (f"📊 ANALYSE — {pair}\n"
               f"━━━━━━━━━━━━━━━━━━━━━━\n"
               f"💰 Prijs: {a['price']:.5f}\n"
               f"🟢 BUY:  {bs}/10\n"
               f"🔴 SELL: {ss}/10\n"
               f"━━━━━━━━━━━━━━━━━━━━━━\n"
               f"{'🟢 BUY' if bs >= ss else '🔴 SELL'} CHECKLIST:\n"
               f"{checklist}\n"
               f"━━━━━━━━━━━━━━━━━━━━━━\n")
        if bs >= 8:   msg += f"✅ BUY setup! Score {bs}/10"
        elif ss >= 8: msg += f"✅ SELL setup! Score {ss}/10"
        else:         msg += f"⏳ Nog geen setup — wacht op meer confluence"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Fout bij {pair}: {str(e)}")

async def cmd_pairs(update, context):
    await update.message.reply_text("📋 ACTIEVE PAIRS (27):\n\n"+"\n".join([f"• {p}" for p in PAIRS.keys()]))

async def cmd_stats(update, context):
    await update.message.reply_text(AILearningSystem().get_insights())

async def cmd_report(update, context):
    await update.message.reply_text(generate_weekly_report())

async def handle_message(update, context):
    q = update.message.text.lower()
    for p in PAIRS.keys():
        if p.lower() in q:
            context.args = [p]
            await cmd_analyse(update, context)
            return
    if any(w in q for w in ['stats','winrate','statistieken']):
        await cmd_stats(update, context)
    elif any(w in q for w in ['rapport','report','week']):
        await cmd_report(update, context)
    elif any(w in q for w in ['best','beste','setup']):
        await cmd_best(update, context)
    elif any(w in q for w in ['pairs','lijst']):
        await cmd_pairs(update, context)
    else:
        await update.message.reply_text("Ik begrijp je vraag! 💬\n\nProbeer:\n• /best\n• /analyse EURUSD\n• /stats\n• /report")

# ================================================================
# SCHEDULER
# ================================================================
def run_scheduler(bot, loop):
    schedule.every().day.at("19:00").do(lambda: asyncio.run_coroutine_threadsafe(send_evening_briefing(bot),loop))
    schedule.every().friday.at("20:00").do(lambda: asyncio.run_coroutine_threadsafe(bot.send_message(chat_id=TELEGRAM_CHAT_ID,text=generate_weekly_report()),loop))
    schedule.every(30).minutes.do(lambda: asyncio.run_coroutine_threadsafe(full_scan(bot),loop))
    schedule.every(2).hours.do(lambda: asyncio.run_coroutine_threadsafe(check_trade_results(bot),loop))
    # Maandrapport — elke laatste dag van de maand om 20:00
    schedule.every().day.at("20:00").do(lambda: asyncio.run_coroutine_threadsafe(_check_month_end(bot),loop))
    while True: schedule.run_pending(); time.sleep(60)

async def _check_month_end(bot):
    """Check of het laatste dag van de maand is"""
    now       = datetime.now()
    last_day  = (now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    last_sent = get_state('last_monthly_report', '')
    current_m = now.strftime('%Y-%m')
    if now.day == last_day.day and last_sent != current_m:
        await send_monthly_report(bot)

# ================================================================
# MAIN
# ================================================================
async def main():
    print("🤖 PRO Signal Bot v5.0 starten...")
    init_database()
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("best",        cmd_best))
    app.add_handler(CommandHandler("analyse",     cmd_analyse))
    app.add_handler(CommandHandler("pairs",       cmd_pairs))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("report",      cmd_report))
    app.add_handler(CommandHandler("maand",       cmd_maand))
    app.add_handler(CommandHandler("genomen",     cmd_genomen))
    app.add_handler(CommandHandler("overgeslagen",cmd_overgeslagen))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot=app.bot; loop=asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(check_missed_briefing(bot),       loop)
    asyncio.run_coroutine_threadsafe(check_missed_signals(bot),        loop)
    asyncio.run_coroutine_threadsafe(check_missed_monthly_report(bot), loop)
    asyncio.run_coroutine_threadsafe(full_scan(bot),                   loop)
    scheduler_thread=threading.Thread(target=run_scheduler,args=(bot,loop),daemon=True)
    scheduler_thread.start()
    print("✅ Bot actief! Wachtend op signalen en berichten...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
