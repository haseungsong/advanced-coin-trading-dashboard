# 🚀 Auto Trade Dashboard

간단한 한 줄 설명:  
Binance API와 Streamlit, CCXT, VectorBT 등을 이용한 고급 자동거래 대시보드입니다.

---

## 📌 목차
1. [프로젝트 개요](#프로젝트-개요)  
2. [설치 방법](#설치-방법)  
3. [환경 변수 설정](#환경-변수-설정)  
4. [실행 방법](#실행-방법)  
5. [파일 구성](#파일-구성)  
6. [권한 설정](#권한-설정)  
7. [기능 설명](#기능-설명)  
8. [라이선스](#라이선스)

---

## 프로젝트 개요
- Binance 선물 시장에 연결하여  
- EMA, RSI, Bollinger, KDJ 등 멀티 타임프레임 지표 기반  
- 자동 매수·예약·OCO 매도 실행  
- WebSocket 실시간 시세, VectorBT 백테스트, SQLite 로그, Telegram 알림  
- Streamlit UI 탭으로 “실시간 대시보드 / 백테스트 / 로그 & PnL” 제공

---

## 설치 방법
```bash
git clone https://github.com/YourUsername/auto-trade-dashboard.git
cd auto-trade-dashboard
pip install -r requirements.txt
