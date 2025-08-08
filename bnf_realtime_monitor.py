# bnf_realtime_monitor.py
"""
BNF 역추세 전략 실시간 모니터링 시스템
- 타카시 코테가와(BNF) 스타일 역추세 전략
- 과매수/과매도 반전 포착
- 2-3일 단기 스윙 트레이딩
- 텔레그램 알림 시스템
"""

import asyncio
import logging
import os
import re
import threading
import time
import warnings
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd
import pytz
import requests
import yfinance as yf
from telegram.ext import Application, CommandHandler

warnings.filterwarnings('ignore')


class BNFCounterTrendMonitor:
  def __init__(self, telegram_bot_token: str = None, telegram_chat_id: str = None):
    """
    BNF 역추세 전략 모니터링 시스템 (백테스트와 파라미터 통일)

    Parameters:
    telegram_bot_token: 텔레그램 봇 토큰
    telegram_chat_id: 텔레그램 채팅 ID
    """
    self.telegram_bot_token = telegram_bot_token
    self.telegram_chat_id = telegram_chat_id

    # Ticker-to-Korean-name mapping (미국 시총 50위)
    self.ticker_to_korean = {
      'AAPL': '애플', 'MSFT': '마이크로소프트', 'GOOGL': '구글', 'AMZN': '아마존',
      'NVDA': '엔비디아', 'META': '메타', 'TSLA': '테슬라', 'BRK-B': '버크셔',
      'AVGO': '브로드컴', 'LLY': '일라이 릴리', 'JPM': 'JP모건', 'UNH': '유나이티드헬스',
      'XOM': '엑슨모빌', 'V': '비자', 'PG': '프록터앤갬블', 'JNJ': '존슨앤존슨',
      'MA': '마스터카드', 'HD': '홈디포', 'CVX': '쉐브론', 'MRK': '머크',
      'ABBV': '애브비', 'KO': '코카콜라', 'ADBE': '어도비', 'PEP': '펩시코',
      'COST': '코스트코', 'WMT': '월마트', 'BAC': '뱅크오브아메리카', 'CRM': '세일즈포스',
      'TMO': '써모피셔', 'NFLX': '넷플릭스', 'ACN': '액센추어', 'LIN': '린데',
      'MCD': '맥도날드', 'ABT': '애보트', 'CSCO': '시스코', 'AMD': 'AMD',
      'PM': '필립모리스', 'TXN': '텍사스인스트루먼츠', 'DHR': '다나허', 'DIS': '디즈니',
      'INTC': '인텔', 'VZ': '버라이즌', 'WFC': '웰스파고', 'COP': '코노코필립스',
      'BMY': '브리스톨마이어스', 'NOW': '서비스나우', 'CAT': '캐터필러', 'NEE': '넥스트에라',
      'UPS': 'UPS', 'RTX': 'RTX'
    }

    # 모니터링 대상 종목 (BNF처럼 엄선된 50개)
    self.watchlist = list(self.ticker_to_korean.keys())

    # BNF 전략 파라미터 (백테스트와 동일하게 수정)
    self.rsi_period = 14
    self.williams_period = 14
    self.ema_short = 20
    self.ema_long = 25  # BNF가 사용한 25일 이동평균
    self.volume_ma_period = 20

    # BNF 신호 임계값 (백테스트와 동일)
    self.rsi_oversold = 35      # 완화된 설정
    self.rsi_overbought = 65    # 완화된 설정
    self.williams_oversold = -75
    self.williams_overbought = -25
    self.volume_threshold = 1.2

    # BNF 핵심: 25일 이동평균 대비 하락률
    self.ma_oversold_threshold = 0.80  # 25일 평균 대비 20% 하락

    # 알림 설정
    self.last_alerts = {}
    self.alert_cooldown = 3600  # 1시간 쿨다운

    # Heartbeat 설정
    self.heartbeat_interval = 3600
    self.last_heartbeat = datetime.now()
    self.heartbeat_thread = None
    self.scan_count = 0
    self.total_signals_sent = 0
    self.last_signal_time = None
    self.start_time = None

    # 성능 최적화를 위한 캐싱
    self.market_time_cache = {}
    self.market_time_cache_expiry = None

    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
          logging.FileHandler('bnf_trading_monitor.log'),
          logging.StreamHandler()
        ]
    )
    self.logger = logging.getLogger(__name__)

    # 모니터링 상태
    self.is_monitoring = False
    self.monitor_thread = None

    # Telegram bot application
    self.telegram_app = None
    self.telegram_running = False
    if self.telegram_bot_token:
      try:
        self.telegram_app = Application.builder().token(self.telegram_bot_token).build()
        self.telegram_app.add_handler(CommandHandler("start", self.start_command))
        self.telegram_app.add_handler(CommandHandler("ticker", self.ticker_command))
        self.telegram_app.add_handler(CommandHandler("status", self.status_command))
        self.logger.info("✅ Telegram bot handlers added successfully")
      except Exception as e:
        self.logger.error(f"❌ Telegram bot initialization failed: {e}")
        self.telegram_app = None

    # BNF 스타일 포지션 관리
    self.positions = {}  # {symbol: {'status': 'none'|'holding', 'entry_price': float, 'entry_time': datetime, 'target_days': 2-3}}

  def get_position_status(self, symbol: str) -> str:
    """포지션 상태 조회"""
    return self.positions.get(symbol, {}).get('status', 'none')

  def update_position(self, symbol: str, status: str, price: float = None):
    """포지션 상태 업데이트"""
    if symbol not in self.positions:
      self.positions[symbol] = {}

    self.positions[symbol]['status'] = status

    if status == 'holding' and price:
      self.positions[symbol]['entry_price'] = price
      self.positions[symbol]['entry_time'] = datetime.now()
      self.positions[symbol]['target_days'] = 3  # BNF 스타일: 최대 3일
    elif status == 'none':
      self.positions[symbol].pop('entry_price', None)
      self.positions[symbol].pop('entry_time', None)
      self.positions[symbol].pop('target_days', None)

  async def start_command(self, update, context):
    """Handle /start command."""
    try:
      welcome_message = (
        "🤖 <b>BNF Counter-Trend Trading Bot</b>\n\n"
        "📊 Available Commands:\n"
        "• /ticker &lt;symbol&gt; - Analyze a stock (e.g., /ticker AAPL)\n"
        "• /status - Show monitoring status\n"
        "• /start - Show this help message\n\n"
        f"🔍 Monitoring Status: {'🟢 Running' if self.is_monitoring else '🔴 Stopped'}\n"
        f"📈 Watching {len(self.watchlist)} stocks\n"
        f"📱 Total alerts sent: {self.total_signals_sent}\n\n"
        "🎯 <b>BNF Strategy:</b> Counter-trend reversal trading\n"
        "💡 <b>Example:</b> /ticker AAPL or /ticker tsla"
      )

      await update.message.reply_text(welcome_message, parse_mode='HTML')
      self.logger.info(
        f"Sent welcome message to user {update.effective_user.id}")
    except Exception as e:
      self.logger.error(f"Error in start_command: {e}")
      await update.message.reply_text(
        "Sorry, an error occurred. Please try again.")

  async def ticker_command(self, update, context):
    """Handle /ticker command to analyze a specific stock."""
    try:
      self.logger.info(
        f"Received ticker command from user {update.effective_user.id}: {context.args}")

      if not context.args:
        await update.message.reply_text(
            "❌ Please provide a ticker symbol.\n\n"
            "💡 <b>Usage:</b> /ticker &lt;symbol&gt;\n"
            "📊 <b>Examples:</b>\n"
            "• /ticker AAPL\n"
            "• /ticker tsla\n"
            "• /ticker GOOGL\n\n"
            "🎯 <b>BNF Strategy:</b> Looking for counter-trend reversals",
            parse_mode='HTML'
        )
        return

      ticker = context.args[0].upper().strip()
      self.logger.info(f"Processing BNF analysis for ticker: {ticker}")

      # 진행 상황 알림
      progress_message = await update.message.reply_text(
          f"🔍 <b>BNF Analysis for {ticker}...</b>\n⏳ Checking reversal signals...",
          parse_mode='HTML'
      )

      # 데이터 가져오기 및 분석
      signals = self.check_bnf_signals(ticker)

      if not signals:
        await progress_message.edit_text(
            f"❌ <b>No data available for {ticker}</b>\n\n"
            "💡 Please check if the ticker symbol is correct.\n"
            "📊 Try popular tickers like: AAPL, MSFT, GOOGL, AMZN, TSLA",
            parse_mode='HTML'
        )
        return

      # 분석 결과 메시지 생성
      message = self.format_bnf_analysis_message(signals)

      # 메시지 업데이트
      await progress_message.edit_text(message, parse_mode='HTML')

      self.logger.info(f"✅ Sent BNF analysis for {ticker} via Telegram command")

    except Exception as e:
      self.logger.error(f"❌ Error analyzing ticker in command: {e}")
      try:
        await update.message.reply_text(
            f"❌ <b>Error analyzing ticker</b>\n\n"
            f"Error: {str(e)}\n\n"
            "💡 Please try again or check if the ticker symbol is correct.",
            parse_mode='HTML'
        )
      except:
        pass

  async def status_command(self, update, context):
    """Handle /status command to show monitoring status."""
    try:
      current_time = datetime.now()
      uptime = current_time - self.start_time if self.start_time else timedelta(
        0)
      uptime_str = str(uptime).split('.')[0]

      market_info = self.get_market_time_info()

      if market_info.get('is_market_open'):
        market_status = "🟢 Market Open"
        if market_info.get('time_to_close'):
          market_status += f" (closes in {market_info['time_to_close']})"
      elif market_info.get('is_weekend'):
        market_status = "🔴 Weekend"
      elif market_info.get('is_holiday'):
        market_status = "🔴 Holiday"
      else:
        market_status = "🔴 Market Closed"
        if market_info.get('next_open_korea'):
          market_status += f"\nNext open: {market_info['next_open_korea']}"

      last_signal_str = "None"
      if self.last_signal_time:
        time_diff = current_time - self.last_signal_time
        if time_diff.days > 0:
          last_signal_str = f"{time_diff.days}d ago"
        elif time_diff.seconds > 3600:
          last_signal_str = f"{time_diff.seconds // 3600}h ago"
        elif time_diff.seconds > 60:
          last_signal_str = f"{time_diff.seconds // 60}m ago"
        else:
          last_signal_str = "< 1m ago"

      # 현재 포지션 수 계산
      current_positions = sum(1 for pos in self.positions.values() if
                              pos.get('status') == 'holding')

      status_message = f"""📊 <b>BNF Strategy Monitor Status</b>

🔄 Status: {'🟢 Running' if self.is_monitoring else '🔴 Stopped'}
⏱️ Uptime: {uptime_str}
🇰🇷 Korea Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}
🇺🇸 US Time: {market_info.get('us_time', 'N/A')}

{market_status}

📈 <b>BNF Strategy Statistics:</b>
   🔍 Total Scans: {self.scan_count}
   📱 Signals Sent: {self.total_signals_sent}
   📊 Watching: {len(self.watchlist)} stocks
   💼 Current Positions: {current_positions}
   ⏰ Scan Interval: 5 minutes
   🎯 Last Signal: {last_signal_str}

🎯 <b>Strategy Focus:</b>
   • Counter-trend reversals
   • 2-3 day holding period
   • High-probability setups only

💡 <b>Commands:</b>
   /ticker &lt;symbol&gt; - Analyze stock
   /status - Show this status
   /start - Help message"""

      await update.message.reply_text(status_message, parse_mode='HTML')
      self.logger.info(f"Sent status to user {update.effective_user.id}")

    except Exception as e:
      self.logger.error(f"Error in status_command: {e}")
      await update.message.reply_text(
        "❌ Error getting status. Please try again.")

  def calculate_bnf_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
    """BNF 스타일 기술적 지표 계산 (백테스트와 동일한 로직)"""
    if len(data) < max(self.rsi_period, self.williams_period, self.ema_long):
      return data

    # RSI 계산
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))

    # Williams %R 계산
    high_max = data['High'].rolling(window=self.williams_period).max()
    low_min = data['Low'].rolling(window=self.williams_period).min()
    data['Williams_R'] = -100 * (high_max - data['Close']) / (high_max - low_min)

    # EMA 계산 (BNF 스타일: 25일 중심)
    data['EMA_20'] = data['Close'].ewm(span=self.ema_short).mean()
    data['EMA_25'] = data['Close'].ewm(span=self.ema_long).mean()  # BNF의 25일

    # 거래량 분석
    data['Volume_MA'] = data['Volume'].rolling(self.volume_ma_period).mean() if 'Volume' in data.columns else 1
    data['Volume_Ratio'] = data['Volume'] / data['Volume_MA'] if 'Volume' in data.columns else 1

    # 가격 모멘텀
    data['Price_Change_Pct'] = data['Close'].pct_change() * 100
    data['Price_MA_5'] = data['Close'].rolling(5).mean()

    # BNF 스타일: 25일 이동평균 대비 하락률
    data['MA25_Ratio'] = data['Close'] / data['EMA_25']
    data['MA25_Oversold'] = data['MA25_Ratio'] <= self.ma_oversold_threshold

    # 기본 과매수/과매도 조건
    data['RSI_Oversold'] = data['RSI'] <= self.rsi_oversold
    data['RSI_Overbought'] = data['RSI'] >= self.rsi_overbought
    data['Williams_Oversold'] = data['Williams_R'] <= self.williams_oversold
    data['Williams_Overbought'] = data['Williams_R'] >= self.williams_overbought

    # BNF 스타일 매수 신호 (OR 조건으로 완화)
    data['BNF_Buy_Signal'] = (
      # 조건 1: RSI 과매도 + 거래량 증가
        (data['RSI_Oversold'] & (data['Volume_Ratio'] > self.volume_threshold)) |

        # 조건 2: Williams %R 과매도 + 거래량 증가
        (data['Williams_Oversold'] & (data['Volume_Ratio'] > self.volume_threshold)) |

        # 조건 3: BNF 핵심 - 25일 평균 대비 큰 하락 + 반등 시작
        (data['MA25_Oversold'] &
         (data['Close'] > data['Close'].shift(1)) &  # 반등 시작
         (data['Volume_Ratio'] > 1.1))  # 거래량 증가
    )

    # BNF 스타일 매도 신호
    data['BNF_Sell_Signal'] = (
      # 조건 1: RSI 과매수
        data['RSI_Overbought'] |

        # 조건 2: Williams %R 과매수
        data['Williams_Overbought'] |

        # 조건 3: 25일 평균 대비 충분한 상승 (수익 실현)
        (data['MA25_Ratio'] >= 1.10)  # 25일 평균 대비 10% 상승시 수익실현
    )

    return data

  def check_bnf_signals(self, symbol: str) -> Dict:
    """BNF 스타일 신호 확인 (25일 평균 로직 추가)"""
    try:
      data = self.get_stock_data(symbol)
      if data is None or len(data) < 50:
        return {}

      # BNF 지표 계산
      data = self.calculate_bnf_indicators(data)

      latest = data.iloc[-1]
      prev = data.iloc[-2] if len(data) > 1 else latest

      # 현재 포지션 상태 확인
      current_position = self.get_position_status(symbol)

      # BNF 스타일 신호 생성
      buy_signal = False
      sell_signal = False

      if current_position == 'none':
        # 포지션이 없을 때 - BNF 스타일 매수 신호
        buy_signal = bool(latest['BNF_Buy_Signal'])

      elif current_position == 'holding':
        # 포지션이 있을 때 - 수익 실현 또는 손절 신호
        entry_time = self.positions[symbol].get('entry_time')
        if entry_time:
          days_held = (datetime.now() - entry_time).days

          # BNF 스타일: 시간 기반 청산 또는 수익 실현
          sell_signal = (
              bool(latest['BNF_Sell_Signal']) or
              days_held >= 3 or
              (days_held >= 2 and latest['RSI'] >= 60)  # 2일 후 적당한 수익에서 청산
          )

      # BNF 매수/매도 이유 분석
      buy_reason = ""
      sell_reason = ""

      if buy_signal:
        reasons = []
        if latest['RSI_Oversold'] and latest['Volume_Ratio'] > self.volume_threshold:
          reasons.append(f"RSI 과매도({latest['RSI']:.1f})")
        if latest['Williams_Oversold'] and latest['Volume_Ratio'] > self.volume_threshold:
          reasons.append(f"Williams 과매도({latest['Williams_R']:.1f})")
        if latest['MA25_Oversold'] and latest['Close'] > prev['Close']:
          reasons.append(f"25일평균 대비 {(1-latest['MA25_Ratio'])*100:.1f}% 하락 반등")
        buy_reason = " + ".join(reasons)

      if sell_signal:
        reasons = []
        if latest['RSI_Overbought']:
          reasons.append(f"RSI 과매수({latest['RSI']:.1f})")
        if latest['Williams_Overbought']:
          reasons.append(f"Williams 과매수({latest['Williams_R']:.1f})")
        if latest['MA25_Ratio'] >= 1.10:
          reasons.append(f"25일평균 대비 {(latest['MA25_Ratio']-1)*100:.1f}% 상승")
        if entry_time and (datetime.now() - entry_time).days >= 3:
          reasons.append("3일 보유 만료")
        sell_reason = " + ".join(reasons)

      signals = {
        'symbol': symbol,
        'price': float(latest['Close']),
        'rsi': float(latest['RSI']),
        'williams_r': float(latest['Williams_R']),
        'ema_20': float(latest['EMA_20']),
        'ema_25': float(latest['EMA_25']),  # BNF 핵심 지표
        'volume_ratio': float(latest['Volume_Ratio']),
        'price_change_pct': float(latest['Price_Change_Pct']),
        'ma25_ratio': float(latest['MA25_Ratio']),  # BNF 핵심 지표
        'ma25_oversold': bool(latest['MA25_Oversold']),
        'rsi_oversold': bool(latest['RSI_Oversold']),
        'rsi_overbought': bool(latest['RSI_Overbought']),
        'williams_oversold': bool(latest['Williams_Oversold']),
        'williams_overbought': bool(latest['Williams_Overbought']),
        'buy_signal': buy_signal,
        'sell_signal': sell_signal,
        'buy_reason': buy_reason,
        'sell_reason': sell_reason,
        'timestamp': latest.name,
        'position_status': current_position
      }

      return signals

    except Exception as e:
      self.logger.error(f"Error checking BNF signals for {symbol}: {e}")
      return {}

  def get_stock_data(self, symbol: str, period: str = "100d") -> Optional[
    pd.DataFrame]:
    """주식 데이터 가져오기"""
    try:
      stock = yf.Ticker(symbol)
      data = stock.history(period=period)

      if data.empty:
        self.logger.warning(
          f"No data found for {symbol}, retrying with period='1y'")
        data = stock.history(period="1y")
      if data.empty:
        self.logger.warning(f"No data found for {symbol}")
        return None

      return data

    except Exception as e:
      self.logger.error(f"Error fetching data for {symbol}: {e}")
      return None

  def format_bnf_analysis_message(self, signals: Dict) -> str:
    """BNF 분석 메시지 포맷팅 (25일 평균 정보 추가)"""
    try:
      symbol = signals['symbol']
      korean_name = self.ticker_to_korean.get(symbol, 'Unknown')
      price = signals['price']
      rsi = signals['rsi']
      williams_r = signals['williams_r']
      ema_25 = signals['ema_25']
      ma25_ratio = signals['ma25_ratio']
      timestamp = signals['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
      buy_signal = signals['buy_signal']
      sell_signal = signals['sell_signal']
      position_status = signals['position_status']

      # RSI 상태
      if rsi >= 65:
        rsi_status = "🔥 Overbought"
      elif rsi <= 35:
        rsi_status = "❄️ Oversold"
      else:
        rsi_status = "⚖️ Neutral"

      # Williams %R 상태
      if williams_r >= -25:
        williams_status = "🔥 Overbought"
      elif williams_r <= -75:
        williams_status = "❄️ Oversold"
      else:
        williams_status = "⚖️ Neutral"

      # BNF 핵심: 25일 평균 대비 상태
      ma25_pct = (ma25_ratio - 1) * 100
      if ma25_ratio <= 0.80:
        ma25_status = "📉 Strong Oversold (-20%+)"
      elif ma25_ratio <= 0.90:
        ma25_status = "📊 Oversold (-10%+)"
      elif ma25_ratio >= 1.10:
        ma25_status = "📈 Strong Overbought (+10%+)"
      else:
        ma25_status = "⚖️ Normal Range"

      # 신호 상태
      signal_text = "📊 No Signals"
      if buy_signal:
        signal_text = f"🚀 BNF BUY: {signals.get('buy_reason', 'Multiple factors')}"
      elif sell_signal:
        signal_text = f"🔴 BNF SELL: {signals.get('sell_reason', 'Take profit')}"

      # BNF 전략 적합성 평가
      bnf_score = 0
      if signals.get('ma25_oversold', False):
        bnf_score += 3  # 가장 중요한 BNF 조건
      if signals.get('rsi_oversold', False):
        bnf_score += 2
      if signals.get('williams_oversold', False):
        bnf_score += 2
      if signals.get('volume_ratio', 1) > 1.2:
        bnf_score += 1

      if bnf_score >= 5:
        bnf_rating = "🌟 Excellent Setup"
      elif bnf_score >= 3:
        bnf_rating = "✅ Good Setup"
      elif bnf_score >= 1:
        bnf_rating = "📊 Moderate Setup"
      else:
        bnf_rating = "⏳ Wait for Better Setup"

      message = (
        f"📈 <b>BNF Analysis: {symbol} ({korean_name})</b>\n\n"
        f"💰 <b>Price:</b> ${price:.2f} ({signals['price_change_pct']:+.2f}%)\n"
        f"📊 <b>RSI:</b> {rsi:.1f} ({rsi_status})\n"
        f"📊 <b>Williams %R:</b> {williams_r:.1f} ({williams_status})\n"
        f"📈 <b>25-Day MA:</b> ${ema_25:.2f} ({ma25_pct:+.1f}% {ma25_status})\n"
        f"📊 <b>Volume:</b> {signals['volume_ratio']:.1f}x average\n\n"
        f"🎯 <b>BNF Signal:</b> {signal_text}\n"
        f"⭐ <b>Setup Quality:</b> {bnf_rating}\n"
        f"💼 <b>Position:</b> {position_status.title()}\n\n"
        f"⏰ <b>Analysis Time:</b> {timestamp}\n\n"
        f"💡 <b>BNF Strategy (Takashi Kotegawa):</b>\n"
        f"• Buy stocks 20% below 25-day average\n"
        f"• Hold 2-3 days maximum\n"
        f"• Exit on overbought or time limit\n"
        f"• Focus on counter-trend reversals\n"
        f"• \"Trade against the crowd\""
      )

      return message

    except Exception as e:
      self.logger.error(f"Error formatting BNF analysis message: {e}")
      return f"❌ Error formatting analysis for {signals.get('symbol', 'unknown')}"

  def format_alert_message(self, signals: Dict, signal_type: str) -> str:
    """BNF 스타일 알림 메시지 (구체적인 BNF 이유 포함)"""
    symbol = signals['symbol']
    korean_name = self.ticker_to_korean.get(symbol, 'Unknown')
    price = signals['price']
    rsi = signals['rsi']
    williams_r = signals['williams_r']
    ema_25 = signals['ema_25']
    ma25_ratio = signals.get('ma25_ratio', 1.0)
    timestamp = signals['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
    position_status = signals.get('position_status', 'none')

    if signal_type == 'buy':
      # BNF 매수 이유 분석
      buy_reason = signals.get('buy_reason', '')
      if not buy_reason:
        # 기본 분석
        if signals.get('ma25_oversold', False):
          decline_pct = (1 - ma25_ratio) * 100
          buy_reason = f"25일평균 대비 {decline_pct:.1f}% 하락 반등"
        elif signals.get('rsi_oversold', False):
          buy_reason = f"RSI 과매도 반전"
        elif signals.get('williams_oversold', False):
          buy_reason = f"Williams %R 과매도 반전"
        else:
          buy_reason = "복합 과매도 신호"

      message = f"""🚀 <b>BNF 역추세 매수 신호!</b>
                
종목: <b>{symbol} ({korean_name})</b>
현재가: <b>${price:.2f}</b>
25일평균: <b>${ema_25:.2f}</b> ({(ma25_ratio-1)*100:+.1f}%)
매수 이유: <b>{buy_reason}</b>

📊 기술적 지표:
RSI: <b>{rsi:.1f}</b> (과매도: {rsi <= 35})
Williams %R: <b>{williams_r:.1f}</b> (과매도: {williams_r <= -75})
거래량: <b>{signals.get('volume_ratio', 1):.1f}x</b>

⏰ 목표 기간: <b>2-3일</b>
📈 전략: <b>타카시 코테가와(BNF) 역추세</b>
시간: {timestamp}

💡 "대중과 반대로 행동하라" - BNF"""

    else:  # sell
      # BNF 매도 이유 분석
      sell_reason = signals.get('sell_reason', '')
      if not sell_reason:
        # 기본 분석
        if ma25_ratio >= 1.10:
          profit_pct = (ma25_ratio - 1) * 100
          sell_reason = f"25일평균 대비 {profit_pct:.1f}% 상승"
        elif signals.get('rsi_overbought', False):
          sell_reason = "RSI 과매수"
        elif signals.get('williams_overbought', False):
          sell_reason = "Williams %R 과매수"
        else:
          sell_reason = "시간 청산"

      # 보유 정보
      entry_time = self.positions.get(symbol, {}).get('entry_time')
      entry_price = self.positions.get(symbol, {}).get('entry_price', price)

      if entry_time and entry_price:
        days_held = (datetime.now() - entry_time).days
        profit_pct = ((price - entry_price) / entry_price) * 100
        entry_info = f"\n진입가: <b>${entry_price:.2f}</b>\n보유기간: <b>{days_held}일</b>\n손익: <b>{profit_pct:+.1f}%</b>"
      else:
        entry_info = ""

      message = f"""🔴 <b>BNF 청산 신호!</b>
                
종목: <b>{symbol} ({korean_name})</b>
현재가: <b>${price:.2f}</b>
25일평균: <b>${ema_25:.2f}</b> ({(ma25_ratio-1)*100:+.1f}%){entry_info}
청산 이유: <b>{sell_reason}</b>

📊 기술적 지표:
RSI: <b>{rsi:.1f}</b> (과매수: {rsi >= 65})
Williams %R: <b>{williams_r:.1f}</b> (과매수: {williams_r >= -25})

📈 BNF 전략: <b>빠른 차익실현</b>
시간: {timestamp}

💰 "작은 수익도 확실히 챙기자" - BNF"""

    return message

  def should_send_alert(self, symbol: str, signal_type: str) -> bool:
    """알림 쿨다운 확인"""
    key = f"{symbol}_{signal_type}"
    current_time = time.time()

    if key in self.last_alerts:
      if current_time - self.last_alerts[key] < self.alert_cooldown:
        return False

    self.last_alerts[key] = current_time
    return True

  def send_telegram_alert(self, message: str, parse_mode: str = 'HTML') -> bool:
    """텔레그램 알림 전송 (재시도 로직 및 큐 시스템 개선)"""
    if not self.telegram_bot_token or not self.telegram_chat_id:
      self.logger.info(f"Telegram Alert (not sent, no token/chat_id): {message}")
      return False

    # 메시지 정제 (HTML 태그 오류 방지)
    message = re.sub(r'<symbol>', '<b>', message, flags=re.IGNORECASE)
    message = re.sub(r'</symbol>', '</b>', message, flags=re.IGNORECASE)

    url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
    payload = {
      'chat_id': self.telegram_chat_id,
      'text': message,
      'parse_mode': parse_mode
    }

    max_retries = 3
    base_delay = 1  # 기본 지연 시간

    for attempt in range(max_retries):
      try:
        # 지수 백오프 지연
        if attempt > 0:
          delay = base_delay * (2 ** (attempt - 1))
          time.sleep(delay)

        response = requests.post(url, data=payload, timeout=10)

        if response.status_code == 200:
          self.logger.info(f"✅ BNF 텔레그램 알림 전송 성공 (시도 {attempt + 1})")
          return True

        elif response.status_code == 429:
          # Rate limit 처리
          retry_data = response.json()
          retry_after = retry_data.get('parameters', {}).get('retry_after', 20)

          self.logger.warning(
              f"⚠️ 텔레그램 429 에러: {retry_after}초 후 재시도 (시도 {attempt + 1}/{max_retries})"
          )

          if attempt < max_retries - 1:
            time.sleep(retry_after + 1)
            continue
          else:
            self.logger.error(f"❌ 텔레그램 전송 최종 실패: Rate limit 초과")
            return False

        elif response.status_code == 400:
          # Bad request - 메시지 포맷 오류
          self.logger.error(f"❌ 텔레그램 400 에러: 메시지 포맷 오류")
          self.logger.error(f"문제 메시지: {message[:100]}...")

          # HTML 파싱 오류일 가능성 - 일반 텍스트로 재시도
          if parse_mode == 'HTML' and attempt < max_retries - 1:
            payload['parse_mode'] = None
            payload['text'] = re.sub(r'<[^>]+>', '', message)  # HTML 태그 제거
            self.logger.info("📝 HTML 태그 제거 후 재시도")
            continue
          else:
            return False

        else:
          self.logger.error(f"❌ 텔레그램 전송 실패 (시도 {attempt + 1}): {response.status_code} - {response.text}")

          if attempt < max_retries - 1:
            continue
          else:
            return False

      except requests.exceptions.Timeout:
        self.logger.warning(f"⏰ 텔레그램 타임아웃 (시도 {attempt + 1}/{max_retries})")
        if attempt == max_retries - 1:
          return False

      except requests.exceptions.ConnectionError:
        self.logger.warning(f"🌐 텔레그램 연결 오류 (시도 {attempt + 1}/{max_retries})")
        if attempt == max_retries - 1:
          return False

      except Exception as e:
        self.logger.error(f"❌ 텔레그램 전송 예외 (시도 {attempt + 1}): {e}")
        if attempt == max_retries - 1:
          return False

    return False

  def process_signals(self, signals: Dict) -> bool:
    """BNF 신호 처리"""
    if not signals:
      return False

    symbol = signals['symbol']
    alert_sent = False

    # 매수 신호 처리
    if signals['buy_signal'] and self.should_send_alert(symbol, 'buy'):
      message = self.format_alert_message(signals, 'buy')
      if self.send_telegram_alert(message):
        self.logger.info(f"🚀 BNF 매수 신호 알림 전송: {symbol}")
        self.total_signals_sent += 1
        self.last_signal_time = datetime.now()

        # 포지션 상태를 holding으로 변경
        self.update_position(symbol, 'holding', signals['price'])
        alert_sent = True

    # 매도 신호 처리
    if signals['sell_signal'] and self.should_send_alert(symbol, 'sell'):
      message = self.format_alert_message(signals, 'sell')
      if self.send_telegram_alert(message):
        self.logger.info(f"🔴 BNF 매도 신호 알림 전송: {symbol}")
        self.total_signals_sent += 1
        self.last_signal_time = datetime.now()

        # 포지션 상태를 none으로 변경
        self.update_position(symbol, 'none')
        alert_sent = True

    return alert_sent

  def _is_market_hours(self) -> bool:
    """미국 주식 시장 시간 확인 (캐싱으로 성능 최적화)"""
    try:
      current_time = datetime.now()

      # 캐시 만료 확인 (1분마다 갱신)
      if (self.market_time_cache_expiry is None or
          current_time > self.market_time_cache_expiry):

        korea_tz = pytz.timezone('Asia/Seoul')
        us_eastern_tz = pytz.timezone('US/Eastern')

        korea_now = current_time.replace(tzinfo=korea_tz)
        us_now = korea_now.astimezone(us_eastern_tz)

        # 주말 체크
        if us_now.weekday() >= 5:
          is_open = False
        # 공휴일 체크
        elif self._is_us_holiday(us_now):
          is_open = False
        else:
          # 장시간 체크
          market_open = us_now.replace(hour=9, minute=30, second=0, microsecond=0)
          market_close = us_now.replace(hour=16, minute=0, second=0, microsecond=0)
          is_open = market_open <= us_now <= market_close

        # 캐시 업데이트
        self.market_time_cache = {
          'is_open': is_open,
          'us_time': us_now,
          'korea_time': korea_now,
          'last_check': current_time
        }
        self.market_time_cache_expiry = current_time + timedelta(minutes=1)

        # 디버그 로그 (첫 3번만)
        if not hasattr(self, '_time_debug_count'):
          self._time_debug_count = 0

        if self._time_debug_count < 3:
          self.logger.info(f"⏰ 시간 체크 - 한국: {korea_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
          self.logger.info(f"⏰ 시간 체크 - 미국: {us_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
          self.logger.info(f"⏰ 장 상태: {'🟢 개장' if is_open else '🔴 마감'}")
          self._time_debug_count += 1

      # 캐시에서 반환
      return self.market_time_cache.get('is_open', True)

    except Exception as e:
      self.logger.warning(f"시간 확인 오류: {e} - 기본값 True 반환")
      return True

  def _is_us_holiday(self, us_date: datetime) -> bool:
    """미국 주요 공휴일 체크"""
    try:
      year = us_date.year
      month = us_date.month
      day = us_date.day

      holidays = [
        (1, 1),  # 신정
        (7, 4),  # 독립기념일
        (12, 25),  # 크리스마스
      ]

      if (month, day) in holidays:
        return True

      if month == 11 and us_date.weekday() == 3:
        first_day = us_date.replace(day=1)
        first_thursday = 1 + (3 - first_day.weekday()) % 7
        fourth_thursday = first_thursday + 21
        if day == fourth_thursday:
          return True

      return False

    except Exception as e:
      self.logger.warning(f"공휴일 확인 오류: {e}")
      return False

  def get_market_time_info(self) -> Dict:
    """시장 시간 정보 조회 (캐싱 활용으로 성능 개선)"""
    try:
      # 캐시된 정보가 있고 1분 이내라면 재사용
      if (self.market_time_cache and
          self.market_time_cache.get('last_check') and
          (datetime.now() - self.market_time_cache['last_check']).seconds < 60):

        cached_data = self.market_time_cache

        # 시간 정보 포맷팅
        korea_time = cached_data['korea_time']
        us_time = cached_data['us_time']

        # 추가 정보 계산 (캐시에 없는 경우만)
        time_to_close = None
        if cached_data['is_open']:
          market_close = us_time.replace(hour=16, minute=0, second=0, microsecond=0)
          time_to_close = market_close - us_time
          if time_to_close.total_seconds() < 0:
            time_to_close = None

        next_open = self._get_next_market_open(us_time)
        next_open_korea = next_open.astimezone(pytz.timezone('Asia/Seoul')) if next_open else None

        return {
          'korea_time': korea_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
          'us_time': us_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
          'is_market_open': cached_data['is_open'],
          'is_weekend': us_time.weekday() >= 5,
          'is_holiday': self._is_us_holiday(us_time),
          'next_open_us': next_open.strftime('%Y-%m-%d %H:%M %Z') if next_open else None,
          'next_open_korea': next_open_korea.strftime('%Y-%m-%d %H:%M %Z') if next_open_korea else None,
          'time_to_close': str(time_to_close).split('.')[0] if time_to_close else None,
          'cached': True  # 캐시 사용 표시
        }

      # 캐시가 없거나 만료된 경우 새로 계산
      korea_tz = pytz.timezone('Asia/Seoul')
      us_eastern_tz = pytz.timezone('US/Eastern')

      korea_now = datetime.now(korea_tz)
      us_now = korea_now.astimezone(us_eastern_tz)

      is_market_open = self._is_market_hours()
      next_open = self._get_next_market_open(us_now)
      next_open_korea = next_open.astimezone(korea_tz) if next_open else None

      time_to_close = None
      if is_market_open:
        market_close = us_now.replace(hour=16, minute=0, second=0, microsecond=0)
        time_to_close = market_close - us_now
        if time_to_close.total_seconds() < 0:
          time_to_close = None

      return {
        'korea_time': korea_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
        'us_time': us_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
        'is_market_open': is_market_open,
        'is_weekend': us_now.weekday() >= 5,
        'is_holiday': self._is_us_holiday(us_now),
        'next_open_us': next_open.strftime('%Y-%m-%d %H:%M %Z') if next_open else None,
        'next_open_korea': next_open_korea.strftime('%Y-%m-%d %H:%M %Z') if next_open_korea else None,
        'time_to_close': str(time_to_close).split('.')[0] if time_to_close else None,
        'cached': False  # 새로 계산됨
      }

    except Exception as e:
      self.logger.error(f"시장 시간 정보 조회 오류: {e}")
      return {
        'korea_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'us_time': 'Error',
        'is_market_open': True,  # 안전한 기본값
        'is_weekend': False,
        'is_holiday': False,
        'next_open_us': None,
        'next_open_korea': None,
        'time_to_close': None,
        'cached': False,
        'error': str(e)
      }

  def _get_next_market_open(self, current_us_time: datetime) -> datetime:
    """다음 장 개장 시간 계산"""
    try:
      today_open = current_us_time.replace(hour=9, minute=30, second=0,
                                           microsecond=0)

      if current_us_time < today_open and current_us_time.weekday() < 5:
        if not self._is_us_holiday(current_us_time):
          return today_open

      next_day = current_us_time + timedelta(days=1)

      for i in range(7):
        check_date = next_day + timedelta(days=i)
        if check_date.weekday() < 5 and not self._is_us_holiday(check_date):
          return check_date.replace(hour=9, minute=30, second=0, microsecond=0)

      return None

    except Exception as e:
      self.logger.error(f"다음 개장 시간 계산 오류: {e}")
      return None

  def send_heartbeat(self):
    """BNF 스타일 Heartbeat 메시지 전송"""
    if not self.telegram_bot_token:
      return

    current_time = datetime.now()
    uptime = current_time - self.start_time if self.start_time else timedelta(0)
    uptime_str = str(uptime).split('.')[0]

    market_info = self.get_market_time_info()

    if market_info.get('is_market_open'):
      market_status = "🟢 장중"
      if market_info.get('time_to_close'):
        market_status += f" (마감까지 {market_info['time_to_close']})"
    elif market_info.get('is_weekend'):
      market_status = "🔴 주말"
    elif market_info.get('is_holiday'):
      market_status = "🔴 공휴일"
    else:
      market_status = "🔴 장마감"
      if market_info.get('next_open_korea'):
        market_status += f"\n   다음 개장: {market_info['next_open_korea']}"

    last_signal_str = "없음"
    if self.last_signal_time:
      time_diff = current_time - self.last_signal_time
      if time_diff.days > 0:
        last_signal_str = f"{time_diff.days}일 전"
      elif time_diff.seconds > 3600:
        last_signal_str = f"{time_diff.seconds // 3600}시간 전"
      elif time_diff.seconds > 60:
        last_signal_str = f"{time_diff.seconds // 60}분 전"
      else:
        last_signal_str = "1분 이내"

    # 현재 포지션 수
    current_positions = sum(
        1 for pos in self.positions.values() if pos.get('status') == 'holding')

    hour = current_time.hour
    if 6 <= hour < 12:
      time_emoji = "🌅"
    elif 12 <= hour < 18:
      time_emoji = "☀️"
    elif 18 <= hour < 22:
      time_emoji = "🌆"
    else:
      time_emoji = "🌙"

    heartbeat_message = f"""{time_emoji} <b>BNF Strategy - Heartbeat</b>

🇰🇷 한국 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}
🇺🇸 미국 시간: {market_info.get('us_time', 'N/A')}
⏱️ 가동 시간: {uptime_str}

{market_status}

📊 <b>BNF 전략 통계:</b>
   🔍 총 스캔: {self.scan_count}회
   📱 알림 발송: {self.total_signals_sent}개
   📈 감시 종목: {len(self.watchlist)}개
   💼 현재 포지션: {current_positions}개
   ⏰ 스캔 간격: 5분

🎯 <b>BNF 방식 요약:</b>
   • 역추세 반전 신호 포착
   • 2-3일 단기 보유
   • 과매수/과매도 반전 전문
   마지막 신호: {last_signal_str}

✅ <b>상태:</b> 타카시 코테가와 스타일 정상 가동 중
🔄 다음 Heartbeat: 1시간 후"""

    if self.send_telegram_alert(heartbeat_message):
      self.logger.info(f"💓 BNF Heartbeat 전송 완료 - 가동시간: {uptime_str}")
      self.last_heartbeat = current_time
    else:
      self.logger.error("💔 BNF Heartbeat 전송 실패")

  def start_heartbeat(self):
    """Heartbeat 스레드 시작"""
    if self.heartbeat_thread and self.heartbeat_thread.is_alive():
      return

    self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop,
                                             daemon=True)
    self.heartbeat_thread.start()
    self.logger.info(f"💓 BNF Heartbeat 스레드 시작 - {self.heartbeat_interval}초 간격")

  def _heartbeat_loop(self):
    """Heartbeat 루프"""
    while self.is_monitoring:
      try:
        time.sleep(self.heartbeat_interval)

        if self.is_monitoring:
          self.send_heartbeat()

      except Exception as e:
        self.logger.error(f"💔 BNF Heartbeat 루프 오류: {e}")
        time.sleep(60)

  def scan_single_stock(self, symbol: str):
    """단일 종목 BNF 스캔"""
    try:
      signals = self.check_bnf_signals(symbol)
      if signals:
        self.process_signals(signals)

        if any([signals.get('buy_signal'), signals.get('sell_signal')]):
          self.logger.info(
            f"BNF {symbol}: Price=${signals['price']:.2f}, RSI={signals['rsi']:.1f}, Williams={signals['williams_r']:.1f}")

    except Exception as e:
      self.logger.error(f"Error scanning BNF {symbol}: {e}")

  def _scan_all_stocks_auto(self) -> int:
    """전체 종목 BNF 자동 스캔 (성능 최적화)"""
    signals_found = 0
    failed_stocks = []
    scan_start_time = time.time()

    # 배치별 진행률 표시를 위한 설정
    batch_size = 10
    total_batches = (len(self.watchlist) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
      batch_start = batch_idx * batch_size
      batch_end = min(batch_start + batch_size, len(self.watchlist))
      batch_stocks = self.watchlist[batch_start:batch_end]

      # 배치 처리 시작
      batch_signals = 0
      batch_start_time = time.time()

      for i, symbol in enumerate(batch_stocks):
        global_idx = batch_start + i + 1

        try:
          # 진행률 표시 (매 10개마다)
          if global_idx % 10 == 0:
            elapsed = time.time() - scan_start_time
            progress = global_idx / len(self.watchlist) * 100
            self.logger.info(
                f"   📊 BNF 스캔 진행률: {global_idx}/{len(self.watchlist)} "
                f"({progress:.0f}%, {elapsed:.1f}초 소요)"
            )

          # BNF 신호 확인
          signals = self.check_bnf_signals(symbol)
          if signals:
            if self.process_signals(signals):
              signals_found += 1
              batch_signals += 1

          # 적응형 지연 (시장 상황에 따라 조정)
          if self._is_market_hours():
            time.sleep(0.1)  # 장중: 짧은 지연
          else:
            time.sleep(0.05)  # 장외: 더 짧은 지연

        except requests.exceptions.Timeout:
          self.logger.warning(f"⏰ {symbol} 타임아웃 - 건너뜀")
          failed_stocks.append(f"{symbol}(timeout)")
          time.sleep(0.5)  # 타임아웃 후 잠시 대기
          continue

        except requests.exceptions.ConnectionError:
          self.logger.warning(f"🌐 {symbol} 연결 오류 - 건너뜀")
          failed_stocks.append(f"{symbol}(connection)")
          time.sleep(0.5)
          continue

        except Exception as e:
          self.logger.error(f"❌ BNF {symbol} 스캔 오류: {str(e)[:50]}")
          failed_stocks.append(f"{symbol}(error)")
          continue

      # 배치 완료 로그
      batch_time = time.time() - batch_start_time
      if batch_signals > 0:
        self.logger.info(
            f"✨ 배치 {batch_idx + 1}/{total_batches} 완료: "
            f"{batch_signals}개 신호 발견 ({batch_time:.1f}초)"
        )

    # 스캔 완료 요약
    total_time = time.time() - scan_start_time
    success_rate = (len(self.watchlist) - len(failed_stocks)) / len(self.watchlist) * 100

    if signals_found > 0:
      self.logger.info(
          f"🎯 BNF 스캔 완료: {signals_found}개 신호 발견 "
          f"({total_time:.1f}초, 성공률: {success_rate:.1f}%)"
      )
    elif failed_stocks:
      self.logger.warning(
          f"⚠️ BNF 스캔 완료: 신호 없음, {len(failed_stocks)}개 실패 "
          f"({total_time:.1f}초)"
      )
    else:
      self.logger.info(
          f"📊 BNF 스캔 완료: 신호 없음 "
          f"({total_time:.1f}초, 모든 종목 정상)"
      )

    # 실패한 종목들 상세 로그 (너무 많으면 요약)
    if failed_stocks:
      if len(failed_stocks) <= 5:
        self.logger.warning(f"❌ 실패 종목: {', '.join(failed_stocks)}")
      else:
        failure_summary = {}
        for failed in failed_stocks:
          if '(' in failed:
            reason = failed.split('(')[1].rstrip(')')
            failure_summary[reason] = failure_summary.get(reason, 0) + 1

        summary_str = ', '.join([f"{reason}: {count}개" for reason, count in failure_summary.items()])
        self.logger.warning(f"❌ 실패 요약: {summary_str}")

    return signals_found

  def start_monitoring(self, scan_interval: int = 300):
    """BNF 자동 모니터링 시작"""
    if self.is_monitoring:
      self.logger.warning("BNF 모니터링이 이미 실행 중입니다.")
      return

    self.is_monitoring = True
    self.start_time = datetime.now()
    self.scan_count = 0
    self.total_signals_sent = 0

    self.logger.info(f"🚀 BNF 자동 모니터링 시작 (스캔 간격: {scan_interval}초)")

    # Telegram bot 시작
    if self.telegram_app and not self.telegram_running:
      self.telegram_running = True
      self.telegram_thread = threading.Thread(target=self._run_telegram_bot,
                                              daemon=True)
      self.telegram_thread.start()
      self.logger.info("✅ BNF Telegram bot thread started")

    # Heartbeat 시작
    self.start_heartbeat()

    # 시작 메시지 전송
    if self.telegram_bot_token:
      time.sleep(2)
      start_message = f"""🤖 <b>BNF Counter-Trend Monitoring Started</b>
        
📊 Watching: {len(self.watchlist)} stocks (US Top 50)
⏰ Scan Interval: {scan_interval}s ({scan_interval // 60}min)
💓 Heartbeat: Every hour
🕐 Start Time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}

🎯 Takashi Kotegawa (BNF) Strategy Active
⚡ Counter-trend reversal alerts
💰 2-3 day holding periods
📱 Real-time signals via Telegram

📱 <b>Commands:</b>
- /ticker &lt;symbol&gt; - Analyze any stock
- /status - Show monitoring status
- /start - Show help

💡 <b>Example:</b> /ticker AAPL"""

      self.send_telegram_alert(start_message)

    # 모니터링 스레드 시작
    self.monitor_thread = threading.Thread(target=self._auto_monitoring_loop,
                                           args=(scan_interval,), daemon=True)
    self.monitor_thread.start()

    self.logger.info("✅ BNF 자동 모니터링 스레드가 시작되었습니다.")

  def _run_telegram_bot(self):
    """Run Telegram bot in a separate thread"""
    try:
      self.logger.info("🤖 Starting BNF Telegram bot polling...")

      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)

      self.telegram_app.run_polling(
          poll_interval=1.0,
          timeout=10,
          drop_pending_updates=True,
          stop_signals=None
      )

    except Exception as e:
      self.logger.error(f"❌ BNF Telegram bot error: {e}")
      self.telegram_running = False
      if self.is_monitoring:
        self.logger.info(
          "🔄 Attempting to restart BNF Telegram bot in 30 seconds...")
        time.sleep(30)
        if self.is_monitoring and not self.telegram_running:
          self.telegram_running = True
          self._run_telegram_bot()

  def _auto_monitoring_loop(self, scan_interval: int):
    """BNF 자동 모니터링 루프"""
    while self.is_monitoring:
      try:
        self.scan_count += 1
        current_time = datetime.now()

        is_market_open = self._is_market_hours()
        market_info = self.get_market_time_info()

        if is_market_open:
          self.logger.info(
            f"📊 BNF 스캔 #{self.scan_count} 시작 - {current_time.strftime('%H:%M:%S')}")
          self.logger.info(f"   🇺🇸 미국시간: {market_info.get('us_time', 'N/A')}")

          signals_found = self._scan_all_stocks_auto()

          if signals_found > 0:
            self.logger.info(f"🎯 BNF {signals_found}개 신호 발견 및 알림 전송 완료")
          else:
            self.logger.info("📈 BNF 신호 없음 - 모니터링 계속")

          if self.scan_count % 5 == 0:
            self._send_status_summary(self.scan_count)

        else:
          if market_info.get('is_weekend'):
            status_msg = "주말"
          elif market_info.get('is_holiday'):
            status_msg = "공휴일"
          else:
            status_msg = "장마감 시간"

          next_scan_time = (
                current_time + timedelta(seconds=scan_interval)).strftime(
            '%H:%M:%S')
          self.logger.info(
            f"⏰ {status_msg} - BNF 대기 중... (다음 스캔: {next_scan_time})")

          if market_info.get('next_open_korea'):
            self.logger.info(f"   📅 다음 개장: {market_info['next_open_korea']}")

        time.sleep(scan_interval)

      except Exception as e:
        self.logger.error(f"❌ BNF 모니터링 루프 오류: {e}")
        time.sleep(30)

  def _send_status_summary(self, scan_count: int):
    """BNF 상태 요약 전송"""
    if not self.telegram_bot_token:
      return

    current_time = datetime.now()
    uptime = current_time - self.start_time if self.start_time else timedelta(0)
    current_positions = sum(
        1 for pos in self.positions.values() if pos.get('status') == 'holding')

    summary_message = f"""📊 <b>BNF 모니터링 상태 요약</b>

🔢 스캔 횟수: {scan_count}회  
⏰ 현재 시간: {current_time.strftime('%H:%M:%S')}
🕐 실행 시간: {str(uptime).split('.')[0]}
📈 감시 종목: {len(self.watchlist)}개
💼 현재 포지션: {current_positions}개
🎯 알림 전송: {self.total_signals_sent}개

🎯 BNF 전략: 역추세 반전 전문
✅ 시스템 정상 작동 중"""

    self.send_telegram_alert(summary_message)

  def stop_monitoring(self):
    """BNF 모니터링 중지"""
    if not self.is_monitoring:
      self.logger.warning("BNF 모니터링이 실행되고 있지 않습니다.")
      return

    self.is_monitoring = False
    self.telegram_running = False

    # 스레드 정리
    if self.monitor_thread:
      self.monitor_thread.join(timeout=10)

    if self.telegram_app:
      try:
        asyncio.run(self.telegram_app.stop())
      except Exception as e:
        self.logger.warning(f"Error stopping BNF Telegram bot: {e}")

    # 종료 메시지 전송
    if self.telegram_bot_token and self.start_time:
      end_time = datetime.now()
      uptime = end_time - self.start_time

      stop_message = f"""⏹️ <b>BNF Monitoring Stopped</b>

🕐 Stop Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}
⏱️ Total Runtime: {str(uptime).split('.')[0]}
🔢 Total Scans: {self.scan_count}
🎯 Total Alerts: {self.total_signals_sent}

✅ BNF monitoring stopped safely."""

      self.send_telegram_alert(stop_message)

    self.logger.info("✅ BNF 모니터링이 중지되었습니다.")

  def run_continuous_monitoring(self, scan_interval: int = 300):
    """BNF 연속 모니터링 실행"""
    try:
      self.logger.info("=" * 80)
      self.logger.info("🚀 BNF 역추세 전략 연속 모니터링 시작")
      self.logger.info("=" * 80)
      self.logger.info(f"📊 감시 종목: {len(self.watchlist)}개 (미국 시총 50위)")
      self.logger.info(f"⏰ 스캔 간격: {scan_interval}초 ({scan_interval // 60}분)")
      self.logger.info(
        f"💓 Heartbeat: {self.heartbeat_interval}초 ({self.heartbeat_interval // 60}분) 간격")
      self.logger.info(
        f"📱 텔레그램 알림: {'활성화' if self.telegram_bot_token else '비활성화'}")

      if self.telegram_bot_token:
        if self.test_telegram_connection():
          self.logger.info("✅ 텔레그램 연결 테스트 성공")
        else:
          self.logger.warning("⚠️ 텔레그램 연결 실패 - 콘솔 로그만 출력")

      self.logger.info("\n📊 초기 BNF 시장 상황 확인 중...")
      initial_signals = self._scan_all_stocks_auto()
      self.logger.info(f"📈 초기 BNF 스캔 완료: {initial_signals}개 신호 발견")

      self.start_monitoring(scan_interval)

      self.logger.info(f"\n🎯 BNF 연속 모니터링 실행 중...")
      self.logger.info(f"   💓 Heartbeat: 1시간마다 상태 알림")
      self.logger.info(
        f"   📬 Use /ticker <symbol> to analyze a stock (e.g., /ticker AAPL)")
      self.logger.info(f"   🎯 BNF 전략: 타카시 코테가와 스타일 역추세")
      self.logger.info(f"   종료하려면 Ctrl+C를 누르세요.")
      self.logger.info("=" * 80)

      while self.is_monitoring:
        time.sleep(60)

    except KeyboardInterrupt:
      self.logger.info(f"\n⏹️ 사용자에 의해 BNF 모니터링이 중단되었습니다.")
    except Exception as e:
      self.logger.error(f"❌ BNF 모니터링 중 오류 발생: {e}")
    finally:
      self.stop_monitoring()

  def test_telegram_connection(self):
    """텔레그램 연결 테스트"""
    time.sleep(1)

    test_message = f"""🧪 <b>BNF 연결 테스트</b>

BNF 역추세 전략 봇이 정상 작동합니다!
테스트 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ 알림 수신 준비 완료
💓 Heartbeat 기능 활성화됨
🎯 타카시 코테가와 스타일 역추세 전략
📬 Use /ticker symbol to analyze a stock (e.g., /ticker AAPL)

🎯 BNF 전략 특징:
• 과매수/과매도 반전 포착
• 2-3일 단기 보유
• 고확률 셋업만 선별"""

    success = self.send_telegram_alert(test_message)
    if success:
      self.logger.info("BNF Telegram connection test successful")
    else:
      self.logger.error("BNF Telegram connection test failed")

    return success


def main():
  """BNF 메인 실행 함수"""
  TELEGRAM_BOT_TOKEN = os.getenv('US_BNF_STRATEGY_TELEGRAM_BOT_TOKEN')
  TELEGRAM_CHAT_ID = os.getenv('US_BNF_STRATEGY_TELEGRAM_CHAT_ID')

  monitor = BNFCounterTrendMonitor(
      telegram_bot_token=TELEGRAM_BOT_TOKEN,
      telegram_chat_id=TELEGRAM_CHAT_ID
  )

  print("=== BNF 역추세 전략 모니터링 시스템 ===")
  print("💓 Heartbeat 기능: 1시간마다 상태 알림")
  print("🇰🇷 한국 시간 기준 미국 장시간 정확 체크")
  print("🎯 타카시 코테가와(BNF) 스타일 역추세 전략")
  print("📬 Use /ticker <symbol> to analyze a stock (e.g., /ticker AAPL)")

  if monitor.telegram_bot_token:
    monitor.test_telegram_connection()

  try:
    print("\n현재 BNF 시장 개요:")
    print("🎯 BNF 전략: 과매수/과매도 반전 포착")
    print("💰 보유 기간: 2-3일 단기")
    print("📊 신호 조건: RSI + Williams %R 이중 확인")

    market_info = monitor.get_market_time_info()
    if market_info:
      print(f"\n시장 시간 정보:")
      print(f"🇰🇷 한국 시간: {market_info.get('korea_time')}")
      print(f"🇺🇸 미국 시간: {market_info.get('us_time')}")
      print(
        f"📊 장 상태: {'🟢 개장' if market_info.get('is_market_open') else '🔴 마감'}")
      if market_info.get('next_open_korea'):
        print(f"📅 다음 개장: {market_info.get('next_open_korea')}")

    print("\nBNF 실시간 모니터링 시작...")
    monitor.run_continuous_monitoring(scan_interval=300)

  except KeyboardInterrupt:
    print("\nBNF 모니터링 종료 중...")
    monitor.stop_monitoring()
    print("BNF 모니터링이 종료되었습니다.")

  except Exception as e:
    print(f"BNF 오류 발생: {e}")
    monitor.stop_monitoring()


if __name__ == "__main__":
  main()
