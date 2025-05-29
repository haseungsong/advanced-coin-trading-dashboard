from flask import Flask
import threading
import time
from trade_logic import get_buy_candidates, place_market_buy, monitor_trade

# ✅ 매매 루프 설정
USDT_AMOUNT = 1.0           # 매수에 사용할 USDT 금액
CHECK_INTERVAL = 60         # 거래 조건 체크 주기 (초)

app = Flask(__name__)

@app.route('/')
def index():
    return "✅ Coin auto-trading bot is running"

def run_bot():
    print("🚀 자동 거래 봇 시작")

    while True:
        try:
            print("🔍 매수 후보 검색 중...")
            candidates = get_buy_candidates()

            if not candidates:
                print("⚠️ 조건에 맞는 코인이 없습니다.")
            else:
                coin = candidates[0]
                print(f"🎯 선택된 코인: {coin['symbol']} (현재가: {coin['price']})")

                price = place_market_buy(coin["symbol"], USDT_AMOUNT)

                if price:
                    quantity = round(USDT_AMOUNT / price, 6)
                    monitor_trade(coin["symbol"], price, quantity)
                else:
                    print("❌ 매수 실패, 다음 기회 대기 중")

            print(f"⏱ {CHECK_INTERVAL}초 후 다음 탐색...")
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"❗ 오류 발생: {e}")
            time.sleep(10)

if __name__ == "__main__":
    # 봇 로직을 백그라운드 쓰레드로 실행
    threading.Thread(target=run_bot).start()

    # 웹 서버 포트 바인딩 (Render용)
    app.run(host="0.0.0.0", port=10000)
