# app.py (Part 1/3)

# ─── 0. 스케줄러 초기화 ────────────────────────────────────────────────
from apscheduler.schedulers.background import BackgroundScheduler
sched = BackgroundScheduler()
sched.start()

# ─── 1. 필수 라이브러리 import ─────────────────────────────────────────
import os, time, threading, sqlite3
from datetime import datetime, date
import pandas as pd, numpy as np, ccxt, streamlit as st
from binance import ThreadedWebsocketManager
import vectorbt as vbt, plotly.graph_objects as go

# vectorbt의 Telegram 백엔드 비활성화
os.environ["VBT_MESSAGING_TELEGRAM_ENABLED"] = "0"

# ─── 2. Streamlit 페이지 설정 ────────────────────────────────────────────
st.set_page_config(
    page_title="고급 코인 자동거래 대시보드",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.title("🚀 고급 코인 자동거래 대시보드")

# ─── 3. 사이드바 위젯 ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ 주문 금액 설정")
    amnt_usdt = st.number_input("주문당 USDT", min_value=0.1, value=1.0, step=0.1)

    st.markdown("---")
    st.markdown("## ⚙️ 볼륨·반등 필터 설정")
    vol_mult    = st.number_input("볼륨스파이크 배수", min_value=1.0, value=3.0, step=0.5)
    rebound_pct = st.number_input("저점 대비 반등(%)", min_value=0.1, value=0.5, step=0.1) / 100

    st.markdown("---")
    auto_trade = st.checkbox("자동진입/청산 실행", value=False)

    take_profit_pct = st.number_input(
        "익절 퍼센트(%)", min_value=1.0, max_value=100.0, value=50.0, step=1.0
    ) / 100

# 바로 TAKE_PROFIT_PCT 변수에 반영
TAKE_PROFIT_PCT = take_profit_pct

# app.py (Part 2/3)

# ─── 4. Secrets 및 CCXT 거래소 초기화 ───────────────────────────────────
BINANCE_API_KEY    = st.secrets["BINANCE_API_KEY"]
BINANCE_SECRET_KEY = st.secrets["BINANCE_SECRET_KEY"]

exchange = ccxt.binance({
    'apiKey':  BINANCE_API_KEY,
    'secret':  BINANCE_SECRET_KEY,
    'options': {'defaultType': 'spot'},
})
exchange.load_markets()

# WS 매니저 (실시간 trade stream)
twm = ThreadedWebsocketManager(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
twm.start()

# ─── 5. 실시간 가격 저장용 세션 스테이트 ────────────────────────────────
if 'realtime' not in st.session_state:
    st.session_state['realtime'] = {}

# ─── 6. SQLite 설정 & 유틸 함수 ──────────────────────────────────────────
conn = sqlite3.connect('trade_logs.db', check_same_thread=False)
c    = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS orders (
    ts TEXT, symbol TEXT, side TEXT, price REAL, size REAL, type TEXT
)""")
c.execute("""
CREATE TABLE IF NOT EXISTS pnl (
    day TEXT PRIMARY KEY, realized REAL
)""")
conn.commit()

def log_order(ts, symbol, side, price, size, type_):
    c.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
              (ts, symbol, side, price, size, type_))
    conn.commit()

def update_pnl(day: str, pnl: float):
    c.execute(
        "INSERT INTO pnl(day, realized) VALUES (?,?) "
        "ON CONFLICT(day) DO UPDATE SET realized=realized+?",
        (day, pnl, pnl)
    )
    conn.commit()

def get_today_realized():
    today = date.today().isoformat()
    c.execute("SELECT realized FROM pnl WHERE day=?", (today,))
    r = c.fetchone()
    return r[0] if r else 0.0

# ─── 7. 지표 계산 함수 ───────────────────────────────────────────────────
def calculate_indicators(df: pd.DataFrame):
    df = df.copy()
    df['EMA15'] = df['close'].ewm(span=15).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    df_hour     = df['close'].resample('1H').last().ffill()
    rsi         = vbt.RSI.run(df_hour, window=14)
    df['RSI1H'] = rsi.rsi.reindex(df.index, method='ffill')
    # Bollinger
    w, m = 20, 2
    mu = df['close'].rolling(w).mean()
    sd = df['close'].rolling(w).std()
    df['BB_upper'] = mu + m * sd
    df['BB_lower'] = mu - m * sd
    # KDJ
    h9 = df['high'].rolling(9).max()
    l9 = df['low'].rolling(9).min()
    df['K'] = 100 * (df['close'] - l9) / (h9 - l9)
    df['D'] = df['K'].ewm(span=3).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    # ATR & BB 폭
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low']  - df['close'].shift(1)).abs()
    df['TR']       = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR']      = df['TR'].rolling(14).mean()
    df['BB_width'] = df['BB_upper'] - df['BB_lower']
    return df.dropna(subset=['EMA15','EMA50','BB_upper','BB_lower','ATR'])

# ─── 8. 백테스트 함수 ────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def fetch_and_indicator(symbol: str, timeframe: str) -> pd.DataFrame:
    ohlc = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=1000)
    df   = pd.DataFrame(ohlc, columns=['ts','open','high','low','close','vol'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df.set_index('ts', inplace=True)
    return calculate_indicators(df)

def run_backtest(symbol: str, timeframe: str, params) -> tuple[pd.DataFrame, vbt.Portfolio]:
    df      = fetch_and_indicator(symbol, timeframe)
    entries = df['EMA15'] > df['EMA50']
    exits   = df['EMA15'] < df['EMA50']
    pf      = vbt.Portfolio.from_signals(
                  df['close'], entries, exits,
                  init_cash=10000, fees=0.0005
              )
    return df, pf

# ─── 9. WS 핸들러 및 심볼 구독 ──────────────────────────────────────────
def handle_trade(msg):
    symbol = msg['s']; price = float(msg['p'])
    st.session_state['realtime'][symbol] = price

@st.cache_data(show_spinner=False)
def get_top_coins_by_volume(n: int = 200, quote: str = "USDT"):
    tickers = exchange.fetch_tickers()
    data    = [
        (sym, tk.get('quoteVolume') or 0)
        for sym, tk in tickers.items() if sym.endswith(f"/{quote}")
    ]
    top     = sorted(data, key=lambda x: x[1], reverse=True)[:n]
    return [sym for sym, _ in top]

start_symbols = get_top_coins_by_volume()

def start_ws(symbols):
    for sym in symbols:
        twm.start_trade_socket(callback=handle_trade, symbol=sym.replace('/', ''))

start_ws(start_symbols)

# app.py (Part 3/3)

# ─── 10. scan_and_trade 함수 ─────────────────────────────────────────────
def scan_and_trade():
    for sym in start_symbols:
        ohlc      = exchange.fetch_ohlcv(sym, "1m", limit=65)
        df60      = pd.DataFrame(ohlc, columns=['ts','o','h','l','c','vol'])
        df60['vol_ma60'] = df60['vol'].rolling(60).mean()
        last_vol  = df60['vol'].iloc[-1]
        avg_vol60 = df60['vol_ma60'].iloc[-1]
        last_price= df60['c'].iloc[-1]
        low5      = df60['l'].iloc[-6:-1].min()
        high5     = df60['h'].iloc[-6:-1].max()

        if last_vol > vol_mult * avg_vol60 and (
           last_price > low5 * (1 + rebound_pct) or last_price > high5
        ):
            size = amnt_usdt / last_price
            # 자동 매수
            try:
                order = exchange.create_order(
                    symbol=sym, type="market", side="buy",
                    amount=round(size,6)
                )
                log_order(datetime.now().isoformat(),
                          sym, "buy", last_price, size, "market")
            except Exception as e:
                print("Auto buy failed", e)
            # 익절 잡 등록
            def tp_job(sym=sym, entry=last_price, sz=size):
                tick = exchange.fetch_ticker(sym)["last"]
                if tick >= entry * (1 + take_profit_pct):
                    so = exchange.create_order(
                        symbol=sym, type="market", side="sell",
                        amount=round(sz,6)
                    )
                    log_order(datetime.now().isoformat(),
                              sym, "sell", tick, sz, "market")
                    sched.remove_job(f"tp_{sym}")
            sched.add_job(tp_job, 'interval', seconds=1,
                          id=f"tp_{sym}", replace_existing=True)

# ─── 11. auto_trade 토글 처리 ───────────────────────────────────────────
if auto_trade:
    sched.add_job(scan_and_trade, 'interval',
                  seconds=30, id="scan_trade",
                  replace_existing=True)
else:
    try:
        sched.remove_job("scan_trade")
    except:
        pass

# ─── 12. Streamlit UI: 탭별 화면 ────────────────────────────────────────
tabs = st.tabs(["실시간 대시보드","백테스트","로그 & PnL"])

# ----- 탭 1: 실시간 대시보드 --------------------------------------------
with tabs[0]:
    st.header("📈 실시간 모니터링")
    bal    = exchange.fetch_balance()
    wallet = bal['total']['USDT']
    unreal = 0.0
    st.metric("지갑 잔액 (USDT)", f"{wallet:.2f}")
    st.metric("미실현 손익 (USDT)", f"{unreal:.2f}")

    st.subheader("🔔 추천 매수/매도 시그널")
    signals = []
    # enumerate로 순위(rank)까지 가져오기
    for rank, sym in enumerate(start_symbols, start=1):
        # 최소 주문 필터
        min_cost = exchange.markets[sym]['limits']['cost']['min'] or 0
        if min_cost > amnt_usdt:
            continue

        # 볼륨·반등 조건 체크
        ohlc = exchange.fetch_ohlcv(sym, "1m", limit=60)
        df60 = pd.DataFrame(ohlc, columns=['ts','o','h','l','c','vol'])
        df60['vol_ma60'] = df60['vol'].rolling(60).mean()
        last_vol   = df60['vol'].iloc[-1]
        avg_vol60  = df60['vol_ma60'].iloc[-1]
        last_price = df60['c'].iloc[-1]
        low5  = df60['l'].iloc[-6:-1].min()
        high5 = df60['h'].iloc[-6:-1].max()

        if last_vol > vol_mult * avg_vol60 and (
           last_price > low5 * (1 + rebound_pct) or last_price > high5
        ):
            size = amnt_usdt / last_price

            # 이유 문자열 생성
            cond_bounce = last_price > low5 * (1 + rebound_pct)
            cond_break  = last_price > high5
            parts = [f"거래량 {last_vol/avg_vol60:.1f}x"]
            if cond_bounce: parts.append(f"저점 대비 {rebound_pct*100:.1f}% 반등")
            if cond_break:  parts.append("고점 돌파")
            reason = " + ".join(parts)

            # 순위, 실시간 표시 추가
            signals.append({
                "rank":      rank,
                "sym":       sym,
                "price":     last_price,
                "vol_spike": f"{last_vol/avg_vol60:.1f}x",
                "action":    f"BUY ({reason})",
                "live":      "✅"
            })

            # 자동매수 처리 (체크박스 on일 때만)
            if auto_trade:
                try:
                    o = exchange.create_order(
                        symbol=sym, type="market", side="buy",
                        amount=round(size,6)
                    )
                    log_order(datetime.now().isoformat(),
                              sym, "buy", last_price, size, "market")
                    st.success(f"[Auto] {sym} 매수: {o['filled']}")
                except Exception as e:
                    st.error(f"[Auto] {sym} 매수실패: {e}")

    # 테이블 출력
    if signals:
        df_sig = pd.DataFrame(signals).rename(columns={
            "rank":      "순위",
            "sym":       "심볼",
            "price":     "현재가",
            "vol_spike": "볼륨배수",
            "action":    "추천",
            "live":      "실시간"
        })
        st.table(df_sig[["순위","심볼","현재가","볼륨배수","추천","실시간"]])
    else:
        st.write("현재 매수 추천이 없습니다.")

    # 실시간 캔들 차트
    for sym, price in st.session_state['realtime'].items():
        st.subheader(f"{sym} 현재가: {price:.4f}")
        raw = exchange.fetch_ohlcv(sym, "1m", limit=100)
        df  = pd.DataFrame(raw, columns=['ts','o','h','l','c','v'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        df.set_index('ts', inplace=True)
        fig = go.Figure([go.Candlestick(
            x=df.index, open=df['o'], high=df['h'],
            low=df['l'], close=df['c']
        )])
        fig.update_layout(height=300, xaxis_rangeslider_visible=True)
        st.plotly_chart(fig, use_container_width=True)


# ----- 탭 2: 백테스트 --------------------------------------------
with tabs[1]:
    st.header("🧪 전략 백테스트")
    bt_sym = st.selectbox("심볼 선택", start_symbols)
    bt_tf  = st.selectbox("타임프레임", ["1m","5m","15m","1h"])
    if st.button("백테스트 실행"):
        df_bt, pf = run_backtest(bt_sym, bt_tf, {})
        st.subheader("수익 곡선")
        fig_eq = go.Figure(go.Scatter(
            x=pf.value().index, y=pf.value().values
        ))
        st.plotly_chart(fig_eq, use_container_width=True)
        stats = pf.stats()
        st.write(f"▶ 총 수익률: {stats['Total Return [%]']:.2f}%")
        st.write(f"▶ 최대 낙폭: {stats['Max Drawdown [%]']:.2f}%")
        st.write(f"▶ 승률: {stats['Win Rate [%]']:.2f}%")

# ----- 탭 3: 로그 & PnL --------------------------------------------
with tabs[2]:
    st.header("📝 주문 로그 & PnL")
    df_orders = pd.read_sql("SELECT * FROM orders ORDER BY ts DESC LIMIT 50", conn)
    st.subheader("최근 주문 로그")
    st.dataframe(df_orders)
    df_pnl = pd.read_sql("SELECT * FROM pnl ORDER BY day DESC", conn)
    st.subheader("일별 실현 PnL")
    st.bar_chart(df_pnl.set_index('day')['realized'])

# ─── 13. 종료 처리 ───────────────────────────────────────────────────────
def shutdown():
    twm.stop()
    conn.close()
