import os
import time
from binance.client import Client
from binance.enums import *
from dotenv import load_dotenv
from utils import calculate_ema, calculate_rsi

# ✅ 환경 변수 로드 (.env 파일에서 API 키 읽기)
load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")

# ✅ 바이낸스 클라이언트 생성
client = Client(api_key, secret_key)

# ✅ 거래 전략 파라미터
TAKE_PROFIT = 3.0   # % 수익 시 매도
STOP_LOSS = -2.0    # % 손실 시 매도

# ✅ 거래량 급등 + 필터 조건 확인
def get_buy_candidates():
    symbols = [s['symbol'] for s in client.get_ticker_24hr() if s['symbol'].endswith('USDT')]
    candidates = []

    for symbol in symbols:
        try:
            klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=65)
            closes = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            avg_volume = sum(volumes[:-5]) / len(volumes[:-5])
            last_volume = volumes[-1]
            volume_spike = last_volume / avg_volume if avg_volume > 0 else 0

            if volume_spike < 5.0:
                continue

            current_price = closes[-1]
            ema15 = calculate_ema(closes, 15)
            ema50 = calculate_ema(closes, 50)
            rsi = calculate_rsi(closes)

            if not (ema15 and ema50 and rsi):
                continue

            if ema15 < ema50 or rsi > 80 or current_price > sum(closes[:-5]) / len(closes[:-5]) * 1.05:
                continue

            candidates.append({
                "symbol": symbol,
                "price": current_price,
                "ema15": ema15,
                "ema50": ema50,
                "rsi": rsi,
                "volume_spike": round(volume_spike, 2)
            })
        except Exception as e:
            continue

    return sorted(candidates, key=lambda x: x["volume_spike"], reverse=True)

# ✅ 시장가 매수 주문
def place_market_buy(symbol: str, usdt_amount: float) -> float | None:
    try:
        price = float(client.get_symbol_ticker(symbol=symbol)['price'])
        quantity = round(usdt_amount / price, 6)
        order = client.order_market_buy(
            symbol=symbol,
            quantity=quantity
        )
        return price
    except Exception as e:
        print(f"매수 오류: {e}")
        return None

# ✅ 시장가 매도 주문
def place_market_sell(symbol: str, quantity: float) -> None:
    try:
        client.order_market_sell(
            symbol=symbol,
            quantity=quantity
        )
        print(f"{symbol} 매도 완료")
    except Exception as e:
        print(f"매도 오류: {e}")

# ✅ 자동 익절/손절 감시 루프
def monitor_trade(symbol: str, entry_price: float, quantity: float):
    print(f"📊 {symbol} 감시 시작 (진입가: {entry_price})")

    while True:
        try:
            price = float(client.get_symbol_ticker(symbol=symbol)['price'])
            change = ((price - entry_price) / entry_price) * 100

            print(f"현재가: {price:.4f} | 수익률: {change:.2f}%")

            if change >= TAKE_PROFIT:
                place_market_sell(symbol, quantity)
                print("💰 익절 완료!")
                break
            elif change <= STOP_LOSS:
                place_market_sell(symbol, quantity)
                print("💥 손절 완료!")
                break

            time.sleep(5)
        except Exception as e:
            print(f"오류 발생: {e}")
            time.sleep(5)
