# bnf_backtest_strategy.py
"""
BNF 역추세 전략 백테스트 전용 모듈

주요 기능:
- 타카시 코테가와(BNF) 스타일 역추세 전략 백테스트
- 과매수/과매도 반전 포착
- 2-3일 단기 스윙 트레이딩
- 상세한 성과 지표 계산 및 시각화
- CSV 결과 저장 및 차트 생성
"""

import os
import platform
import time
import warnings
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings('ignore')


# ===================================================================================
# 한글 폰트 설정
# ===================================================================================

def setup_korean_font():
  """한글 폰트 설정"""
  try:
    import matplotlib.font_manager as fm

    system = platform.system()

    if system == "Windows":
      font_candidates = [
        'C:/Windows/Fonts/malgun.ttf',
        'C:/Windows/Fonts/gulim.ttc',
        'C:/Windows/Fonts/batang.ttc'
      ]
      font_names = ['Malgun Gothic', 'Gulim', 'Batang', 'Arial Unicode MS']
    elif system == "Darwin":
      font_candidates = [
        '/Library/Fonts/AppleSDGothicNeo.ttc',
        '/System/Library/Fonts/AppleGothic.ttf',
        '/Library/Fonts/NanumGothic.ttf'
      ]
      font_names = ['Apple SD Gothic Neo', 'AppleGothic', 'NanumGothic',
                    'Arial Unicode MS']
    else:
      font_candidates = [
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
        '/usr/share/fonts/TTF/NanumGothic.ttf'
      ]
      font_names = ['NanumGothic', 'DejaVu Sans', 'Liberation Sans']

    font_found = False
    for font_path in font_candidates:
      if os.path.exists(font_path):
        try:
          if hasattr(fm.fontManager, 'addfont'):
            fm.fontManager.addfont(font_path)
          prop = fm.FontProperties(fname=font_path)
          plt.rcParams['font.family'] = prop.get_name()
          font_found = True
          print(f"✅ 한글 폰트 설정: {font_path}")
          break
        except Exception as e:
          continue

    if not font_found:
      available_fonts = [f.name for f in fm.fontManager.ttflist]
      for font_name in font_names:
        if font_name in available_fonts:
          try:
            plt.rcParams['font.family'] = font_name
            font_found = True
            print(f"✅ 한글 폰트 설정: {font_name}")
            break
          except Exception as e:
            continue

    if not font_found:
      if system == "Windows":
        plt.rcParams['font.family'] = ['Arial Unicode MS', 'DejaVu Sans',
                                       'Arial']
      elif system == "Darwin":
        plt.rcParams['font.family'] = ['Arial Unicode MS', 'Helvetica',
                                       'DejaVu Sans']
      else:
        plt.rcParams['font.family'] = ['DejaVu Sans', 'Liberation Sans',
                                       'Arial']

      print("⚠️ 한글 폰트를 찾을 수 없어 기본 폰트를 사용합니다.")

    plt.rcParams['axes.unicode_minus'] = False

    try:
      if hasattr(fm, '_rebuild'):
        fm._rebuild()
      elif hasattr(fm.fontManager, 'findfont'):
        fm.fontManager.__init__()
    except Exception as e:
      print(f"⚠️ 폰트 캐시 갱신 건너뜀: {e}")

    return font_found

  except Exception as e:
    print(f"⚠️ 폰트 설정 중 오류: {e}")
    plt.rcParams['font.family'] = ['DejaVu Sans', 'Arial', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False
    return False


# 폰트 초기화
setup_korean_font()


# ===================================================================================
# BNF 백테스트 클래스
# ===================================================================================

class BNFCounterTrendBacktest:
  """BNF 역추세 전략 백테스트 클래스"""

  def __init__(self, initial_capital: float = 10000,
      strategy_mode: str = "balanced"):
    """초기화"""

    # 미국 시총 50위 종목 (실시간 모니터와 동일)
    self.top50_stocks = [
      'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B', 'AVGO',
      'LLY',
      'JPM', 'UNH', 'XOM', 'V', 'PG', 'JNJ', 'MA', 'HD', 'CVX', 'MRK',
      'ABBV', 'KO', 'ADBE', 'PEP', 'COST', 'WMT', 'BAC', 'CRM', 'TMO', 'NFLX',
      'ACN', 'LIN', 'MCD', 'ABT', 'CSCO', 'AMD', 'PM', 'TXN', 'DHR', 'DIS',
      'INTC', 'VZ', 'WFC', 'COP', 'BMY', 'NOW', 'CAT', 'NEE', 'UPS', 'RTX'
    ]

    # 백테스트 설정
    self.initial_capital = initial_capital
    self.strategy_mode = strategy_mode
    self._setup_bnf_parameters(strategy_mode)

    # 출력 디렉토리 설정
    self._setup_output_directories()

    print(f"💰 초기 자금: ${self.initial_capital:,.2f}")
    print(f"🎯 BNF 전략 모드: {strategy_mode.upper()}")
    print(f"📋 분석 대상: {len(self.top50_stocks)}개 종목")

  def _setup_output_directories(self):
    """출력 디렉토리 설정"""
    base_dir = os.path.dirname(os.path.abspath(__file__))

    self.output_base_dir = os.path.join(base_dir, 'bnf_output_files')
    self.results_dir = os.path.join(self.output_base_dir, 'results')
    self.charts_dir = os.path.join(self.output_base_dir, 'charts')
    self.reports_dir = os.path.join(self.output_base_dir, 'reports')

    for directory in [self.output_base_dir, self.results_dir, self.charts_dir,
                      self.reports_dir]:
      try:
        os.makedirs(directory, exist_ok=True)
        print(f"📁 BNF 디렉토리 준비: {os.path.relpath(directory)}")
      except Exception as e:
        print(f"⚠️ 디렉토리 생성 오류 ({directory}): {e}")
        if directory == self.results_dir:
          self.results_dir = base_dir
        elif directory == self.charts_dir:
          self.charts_dir = base_dir
        elif directory == self.reports_dir:
          self.reports_dir = base_dir

  def _setup_bnf_parameters(self, strategy_mode: str):
    """BNF 전략 매개변수 설정 (실제 BNF 전략에 맞게 수정)"""
    # 실제 BNF가 사용한 파라미터
    self.rsi_period = 14
    self.williams_period = 14
    self.ema_short = 20
    self.ema_long = 25  # BNF가 사용한 25일 이동평균
    self.volume_ma_period = 20
    self.max_holding_days = 3  # BNF 스타일: 최대 3일

    # BNF 스타일: 25일 이동평균 대비 하락률 기준
    self.ma_oversold_threshold = 0.80  # 25일 평균 대비 20% 하락

    if strategy_mode == "aggressive":
      # 공격적: 더 빠른 진입
      self.rsi_oversold = 40
      self.rsi_overbought = 60
      self.williams_oversold = -70
      self.williams_overbought = -30
      self.volume_threshold = 1.1
      self.ma_oversold_threshold = 0.85  # 15% 하락에서도 진입
      print("🔥 공격적 BNF 전략: 빠른 반전 포착")

    elif strategy_mode == "balanced":
      # 균형: 실제 BNF에 가까운 설정
      self.rsi_oversold = 35
      self.rsi_overbought = 65
      self.williams_oversold = -75
      self.williams_overbought = -25
      self.volume_threshold = 1.2
      self.ma_oversold_threshold = 0.80  # 20% 하락
      print("⚖️ 균형 BNF 전략: 실제 BNF 스타일")

    else:  # conservative
      # 보수적: 더 엄격한 기준
      self.rsi_oversold = 30
      self.rsi_overbought = 70
      self.williams_oversold = -80
      self.williams_overbought = -20
      self.volume_threshold = 1.3
      self.ma_oversold_threshold = 0.75  # 25% 하락
      print("🛡️ 보수적 BNF 전략: 강한 반전만 포착")

  # ===================================================================================
  # BNF 기술적 지표 계산
  # ===================================================================================

  def calculate_bnf_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
    """BNF 스타일 기술적 지표 계산 (신호 조건 완화)"""
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
    data['Williams_R'] = -100 * (high_max - data['Close']) / (
        high_max - low_min)

    # EMA 계산
    data['EMA_20'] = data['Close'].ewm(span=self.ema_short).mean()
    data['EMA_25'] = data['Close'].ewm(span=self.ema_long).mean()  # BNF의 25일

    # 거래량 분석
    data['Volume_MA'] = data['Volume'].rolling(
        self.volume_ma_period).mean() if 'Volume' in data.columns else 1
    data['Volume_Ratio'] = data['Volume'] / data[
      'Volume_MA'] if 'Volume' in data.columns else 1

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
        (data['RSI_Oversold'] & (
            data['Volume_Ratio'] > self.volume_threshold)) |

        # 조건 2: Williams %R 과매도 + 거래량 증가
        (data['Williams_Oversold'] & (
            data['Volume_Ratio'] > self.volume_threshold)) |

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

  # ===================================================================================
  # BNF 백테스트 실행
  # ===================================================================================

  def run_single_backtest(self, symbol: str, start_date: str, end_date: str) -> \
      Optional[Dict]:
    """단일 종목 BNF 백테스트"""
    try:
      stock = yf.Ticker(symbol)
      data = stock.history(start=start_date, end=end_date, auto_adjust=True,
                           prepost=True)

      if data.empty:
        print(f"❌ {symbol}: 데이터 없음", end="")
        return None

      if len(data) < self.ema_long:
        print(f"❌ {symbol}: 데이터 부족 ({len(data)}일 < {self.ema_long}일)", end="")
        return None

      # 데이터 품질 검증
      if data['Close'].isna().sum() > len(data) * 0.1:
        print(f"❌ {symbol}: 데이터 품질 불량", end="")
        return None

      avg_price = data['Close'].mean()
      if avg_price < 1 or avg_price > 10000:
        print(f"❌ {symbol}: 비정상 가격 (평균: ${avg_price:.2f})", end="")
        return None

      # BNF 지표 계산
      data = self.calculate_bnf_indicators(data)

      if data['RSI'].isna().all() or data['Williams_R'].isna().all():
        print(f"❌ {symbol}: BNF 지표 계산 실패", end="")
        return None

      # BNF 백테스트 실행
      result = self._execute_bnf_backtest(data, symbol, start_date, end_date)
      result['data'] = data

      return result

    except Exception as e:
      error_msg = str(e)
      if "No data found" in error_msg:
        print(f"❌ {symbol}: 데이터 없음", end="")
      elif "Invalid ticker" in error_msg:
        print(f"❌ {symbol}: 잘못된 티커", end="")
      elif "timeout" in error_msg.lower():
        print(f"❌ {symbol}: 타임아웃", end="")
      else:
        print(f"❌ {symbol}: {error_msg[:20]}...", end="")
      return None

  def _execute_bnf_backtest(self, data: pd.DataFrame, symbol: str,
      start_date: str, end_date: str) -> Dict:
    """BNF 백테스트 로직 실행 (실제 BNF 전략에 맞게 수정)"""
    position = 0  # 0: 노포지션, 1: 보유중
    cash = self.initial_capital
    shares = 0
    trades = []
    equity_curve = []
    entry_date = None
    entry_price = None

    for i in range(len(data)):
      current_price = data.iloc[i]['Close']
      current_date = data.index[i]

      # NaN 체크
      if pd.isna(current_price) or pd.isna(
          data.iloc[i]['BNF_Buy_Signal']) or pd.isna(
          data.iloc[i]['BNF_Sell_Signal']):
        continue

      # 보유 기간 체크 (BNF 스타일: 최대 3일)
      if position == 1 and entry_date:
        days_held = (current_date - entry_date).days
        force_exit = days_held >= self.max_holding_days
      else:
        force_exit = False

      # 매수 신호 (포지션이 없을 때)
      if data.iloc[i]['BNF_Buy_Signal'] and position == 0 and cash > 0:
        # BNF 스타일: 전액 투자
        shares = cash / current_price
        position = 1
        entry_date = current_date
        entry_price = current_price

        trades.append({
          'date': current_date,
          'action': 'BUY',
          'price': current_price,
          'shares': shares,
          'value': cash
        })
        cash = 0  # 전액 투자

      # 매도 신호 (포지션이 있을 때)
      elif position == 1 and (data.iloc[i]['BNF_Sell_Signal'] or force_exit):
        cash = shares * current_price

        if force_exit:
          action = 'SELL_TIME'
          reason = f'{days_held}일 보유 만료'
        else:
          action = 'SELL_SIGNAL'
          # 매도 이유 판별
          if data.iloc[i]['RSI'] >= self.rsi_overbought:
            reason = 'RSI 과매수'
          elif data.iloc[i]['Williams_R'] >= self.williams_overbought:
            reason = 'Williams %R 과매수'
          elif data.iloc[i]['Close'] / data.iloc[i]['EMA_25'] >= 1.10:
            reason = '25일 평균 대비 10% 상승'
          else:
            reason = '기타 매도 신호'

        trades.append({
          'date': current_date,
          'action': action,
          'price': current_price,
          'shares': shares,
          'value': cash,
          'reason': reason,
          'entry_price': entry_price,
          'profit_pct': ((
                             current_price - entry_price) / entry_price * 100) if entry_price else 0
        })

        shares = 0
        position = 0
        entry_date = None
        entry_price = None

      # 자산가치 기록
      portfolio_value = cash + (shares * current_price)
      equity_curve.append({
        'date': current_date,
        'portfolio_value': portfolio_value,
        'cash': cash,
        'stock_value': shares * current_price,
        'position': position
      })

    # 마지막 포지션 청산
    if shares > 0:
      final_price = data.iloc[-1]['Close']
      cash = shares * final_price

      trades.append({
        'date': data.index[-1],
        'action': 'SELL_FINAL',
        'price': final_price,
        'shares': shares,
        'value': cash,
        'reason': '백테스트 종료',
        'entry_price': entry_price,
        'profit_pct': ((
                           final_price - entry_price) / entry_price * 100) if entry_price else 0
      })

    # BNF 성과 지표 계산
    metrics = self._calculate_bnf_metrics(trades, equity_curve, cash,
                                          start_date, end_date)

    return {
      'symbol': symbol,
      'trades': trades,
      'equity_curve': equity_curve,
      'final_cash': cash,
      **metrics
    }

  def _calculate_bnf_metrics(self, trades: List[Dict], equity_curve: List[Dict],
      final_cash: float, start_date: str, end_date: str) -> Dict:
    """BNF 성과 지표 계산"""
    total_return = (
                       final_cash - self.initial_capital) / self.initial_capital * 100

    # BNF 스타일 거래 분석
    completed_trades = self._analyze_bnf_trades(trades)

    total_trades = len(completed_trades)
    winning_trades = sum(1 for t in completed_trades if t['is_winning'])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    # 수익/손실 분석
    profits = [t['profit_pct'] for t in completed_trades if t['is_winning']]
    losses = [t['profit_pct'] for t in completed_trades if not t['is_winning']]

    avg_profit = np.mean(profits) if profits else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(avg_profit / avg_loss) if avg_loss != 0 else float(
        'inf')

    # 평균 보유 기간 (BNF 특징)
    holding_periods = [t['holding_days'] for t in completed_trades]
    avg_holding_days = np.mean(holding_periods) if holding_periods else 0

    # 최대 낙폭
    max_drawdown = self._calculate_max_drawdown(equity_curve)

    # 테스트 기간
    test_period_days = self._calculate_test_period_days(start_date, end_date)

    return {
      'total_return': total_return,
      'win_rate': win_rate,
      'total_trades': total_trades,
      'winning_trades': winning_trades,
      'avg_profit': avg_profit,
      'avg_loss': avg_loss,
      'profit_factor': profit_factor,
      'avg_holding_days': avg_holding_days,  # BNF 특화 지표
      'max_drawdown': max_drawdown,
      'final_value': final_cash,
      'completed_trades': completed_trades,
      'test_period_days': test_period_days
    }

  def _analyze_bnf_trades(self, trades: List[Dict]) -> List[Dict]:
    """BNF 거래 분석"""
    completed_trades = []
    buy_trade = None

    for trade in trades:
      if trade['action'] == 'BUY':
        buy_trade = trade
      elif buy_trade and trade['action'] in ['SELL_SIGNAL', 'SELL_TIME']:
        profit_pct = (trade['price'] - buy_trade['price']) / buy_trade[
          'price'] * 100
        holding_days = (trade['date'] - buy_trade['date']).days

        completed_trades.append({
          'entry_date': buy_trade['date'],
          'exit_date': trade['date'],
          'entry_price': buy_trade['price'],
          'exit_price': trade['price'],
          'profit_pct': profit_pct,
          'holding_days': holding_days,
          'exit_reason': trade['action'],
          'is_winning': profit_pct > 0
        })

        buy_trade = None

    return completed_trades

  def _calculate_max_drawdown(self, equity_curve: List[Dict]) -> float:
    """최대 낙폭 계산"""
    if not equity_curve:
      return 0

    portfolio_values = [eq['portfolio_value'] for eq in equity_curve]
    peak = portfolio_values[0]
    max_drawdown = 0

    for value in portfolio_values:
      if value > peak:
        peak = value
      drawdown = (peak - value) / peak * 100
      if drawdown > max_drawdown:
        max_drawdown = drawdown

    return max_drawdown

  def _calculate_test_period_days(self, start_date: str, end_date: str) -> int:
    """테스트 기간 일수 계산"""
    try:
      start = datetime.strptime(start_date, '%Y-%m-%d')
      end = datetime.strptime(end_date, '%Y-%m-%d')
      return (end - start).days
    except:
      return 0

  # ===================================================================================
  # 다중 종목 백테스트
  # ===================================================================================

  def run_multi_stock_backtest(self, start_date: str, end_date: str,
      max_stocks: int = 20) -> pd.DataFrame:
    """다중 종목 BNF 백테스트"""
    results = []
    stocks_to_test = self.top50_stocks[:max_stocks]
    failed_stocks = []

    print(f"🎯 {len(stocks_to_test)}개 종목 BNF 백테스트 시작...")
    print(f"📅 기간: {start_date} ~ {end_date}")
    print(f"🎯 전략: 타카시 코테가와(BNF) 역추세")
    print(f"⚠️  중단하려면 Ctrl+C를 누르세요")
    print("-" * 80)

    try:
      for i, symbol in enumerate(stocks_to_test):
        print(f"진행: {i + 1:2d}/{len(stocks_to_test)} - {symbol:5s}",
              end=" ... ")

        retry_count = 0
        max_retries = 3
        success = False

        while retry_count < max_retries and not success:
          try:
            result = self.run_single_backtest(symbol, start_date, end_date)
            if result:
              results.append(result)
              avg_holding = result.get('avg_holding_days', 0)
              print(
                  f"완료 (수익률: {result['total_return']:6.2f}%, 평균보유: {avg_holding:.1f}일)")
              success = True
            else:
              print(f"데이터 부족", end="")
              if retry_count < max_retries - 1:
                print(f" - 재시도 {retry_count + 1}/{max_retries}", end="")
                time.sleep(1)
              retry_count += 1

          except KeyboardInterrupt:
            print(f"\n⏹️  BNF 백테스트가 중단되었습니다.")
            raise
          except Exception as e:
            print(f"오류: {str(e)[:30]}...", end="")
            if retry_count < max_retries - 1:
              print(f" - 재시도 {retry_count + 1}/{max_retries}", end="")
              time.sleep(1)
            retry_count += 1

        if not success:
          failed_stocks.append(symbol)
          print(" - 최종 실패")

        if i < len(stocks_to_test) - 1:
          time.sleep(0.1)

        # 진행률 요약 (매 10개마다)
        if (i + 1) % 10 == 0:
          success_count = len(results)
          print(
              f"\n📊 BNF 중간 요약: {success_count}/{i + 1} 성공 ({success_count / (i + 1) * 100:.1f}%)")
          print("-" * 80)

    except KeyboardInterrupt:
      print(f"\n⏹️  다중 종목 BNF 백테스트가 중단되었습니다.")

    # 최종 결과 요약
    print(f"\n" + "=" * 80)
    print(f"📊 BNF 백테스트 완료 요약")
    print(f"=" * 80)
    print(f"✅ 성공: {len(results)}개 종목")
    print(f"❌ 실패: {len(failed_stocks)}개 종목")
    print(f"📈 성공률: {len(results) / len(stocks_to_test) * 100:.1f}%")

    if failed_stocks:
      print(f"\n❌ 실패한 종목들:")
      for i, symbol in enumerate(failed_stocks):
        print(f"   {i + 1}. {symbol}")

    if not results:
      print("\n❌ 분석 가능한 종목이 없습니다.")
      return pd.DataFrame()

    # DataFrame 변환
    df_results = pd.DataFrame([
      {
        'Symbol': r['symbol'],
        'Initial_Capital($)': f"${self.initial_capital:,.0f}",
        'Final_Value($)': f"${r['final_value']:,.0f}",
        'Profit($)': f"${r['final_value'] - self.initial_capital:,.0f}",
        'Total_Return(%)': round(r['total_return'], 2),
        'Win_Rate(%)': round(r['win_rate'], 2),
        'Total_Trades': r['total_trades'],
        'Winning_Trades': r['winning_trades'],
        'Avg_Profit(%)': round(r['avg_profit'], 2),
        'Avg_Loss(%)': round(r['avg_loss'], 2),
        'Profit_Factor': round(r['profit_factor'], 2),
        'Avg_Holding_Days': round(r['avg_holding_days'], 1),  # BNF 특화
        'Max_Drawdown(%)': round(r['max_drawdown'], 2),
        'Test_Days': r.get('test_period_days', 0)
      }
      for r in results
    ])

    return df_results.sort_values('Total_Return(%)', ascending=False)

  # ===================================================================================
  # BNF 포트폴리오 백테스트
  # ===================================================================================

  def run_bnf_portfolio_backtest(self, start_date: str, end_date: str,
      max_stocks: int = 50) -> Dict:
    """BNF 스타일 통합 포트폴리오 백테스트"""
    print("=" * 80)
    print("💼 BNF 통합 포트폴리오 백테스트 시작")
    print("=" * 80)

    stocks_to_test = self.top50_stocks[:max_stocks]

    print(f"💰 총 자금: ${self.initial_capital:,.2f} (BNF 스타일 관리)")
    print(f"📊 대상 종목: {len(stocks_to_test)}개")
    print(f"🎯 전략: BNF 역추세 반전 포착")
    print(f"⏰ 최대 보유: {self.max_holding_days}일")

    # 각 종목별 데이터 준비
    stock_data = {}
    valid_stocks = []
    failed_stocks = []

    print(f"\n📥 BNF 데이터 다운로드 중...")
    print("-" * 80)

    for i, symbol in enumerate(stocks_to_test):
      print(f"진행: {i + 1:2d}/{len(stocks_to_test)} - {symbol}", end=" ... ")

      retry_count = 0
      max_retries = 2
      success = False

      while retry_count < max_retries and not success:
        try:
          stock = yf.Ticker(symbol)
          data = stock.history(start=start_date, end=end_date, auto_adjust=True)

          if data.empty or len(data) < self.ema_long:
            if retry_count == 0:
              print("데이터 부족", end="")
            break

          if data['Close'].isna().sum() > len(data) * 0.1:
            print("품질 불량", end="")
            break

          data = self.calculate_bnf_indicators(data)

          if data['RSI'].isna().all():
            print("지표 실패", end="")
            break

          stock_data[symbol] = data
          valid_stocks.append(symbol)
          print("완료")
          success = True

        except Exception as e:
          retry_count += 1
          if retry_count < max_retries:
            print(f"재시도({retry_count})", end="...")
            time.sleep(0.5)
          else:
            print(f"실패")
            failed_stocks.append(symbol)

        time.sleep(0.05)

      if not success and retry_count >= max_retries:
        failed_stocks.append(symbol)

      if (i + 1) % 10 == 0:
        print(
            f"📊 진행률: {len(valid_stocks)}/{i + 1} 성공 ({len(valid_stocks) / (i + 1) * 100:.1f}%)")

    print("-" * 80)
    print(f"✅ 유효 종목: {len(valid_stocks)}개")
    if failed_stocks:
      print(f"❌ 실패 종목: {len(failed_stocks)}개 - {', '.join(failed_stocks[:5])}" +
            (f" 외 {len(failed_stocks) - 5}개" if len(failed_stocks) > 5 else ""))

    if not valid_stocks:
      print("❌ 분석 가능한 종목이 없습니다.")
      return {}

    # BNF 통합 포트폴리오 백테스트 실행
    result = self._execute_bnf_portfolio_backtest(stock_data, valid_stocks)

    if result:
      result['failed_stocks'] = failed_stocks
      result['success_rate'] = len(valid_stocks) / len(stocks_to_test) * 100

    return result

  def _execute_bnf_portfolio_backtest(self, stock_data: Dict,
      valid_stocks: List[str]) -> Dict:
    """BNF 통합 포트폴리오 백테스트 로직"""
    # 모든 날짜 통합
    all_dates = None
    for symbol in valid_stocks:
      if all_dates is None:
        all_dates = set(stock_data[symbol].index)
      else:
        all_dates = all_dates.intersection(set(stock_data[symbol].index))

    all_dates = sorted(list(all_dates))

    if not all_dates:
      return {}

    print(f"📅 거래일: {len(all_dates)}일")

    # BNF 포트폴리오 상태
    total_cash = self.initial_capital
    holdings = {}  # {symbol: {'shares': float, 'entry_date': datetime, 'entry_price': float}}
    portfolio_history = []
    all_trades = []
    max_positions = 10  # BNF 스타일: 최대 동시 보유

    print(f"\n⚡ BNF 통합 포트폴리오 백테스트 실행...")
    print(f"📊 최대 동시 보유: {max_positions}개 종목")
    print(f"⏰ 최대 보유 기간: {self.max_holding_days}일")

    for i, date in enumerate(all_dates):
      if (i + 1) % 50 == 0:
        print(
            f"진행률: {i + 1}/{len(all_dates)} ({(i + 1) / len(all_dates) * 100:.1f}%)")

      daily_signals = []

      # 1. 모든 종목의 BNF 신호 수집
      for symbol in valid_stocks:
        try:
          data = stock_data[symbol]
          if date not in data.index:
            continue

          row = data.loc[date]
          current_price = row['Close']

          signal_info = {
            'symbol': symbol,
            'price': current_price,
            'buy_signal': row['BNF_Buy_Signal'],
            'sell_signal': row['BNF_Sell_Signal'],
            'rsi': row['RSI'],
            'williams_r': row['Williams_R'],
            'volume_ratio': row['Volume_Ratio']
          }
          daily_signals.append(signal_info)

        except:
          continue

      # 2. 시간 기반 강제 청산 처리 (BNF 스타일)
      symbols_to_remove = []
      for symbol, holding_info in holdings.items():
        entry_date = holding_info['entry_date']
        days_held = (date - entry_date).days

        if days_held >= self.max_holding_days:
          # 강제 청산
          current_price = next(
              (s['price'] for s in daily_signals if s['symbol'] == symbol),
              None)
          if current_price:
            shares = holding_info['shares']
            sell_value = shares * current_price
            total_cash += sell_value

            trade = {
              'date': date,
              'symbol': symbol,
              'action': 'SELL_TIME',
              'price': current_price,
              'shares': shares,
              'value': sell_value,
              'days_held': days_held
            }
            all_trades.append(trade)
            symbols_to_remove.append(symbol)

      # 강제 청산된 종목 제거
      for symbol in symbols_to_remove:
        del holdings[symbol]

      # 3. 매도 신호 처리
      symbols_to_remove = []
      for signal in daily_signals:
        symbol = signal['symbol']
        if symbol not in holdings:
          continue

        if signal['sell_signal']:
          shares = holdings[symbol]['shares']
          current_price = signal['price']
          sell_value = shares * current_price
          total_cash += sell_value

          days_held = (date - holdings[symbol]['entry_date']).days

          trade = {
            'date': date,
            'symbol': symbol,
            'action': 'SELL_SIGNAL',
            'price': current_price,
            'shares': shares,
            'value': sell_value,
            'days_held': days_held
          }
          all_trades.append(trade)
          symbols_to_remove.append(symbol)

      # 매도된 종목 제거
      for symbol in symbols_to_remove:
        del holdings[symbol]

      # 4. 매수 신호 처리 (RSI 낮은 순으로 우선순위 - BNF 스타일)
      buy_candidates = [s for s in daily_signals if
                        s['buy_signal'] and s['symbol'] not in holdings]
      buy_candidates.sort(key=lambda x: x['rsi'])  # RSI 낮은 순 (더 과매도)

      current_positions = len(holdings)
      available_slots = max_positions - current_positions

      for signal in buy_candidates[:available_slots]:
        if total_cash < 1000:
          break

        symbol = signal['symbol']
        current_price = signal['price']

        # BNF 스타일: 균등 분할 투자
        investment_ratio = min(0.2, 1.0 / max_positions)
        investment_amount = total_cash * investment_ratio

        if investment_amount >= 1000:
          shares = investment_amount / current_price
          total_cash -= investment_amount
          holdings[symbol] = {
            'shares': shares,
            'entry_date': date,
            'entry_price': current_price
          }

          trade = {
            'date': date,
            'symbol': symbol,
            'action': 'BUY',
            'price': current_price,
            'shares': shares,
            'value': investment_amount
          }
          all_trades.append(trade)

      # 5. 포트폴리오 가치 계산
      total_stock_value = 0
      for symbol, holding_info in holdings.items():
        try:
          current_price = next(
              s['price'] for s in daily_signals if s['symbol'] == symbol)
          total_stock_value += holding_info['shares'] * current_price
        except:
          continue

      total_portfolio_value = total_cash + total_stock_value

      portfolio_history.append({
        'date': date,
        'total_value': total_portfolio_value,
        'cash': total_cash,
        'stock_value': total_stock_value,
        'positions': len(holdings),
        'daily_trades': len([t for t in all_trades if t['date'] == date])
      })

    # 최종 청산
    final_date = all_dates[-1]
    for symbol, holding_info in holdings.items():
      try:
        final_price = stock_data[symbol].loc[final_date]['Close']
        total_cash += holding_info['shares'] * final_price
      except:
        continue

    # 결과 계산
    total_return = (
                       total_cash - self.initial_capital) / self.initial_capital * 100
    total_profit = total_cash - self.initial_capital

    # BNF 통계 계산
    stats = self._calculate_bnf_portfolio_stats(portfolio_history, all_trades,
                                                total_cash)

    result = {
      'initial_capital': self.initial_capital,
      'final_value': total_cash,
      'total_profit': total_profit,
      'total_return': total_return,
      'valid_stocks': valid_stocks,
      'portfolio_history': portfolio_history,
      'all_trades': all_trades,
      'final_holdings': holdings,
      'max_positions': max_positions,
      'max_holding_days': self.max_holding_days,
      **stats
    }

    self._print_bnf_portfolio_results(result)
    return result

  def _calculate_bnf_portfolio_stats(self, portfolio_history: List[Dict],
      all_trades: List[Dict], final_value: float) -> Dict:
    """BNF 포트폴리오 통계 계산"""
    if not portfolio_history:
      return {}

    values = [p['total_value'] for p in portfolio_history]

    # 최대 낙폭
    peak = values[0]
    max_drawdown = 0
    for value in values:
      if value > peak:
        peak = value
      drawdown = (peak - value) / peak * 100
      if drawdown > max_drawdown:
        max_drawdown = drawdown

    # 일일 수익률
    daily_returns = []
    for i in range(1, len(values)):
      daily_return = (values[i] - values[i - 1]) / values[i - 1] * 100
      daily_returns.append(daily_return)

    volatility = np.std(daily_returns) if daily_returns else 0
    avg_daily_return = np.mean(daily_returns) if daily_returns else 0

    # 샤프 비율
    sharpe_ratio = (avg_daily_return * 252) / (
        volatility * np.sqrt(252)) if volatility > 0 else 0

    # BNF 거래 통계
    buy_trades = len([t for t in all_trades if t['action'] == 'BUY'])
    sell_signal_trades = len(
        [t for t in all_trades if t['action'] == 'SELL_SIGNAL'])
    sell_time_trades = len(
        [t for t in all_trades if t['action'] == 'SELL_TIME'])

    # 평균 보유 기간 (BNF 특화)
    holding_periods = [t.get('days_held', 0) for t in all_trades if
                       'days_held' in t]
    avg_holding_days = np.mean(holding_periods) if holding_periods else 0

    # 포지션 통계
    avg_positions = np.mean([p['positions'] for p in portfolio_history])
    max_positions_held = max([p['positions'] for p in portfolio_history])

    return {
      'max_drawdown': max_drawdown,
      'volatility': volatility,
      'sharpe_ratio': sharpe_ratio,
      'total_trade_count': len(all_trades),
      'buy_trades': buy_trades,
      'sell_signal_trades': sell_signal_trades,
      'sell_time_trades': sell_time_trades,
      'avg_daily_return': avg_daily_return,
      'avg_positions': avg_positions,
      'max_positions_held': max_positions_held,
      'avg_holding_days': avg_holding_days  # BNF 특화
    }

  def _print_bnf_portfolio_results(self, result: Dict):
    """BNF 포트폴리오 결과 출력"""
    print(f"\n{'=' * 80}")
    print(f"💼 BNF 통합 포트폴리오 백테스트 결과")
    print(f"{'=' * 80}")

    print(f"💰 초기 자금:        ${result['initial_capital']:>12,.2f}")
    print(f"💵 최종 자산:        ${result['final_value']:>12,.2f}")
    print(f"💲 총 수익금:        ${result['total_profit']:>12,.2f}")
    print(f"📈 총 수익률:        {result['total_return']:>12.2f}%")

    # 연율화 수익률
    if result.get('portfolio_history'):
      days = len(result['portfolio_history'])
      if days > 0:
        annualized = ((result['final_value'] / result['initial_capital']) ** (
            365 / days) - 1) * 100
        print(f"📊 연율화 수익률:    {annualized:>12.2f}%")

    print(f"\n📊 BNF 포트폴리오 운용 통계:")
    print(f"📊 감시 종목:        {len(result['valid_stocks']):>12d}개")
    print(f"🎯 최대 동시보유:    {result['max_positions']:>12d}개")
    print(f"📊 평균 보유종목:    {result['avg_positions']:>12.1f}개")
    print(f"📊 최대 보유기록:    {result['max_positions_held']:>12d}개")
    print(f"⏰ 최대 보유기간:    {result['max_holding_days']:>12d}일")
    print(f"📊 평균 보유기간:    {result['avg_holding_days']:>12.1f}일")
    print(f"🔢 총 거래:         {result['total_trade_count']:>12d}회")
    print(f"📊 매수:           {result['buy_trades']:>12d}회")
    print(f"📊 신호매도:        {result['sell_signal_trades']:>12d}회")
    print(f"📊 시간매도:        {result['sell_time_trades']:>12d}회")
    print(f"📉 최대 낙폭:        {result['max_drawdown']:>12.2f}%")
    print(f"📊 변동성:          {result['volatility']:>12.2f}%")
    print(f"⚖️ 샤프 비율:       {result['sharpe_ratio']:>12.2f}")

    # 성과 평가
    if result['total_return'] > 20:
      evaluation = "🌟 우수"
    elif result['total_return'] > 10:
      evaluation = "✅ 양호"
    elif result['total_return'] > 0:
      evaluation = "📈 수익"
    else:
      evaluation = "📉 손실"
    print(f"🏆 성과 평가:        {evaluation}")

    print(f"\n💡 BNF 전략 특징:")
    print(f"   🎯 역추세 반전 전문 (타카시 코테가와 스타일)")
    print(f"   ⏰ 최대 {result['max_holding_days']}일 단기 보유")
    print(f"   📊 과매수/과매도 이중 확인 (RSI + Williams %R)")
    print(f"   💰 동적 자금 관리 (신호 기반 투자)")
    print(f"   🎯 고확률 셋업만 선별")

    print(f"{'=' * 80}")

  # ===================================================================================
  # 결과 출력 및 저장
  # ===================================================================================

  def _print_summary_statistics(self, results_df: pd.DataFrame):
    """BNF 요약 통계 출력 (중복 출력 및 데이터 오류 수정)"""
    print(f"\n📊 BNF 백테스트 결과 요약:")
    print("-" * 150)
    print(results_df.to_string(index=False))

    print(f"\n📈 BNF 전체 통계:")
    print("-" * 70)

    total_stocks = len(results_df)
    profitable_stocks = len(results_df[results_df['Total_Return(%)'] > 0])
    avg_return = results_df['Total_Return(%)'].mean()
    avg_win_rate = results_df['Win_Rate(%)'].mean()
    avg_holding_days = results_df['Avg_Holding_Days'].mean()
    avg_drawdown = results_df['Max_Drawdown(%)'].mean()

    # 수익금 계산 (오류 수정)
    profits = []
    for profit_str in results_df['Profit($)']:
      try:
        # 안전한 문자열 변환
        clean_str = str(profit_str).replace('$', '').replace(',', '').replace(
            ' ', '')
        profit_val = float(clean_str)
        profits.append(profit_val)
      except (ValueError, TypeError):
        profits.append(0.0)

    avg_profit = sum(profits) / len(profits) if profits else 0

    # 최고/최저 종목
    best = results_df.iloc[0] if len(results_df) > 0 else None
    worst = results_df.iloc[-1] if len(results_df) > 0 else None

    print(f"💰 초기 자금:     ${self.initial_capital:>10,.2f}")
    print(f"📊 분석 종목 수:   {total_stocks:>10d}개")
    print(
        f"✅ 수익 종목 수:   {profitable_stocks:>10d}개 ({profitable_stocks / total_stocks * 100:.1f}%)")
    print(f"📈 평균 수익률:   {avg_return:>10.2f}%")
    print(f"💲 평균 수익금:   ${avg_profit:>10,.2f}")
    print(f"🎯 평균 승률:     {avg_win_rate:>10.2f}%")
    print(f"⏰ 평균 보유기간: {avg_holding_days:>10.1f}일")
    print(f"📉 평균 최대낙폭: {avg_drawdown:>10.2f}%")

    if best is not None and worst is not None:
      print(f"🏆 최고 수익:     {best['Symbol']} ({best['Total_Return(%)']:6.2f}%)")
      print(
          f"📉 최저 수익:     {worst['Symbol']} ({worst['Total_Return(%)']:6.2f}%)")

    # BNF 포트폴리오 시뮬레이션 (한 번만 출력)
    portfolio_return = avg_return
    portfolio_profit = (portfolio_return / 100) * self.initial_capital

    print(f"\n💼 BNF 포트폴리오 시뮬레이션 (동일 비중 투자):")
    print(f"   예상 수익률:    {portfolio_return:>10.2f}%")
    print(f"   예상 수익금:    ${portfolio_profit:>10,.2f}")
    print(f"   예상 최종자산:  ${self.initial_capital + portfolio_profit:>10,.2f}")
    print(f"   예상 보유기간:  {avg_holding_days:>10.1f}일 (BNF 스타일)")

    # BNF 전략 성과 평가
    if avg_return > 15:
      evaluation = "🌟 우수 (실제 BNF 수준)"
    elif avg_return > 8:
      evaluation = "✅ 양호"
    elif avg_return > 0:
      evaluation = "📈 수익"
    else:
      evaluation = "📉 손실"
    print(f"\n🏆 BNF 전략 성과: {evaluation}")

  def save_results_to_csv(self, results_df: pd.DataFrame,
      filename: str = None):
    """BNF 결과를 CSV로 저장"""
    if results_df.empty:
      print("❌ 저장할 BNF 결과가 없습니다.")
      return None

    if filename is None:
      timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
      filename = f'bnf_backtest_results_{timestamp}.csv'

    output_path = os.path.join(self.results_dir, filename)

    try:
      results_df.to_csv(output_path, index=False, encoding='utf-8')
      print(f"💾 BNF 백테스트 결과 저장: {os.path.relpath(output_path)}")
      return filename
    except Exception as e:
      print(f"❌ BNF 백테스트 결과 저장 실패: {e}")
      try:
        current_dir_path = os.path.join(os.getcwd(), filename)
        results_df.to_csv(current_dir_path, index=False, encoding='utf-8')
        print(f"💾 BNF 백테스트 결과 저장 (대안 경로): {filename}")
        return filename
      except Exception as e2:
        print(f"❌ 대안 저장도 실패: {e2}")
        return None

  # ===================================================================================
  # 종합 분석
  # ===================================================================================

  def run_comprehensive_analysis(self, start_date: str, end_date: str,
      max_stocks: int = 20, detailed_analysis: str = "top5",
      save_charts: bool = True) -> Dict:
    """BNF 종합 분석 실행"""
    print("=" * 80)
    print("🚀 BNF 역추세 전략 종합 분석")
    print("=" * 80)

    # 1. 다중 종목 백테스트
    results_df = self.run_multi_stock_backtest(start_date, end_date, max_stocks)

    if results_df.empty:
      return {}

    # 2. 요약 통계 출력
    self._print_summary_statistics(results_df)

    # 3. 결과 저장
    self.save_results_to_csv(results_df)

    # 4. BNF 투자 리포트 생성
    self._save_bnf_investment_report(results_df, start_date, end_date)

    return {
      'summary_results': results_df,
      'statistics': self._calculate_summary_stats(results_df)
    }

  def _calculate_annual_returns(self, results_df: pd.DataFrame, start_date: str, end_date: str) -> Dict:
    """연도별 수익률 및 기간별 통계 계산"""
    try:
      start_year = int(start_date.split('-')[0])
      end_year = int(end_date.split('-')[0])

      # 백테스트 기간 계산
      from datetime import datetime
      start_dt = datetime.strptime(start_date, '%Y-%m-%d')
      end_dt = datetime.strptime(end_date, '%Y-%m-%d')
      total_days = (end_dt - start_dt).days
      total_years = total_days / 365.25

      # 전체 평균 수익률
      avg_annual_return = results_df['Total_Return(%)'].mean()

      # 복리 계산 (연간 복리 수익률)
      if avg_annual_return > 0:
        compound_annual_return = ((1 + avg_annual_return/100) ** (1/total_years) - 1) * 100
      else:
        compound_annual_return = avg_annual_return / total_years

      # 포트폴리오 시뮬레이션
      portfolio_total_return = avg_annual_return * total_years
      portfolio_compound_return = ((1 + avg_annual_return/100) ** total_years - 1) * 100

      # 연도별 예상 수익률 (단순화)
      annual_breakdown = {}
      for year in range(start_year, end_year + 1):
        if year == start_year and year == end_year:
          # 같은 해 내 기간
          year_fraction = total_days / 365.25
          annual_breakdown[year] = avg_annual_return * year_fraction
        elif year == start_year:
          # 시작 년도
          days_in_year = (datetime(year + 1, 1, 1) - start_dt).days
          year_fraction = days_in_year / 365.25
          annual_breakdown[year] = avg_annual_return * year_fraction
        elif year == end_year:
          # 끝 년도
          days_in_year = (end_dt - datetime(year, 1, 1)).days
          year_fraction = days_in_year / 365.25
          annual_breakdown[year] = avg_annual_return * year_fraction
        else:
          # 완전한 년도
          annual_breakdown[year] = avg_annual_return

      # BNF 실제 성과와 비교
      bnf_original_years = 8  # BNF가 8년간 운용
      bnf_original_return = ((153000000 / 13600) ** (1/8) - 1) * 100  # 연 복리 수익률

      return {
        'total_years': total_years,
        'total_days': total_days,
        'avg_annual_return': avg_annual_return,
        'compound_annual_return': compound_annual_return,
        'portfolio_total_return': portfolio_total_return,
        'portfolio_compound_return': portfolio_compound_return,
        'annual_breakdown': annual_breakdown,
        'bnf_original_cagr': bnf_original_return,
        'vs_bnf_ratio': compound_annual_return / bnf_original_return if bnf_original_return != 0 else 0
      }

    except Exception as e:
      print(f"⚠️ 연도별 수익률 계산 오류: {e}")
      return {}

  def _save_bnf_investment_report(self, results_df: pd.DataFrame, start_date: str, end_date: str):
    """BNF 투자 리포트 저장 (연도별 수익률 및 상세 분석 추가)"""
    if results_df.empty:
      print("❌ 저장할 BNF 리포트 데이터가 없습니다.")
      return None

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'bnf_investment_report_{timestamp}.txt'

    # 기본 통계 계산
    total_stocks = len(results_df)
    profitable_stocks = len(results_df[results_df['Total_Return(%)'] > 0])
    avg_return = results_df['Total_Return(%)'].mean()
    avg_holding_days = results_df['Avg_Holding_Days'].mean()
    avg_win_rate = results_df['Win_Rate(%)'].mean()
    avg_trades = results_df['Total_Trades'].mean()

    # 연도별 수익률 계산
    annual_data = self._calculate_annual_returns(results_df, start_date, end_date)

    # 성과 분석
    excellent_stocks = len(results_df[results_df['Total_Return(%)'] >= 20])
    good_stocks = len(results_df[(results_df['Total_Return(%)'] >= 10) &
                                 (results_df['Total_Return(%)'] < 20)])
    moderate_stocks = len(results_df[(results_df['Total_Return(%)'] >= 5) &
                                     (results_df['Total_Return(%)'] < 10)])

    # 포트폴리오 추천
    top_5 = results_df.head(5)
    quick_wins = results_df[(results_df['Total_Return(%)'] > 5) &
                            (results_df['Avg_Holding_Days'] <= 2.5)].head(3)

    # 리포트 작성
    report = f"""📊 BNF 역추세 전략 투자 분석 리포트
{'=' * 80}
📅 백테스트 기간: {start_date} ~ {end_date}
💰 초기 자금: ${self.initial_capital:,.2f}
⚙️ 전략 모드: {self.strategy_mode.upper()}
🎯 전략 유형: 타카시 코테가와(BNF) 역추세 전략

📈 백테스트 기간 성과 요약:
{'=' * 50}
   • 분석 종목: {total_stocks}개
   • 수익 종목: {profitable_stocks}개 ({profitable_stocks / total_stocks * 100:.1f}%)
   • 평균 수익률: {avg_return:.2f}%
   • 평균 승률: {avg_win_rate:.1f}%
   • 평균 거래 횟수: {avg_trades:.1f}회
   • 평균 보유기간: {avg_holding_days:.1f}일 (BNF 스타일)
"""

    # 연도별 수익률 정보 추가
    if annual_data:
      report += f"""
📊 백테스트 기간 분석:
{'=' * 50}
   • 총 백테스트 기간: {annual_data['total_days']:.0f}일 ({annual_data['total_years']:.1f}년)
   • 기간 중 평균 연 수익률: {annual_data['avg_annual_return']:.2f}%
   • 연복리 수익률 (CAGR): {annual_data['compound_annual_return']:.2f}%
   • 총 누적 수익률: {annual_data['portfolio_compound_return']:.2f}%

💰 포트폴리오 수익률 시뮬레이션:
{'=' * 50}
   초기 투자금: ${self.initial_capital:,.2f}
   
   📈 단순 수익률 기준:
      총 수익률: {annual_data['portfolio_total_return']:.2f}%
      예상 수익금: ${annual_data['portfolio_total_return'] / 100 * self.initial_capital:,.2f}
      예상 최종 자산: ${self.initial_capital * (1 + annual_data['portfolio_total_return'] / 100):,.2f}
   
   📊 복리 수익률 기준 (더 정확):
      총 복리 수익률: {annual_data['portfolio_compound_return']:.2f}%
      예상 수익금: ${annual_data['portfolio_compound_return'] / 100 * self.initial_capital:,.2f}
      예상 최종 자산: ${self.initial_capital * (1 + annual_data['portfolio_compound_return'] / 100):,.2f}

📈 연도별 예상 수익률 분석:
{'=' * 50}"""

      for year, return_rate in annual_data['annual_breakdown'].items():
        report += f"   {year}년: {return_rate:6.2f}%\n"

      # BNF 원조와 비교
      report += f"""
🏆 BNF 원조 성과와 비교:
{'=' * 50}
   타카시 코테가와 원조 실적:
      • 기간: 2000~2008년 (8년)
      • 초기 자금: $13,600
      • 최종 자산: $153,000,000
      • 연복리 수익률(CAGR): {annual_data['bnf_original_cagr']:.1f}%
   
   현재 백테스트 vs BNF 원조:
      • 우리 CAGR: {annual_data['compound_annual_return']:.2f}%
      • BNF 원조 CAGR: {annual_data['bnf_original_cagr']:.1f}%
      • 상대 성과: {annual_data['vs_bnf_ratio']:.2%} (BNF 대비)
      
   💡 분석:"""

      if annual_data['vs_bnf_ratio'] >= 0.5:
        report += f"\n      ✅ 우수한 성과! BNF 원조 대비 {annual_data['vs_bnf_ratio']:.1%} 수준"
      elif annual_data['vs_bnf_ratio'] >= 0.2:
        report += f"\n      📈 양호한 성과! BNF 원조 대비 {annual_data['vs_bnf_ratio']:.1%} 수준"
      else:
        report += f"\n      📉 개선 필요. BNF 원조 대비 {annual_data['vs_bnf_ratio']:.1%} 수준"

      report += f"\n      💡 BNF 전성기는 IT버블 붕괴 등 특수 상황이었음을 고려"

    # 성과 등급별 분포
    report += f"""

🏆 성과 등급별 분포:
{'=' * 50}
   • 🌟 우수 (20%+): {excellent_stocks}개 ({excellent_stocks/total_stocks*100:.1f}%)
   • ✅ 양호 (10-20%): {good_stocks}개 ({good_stocks/total_stocks*100:.1f}%)
   • 📈 보통 (5-10%): {moderate_stocks}개 ({moderate_stocks/total_stocks*100:.1f}%)
   • 📉 저조 (5% 미만): {total_stocks - excellent_stocks - good_stocks - moderate_stocks}개

🎯 BNF 투자 추천 종목:
{'=' * 50}"""

    # 상위 5개 종목
    if not top_5.empty:
      report += "\n   📈 고수익 포트폴리오 (상위 5개):\n"
      for i, (_, row) in enumerate(top_5.iterrows()):
        profit_amount = (row['Total_Return(%)'] / 100) * self.initial_capital
        report += f"      {i + 1}. {row['Symbol']}: {row['Total_Return(%)']}% "
        report += f"(수익: ${profit_amount:,.0f}, 보유: {row['Avg_Holding_Days']}일, 승률: {row['Win_Rate(%)']}%)\n"

    # 빠른 회전 포트폴리오
    if not quick_wins.empty:
      report += "\n   ⚡ 빠른 회전 포트폴리오 (BNF 스타일):\n"
      for i, (_, row) in enumerate(quick_wins.iterrows()):
        profit_amount = (row['Total_Return(%)'] / 100) * self.initial_capital
        report += f"      {i + 1}. {row['Symbol']}: {row['Total_Return(%)']}% "
        report += f"(수익: ${profit_amount:,.0f}, 보유: {row['Avg_Holding_Days']}일)\n"

    # BNF 전략 추천
    if avg_return > 15:
      strategy_advice = "💪 적극적 BNF 전략 추천"
      strategy_reason = "높은 수익률을 보이므로 강한 반전 신호를 적극 활용하세요"
    elif avg_return > 8:
      strategy_advice = "⚖️ 균형 BNF 전략 추천"
      strategy_reason = "안정적인 수익률을 보이므로 현재 전략을 유지하세요"
    elif avg_return > 0:
      strategy_advice = "🛡️ 보수적 BNF 전략 추천"
      strategy_reason = "수익률이 낮으므로 더 확실한 셋업만 선택하세요"
    else:
      strategy_advice = "⚠️ 전략 재검토 필요"
      strategy_reason = "손실이 발생하므로 시장 상황이나 파라미터를 재검토하세요"

    report += f"""

💡 BNF 전략 추천사항:
{'=' * 50}
   🎯 추천 전략: {strategy_advice}
   📝 이유: {strategy_reason}
   
   📊 백테스트 결과 기반 조언:
      • 평균 보유기간 {avg_holding_days:.1f}일은 BNF 원칙(2-3일)에 {'✅ 부합' if avg_holding_days <= 3 else '⚠️ 초과'}
      • 평균 승률 {avg_win_rate:.1f}%는 BNF 목표(60%)에 {'✅ 근접' if avg_win_rate >= 50 else '📉 미달'}
      • 연복리 수익률 {annual_data.get('compound_annual_return', 0):.1f}%는 {'🌟 우수' if annual_data.get('compound_annual_return', 0) > 15 else '📈 적정' if annual_data.get('compound_annual_return', 0) > 8 else '📉 개선 필요'}

⚠️ BNF 전략 주의사항:
{'=' * 50}
   • 과매수/과매도 반전만 노리는 역추세 전략입니다
   • 최대 {self.max_holding_days}일 보유 원칙을 철저히 지키세요
   • 강한 추세 시장에서는 성과가 제한될 수 있습니다
   • 거래량 증가 확인을 통해 반전 신호의 신뢰도를 높이세요
   • 분산 투자를 통해 개별 종목 리스크를 관리하세요
   • 감정적 거래를 피하고 시스템적으로 접근하세요

📊 사용된 BNF 전략 파라미터:
{'=' * 50}
   • RSI: {self.rsi_period}일 (과매도: {self.rsi_oversold}, 과매수: {self.rsi_overbought})
   • Williams %R: {self.williams_period}일 (과매도: {self.williams_oversold}, 과매수: {self.williams_overbought})
   • 25일 이동평균 대비 하락률: {(1-self.ma_oversold_threshold)*100:.0f}% 이상
   • 최대 보유 기간: {self.max_holding_days}일
   • 거래량 증가 임계값: {self.volume_threshold}배

🎯 BNF 전략의 핵심 원칙:
{'=' * 50}
   • "대중과 반대로 행동하라" - 타카시 코테가와
   • 25일 이동평균 대비 20% 이상 하락한 주식 매수
   • 과매수 구간에서 매도, 과매도 구간에서 매수
   • 2-3일 단기 보유로 빠른 차익실현
   • 감정을 배제하고 데이터에 기반한 거래
   • 고확률 셋업만 선별하여 거래 빈도 최소화

📈 실전 적용 가이드:
{'=' * 50}
   1. 25일 이동평균 대비 20% 이상 하락한 종목 스크리닝
   2. RSI < {self.rsi_oversold} AND Williams %R < {self.williams_oversold} 확인
   3. 거래량이 평균 대비 {self.volume_threshold}배 이상 증가 확인
   4. 매수 후 최대 3일 보유, 목표 수익률 도달시 즉시 매도
   5. 손실 시에도 3일 경과하면 무조건 청산

💰 리스크 관리:
{'=' * 50}
   • 포트폴리오의 20% 이상을 단일 종목에 투자 금지
   • 일일 손실 한도를 설정하고 준수
   • 연속 손실 발생 시 거래 중단 고려
   • 시장 상황 변화에 따른 전략 재검토

📞 추가 정보:
{'=' * 50}
   BNF 실시간 모니터링 시스템으로 자동 신호를 받아보세요.
   텔레그램 봇을 통해 실시간 매수/매도 신호를 제공합니다.

{'=' * 80}
📋 리포트 생성 정보:
   생성 시간: {datetime.now().strftime('%Y년 %m월 %d일 %H시 %M분 %S초')}
   분석 도구: BNF 역추세 전략 백테스트 시스템
   개발자: BNF Strategy Team
{'=' * 80}
"""

    # 파일 저장 (3단계 폴백)
    output_path = os.path.join(self.reports_dir, filename)
    try:
      with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
      print(f"📋 BNF 투자 리포트 저장: {os.path.abspath(output_path)}")
      return filename
    except PermissionError:
      print(f"⚠️ 권한 오류: {output_path}")
    except Exception as e:
      print(f"⚠️ 리포트 저장 오류: {e}")

    # 현재 디렉토리 시도
    try:
      current_dir_path = os.path.join(os.getcwd(), filename)
      with open(current_dir_path, 'w', encoding='utf-8') as f:
        f.write(report)
      print(f"📋 BNF 투자 리포트 저장 (현재 디렉토리): {os.path.abspath(current_dir_path)}")
      return filename
    except Exception as e2:
      print(f"⚠️ 현재 디렉토리 저장 실패: {e2}")

    # 홈 디렉토리 시도
    try:
      home_path = os.path.join(os.path.expanduser("~"), filename)
      with open(home_path, 'w', encoding='utf-8') as f:
        f.write(report)
      print(f"📋 BNF 투자 리포트 저장 (홈 디렉토리): {os.path.abspath(home_path)}")
      return filename
    except Exception as e3:
      print(f"❌ 모든 리포트 저장 시도 실패: {e3}")
      return None

  def _calculate_summary_stats(self, results_df: pd.DataFrame) -> Dict:
    """요약 통계 계산 (데이터 타입 오류 수정)"""
    if results_df.empty:
      return {}

    # 수익금 문자열을 숫자로 안전하게 변환
    profits = []
    for profit_str in results_df['Profit($)']:
      try:
        # 모든 형태의 구분자 제거 후 숫자 변환
        clean_str = str(profit_str).replace('$', '').replace(',', '').replace(
            ' ', '')
        profit_val = float(clean_str)
        profits.append(profit_val)
      except (ValueError, TypeError):
        profits.append(0.0)  # 변환 실패시 0으로 처리

    avg_profit = sum(profits) / len(profits) if profits else 0

    return {
      'total_stocks': len(results_df),
      'profitable_stocks': len(results_df[results_df['Total_Return(%)'] > 0]),
      'average_return': results_df['Total_Return(%)'].mean(),
      'average_holding_days': results_df['Avg_Holding_Days'].mean(),
      'median_return': results_df['Total_Return(%)'].median(),
      'best_stock': results_df.iloc[0]['Symbol'] if len(
          results_df) > 0 else 'N/A',
      'best_return': results_df.iloc[0]['Total_Return(%)'] if len(
          results_df) > 0 else 0,
      'worst_stock': results_df.iloc[-1]['Symbol'] if len(
          results_df) > 0 else 'N/A',
      'worst_return': results_df.iloc[-1]['Total_Return(%)'] if len(
          results_df) > 0 else 0,
      'average_profit': avg_profit
    }


# ===================================================================================
# 메인 실행 함수
# ===================================================================================

def main():
  """BNF 메인 실행 함수"""
  print("🚀 BNF 역추세 전략 백테스트")
  print("=" * 50)

  # 초기 자금 설정
  print("💰 초기 자금 설정:")
  try:
    capital = float(input("초기 자금을 입력하세요 ($): "))
    backtest = BNFCounterTrendBacktest(initial_capital=capital)
  except ValueError:
    print("잘못된 입력입니다. 기본값 $10,000을 사용합니다.")
    backtest = BNFCounterTrendBacktest(initial_capital=10000)

  # 백테스트 기간 설정
  start_date = "2021-01-01"
  end_date = "2025-07-31"

  print(f"📅 분석 기간: {start_date} ~ {end_date}")
  print(f"🎯 전략: 타카시 코테가와(BNF) 역추세")

  # BNF 종합 분석 실행
  results = backtest.run_comprehensive_analysis(
      start_date=start_date,
      end_date=end_date,
      max_stocks=10,
      detailed_analysis="top3",
      save_charts=True
  )

  if results:
    print(f"\n✅ BNF 분석 완료!")

    # BNF 투자 권장사항
    summary_results = results.get('summary_results')
    if not summary_results.empty:
      top_performers = summary_results.head(3)
      print(f"\n🏆 BNF 추천 종목 (상위 3개):")
      for i, (_, row) in enumerate(top_performers.iterrows()):
        print(
            f"{i + 1}. {row['Symbol']}: {row['Total_Return(%)']}% 수익률 (평균보유: {row['Avg_Holding_Days']}일)")

      print(f"\n🎯 BNF 전략 특징:")
      print(f"   • 역추세 반전 전문")
      print(f"   • 2-3일 단기 보유")
      print(f"   • 과매수/과매도 이중 확인")
      print(f"   • 타카시 코테가와 스타일")
  else:
    print(f"\n❌ BNF 분석 실패")


if __name__ == "__main__":
  main()
