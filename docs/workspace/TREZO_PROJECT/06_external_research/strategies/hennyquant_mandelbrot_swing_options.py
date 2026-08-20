from AlgorithmImports import *
from datetime import timedelta
from utils import *
from ml_filter import MLTradeFilter, TradeDataCollector
import numpy as np

class MandelbrotSwingAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_end_date(2025, 1, 1)
        self.set_start_date(self.end_date - timedelta(5 * 365))
        self.set_cash(1_000_000)
        self.set_benchmark("SPY")

        self.tickers = ["GOOGL", "TSLA", "NVDA", "AAPL", "AMZN", "META", "MSFT"]
        self.symbols = {}
        self.option_symbols = {}
        for ticker in self.tickers:
            equity = self.add_equity(ticker, Resolution.DAILY)
            equity.set_data_normalization_mode(DataNormalizationMode.RAW)
            self.symbols[ticker] = equity.symbol
            option = self.add_option(ticker, Resolution.DAILY)
            option.set_filter(lambda u: u.include_weeklys().strikes(-5, 5).expiration(21, 60))
            self.option_symbols[ticker] = option.symbol

        parking_equity = self.add_equity("QQQ", Resolution.DAILY)
        parking_equity.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.symbols["QQQ"] = parking_equity.symbol

        self.lookback = 260
        self.min_data_for_trading = 52
        self.min_data_for_tail = 100
        self._price_data = {}
        self._option_iv_cache = {}
        self._option_chains_cache = {}

        for ticker in list(self.tickers) + ["QQQ"]:
            self._price_data[ticker] = {
                'open': [], 'high': [], 'low': [], 'close': [], 'volume': []
            }

        self.max_positions = 5
        self.position_size = 0.2
        self.holding_period = 20
        self.option_stop_loss = 0.4
        self.option_take_profit = 5.0
        self.min_signal_strength = 0.3

        self.signal_cfg = {
            'rsi_oversold': 40,
            'rsi_overbought': 60,
            'rsi_mr_oversold': 35,
            'rsi_mr_overbought': 65,
        }

        self.cash_parking_ticker = "QQQ"
        self.min_cash_parking_pct = 0.1

        self._entry_prices = {}
        self._entry_dates = {}
        self._entry_signals = {}
        self._trade_log = []

        self.ml_filter = MLTradeFilter(
            retrain_interval=20,
            min_samples=30,
            threshold=0.45,
        )

        self.use_ml = False
        self.trade_collector = TradeDataCollector(max_samples=2000)
        self._ml_blocked_count = 0
        self._ml_passed_count = 0

        self.set_warm_up(130, Resolution.DAILY)

        self.schedule.on(
            self.date_rules.every_day("QQQ"),
            self.time_rules.after_market_open("QQQ", 30),
            self._daily_analysis
        )

    def on_data(self, data):
        for ticker, symbol in self.symbols.items():
            if data.bars.contains_key(symbol):
                bar = data.bars[symbol]
                pd = self._price_data[ticker]
                pd['open'].append(float(bar.open))
                pd['high'].append(float(bar.high))
                pd['low'].append(float(bar.low))
                pd['close'].append(float(bar.close))
                pd['volume'].append(float(bar.volume))
                for key in pd:
                    if len(pd[key]) > self.lookback + 10:
                        pd[key] = pd[key][-(self.lookback + 10):]

        if self.is_warming_up:
            return

        for ticker in self.tickers:
            option_symbol = self.option_symbols.get(ticker)
            if not option_symbol:
                continue
            chain = data.option_chains.get(option_symbol)
            if chain:
                self._option_chains_cache[ticker] = chain
                underlying_price = chain.underlying.price
                if underlying_price > 0:
                    ivs = []
                    for contract in chain:
                        if abs(contract.strike - underlying_price) / underlying_price > 0.03:
                            continue
                        dte = (contract.expiry - self.time).days
                        if dte < 14 or dte > 45:
                            continue
                        if contract.implied_volatility > 0.01:
                            ivs.append(contract.implied_volatility)
                    if ivs:
                        self._option_iv_cache[(self.time.date(), ticker)] = float(np.median(ivs))

    def _find_option_contract(self, ticker, option_type='call', min_dte=21, max_dte=45):
        chain = self._option_chains_cache.get(ticker)
        if not chain:
            return None
        underlying_price = self.securities[self.symbols[ticker]].price
        if underlying_price <= 0:
            return None
        candidates = []
        for contract in chain:
            if not self.securities.contains_key(contract.symbol):
                continue
            if not self.securities[contract.symbol].is_tradable:
                continue
            dte = (contract.expiry - self.time).days
            if dte < min_dte or dte > max_dte:
                continue
            is_call = contract.right == OptionRight.CALL
            if option_type == 'call' and not is_call:
                continue
            if option_type == 'put' and is_call:
                continue
            moneyness = (contract.strike - underlying_price) / underlying_price
            if option_type == 'call' and -0.005 <= moneyness <= 0.05:
                candidates.append(contract)
            elif option_type == 'put' and -0.05 <= moneyness <= 0.005:
                candidates.append(contract)
        if not candidates:
            return None
        target = 0.01 if option_type == 'call' else -0.01
        candidates.sort(key=lambda c: abs((c.strike - underlying_price) / underlying_price - target))
        return candidates[0]

    def _enter_option_position(self, ticker, signal):
        direction = signal['direction']
        option_type = 'call' if direction > 0 else 'put'
        contract = self._find_option_contract(ticker, option_type)
        if not contract:
            self.debug(f"NO CONTRACT: {ticker} {option_type}")
            return False
        size = compute_position_size(signal, self.position_size)
        notional = self.portfolio.total_portfolio_value * size
        option_price = (contract.bid_price + contract.ask_price) / 2
        if option_price < 0.10:
            return False
        n_contracts = max(1, min(int(notional / (option_price * 100)), 2500))
        self.market_order(contract.symbol, n_contracts)
        self._entry_prices[ticker] = option_price
        self._entry_dates[ticker] = self.time
        self._entry_signals[ticker] = {**signal, 'contract': contract.symbol}

        if self.use_ml:
            self.trade_collector.record_entry(ticker, signal, date=self.time)

        self.debug(
            f"ENTRY: {ticker} {option_type.upper()} K={contract.strike} "
            f"x{n_contracts} @ ${option_price:.2f} | R{signal['regime']} "
            f"D={signal.get('danger_score',0):.2f} | {signal['reason']}"
        )
        return True

    def _check_entries(self, signals):
        candidates = [
            (t, s) for t, s in signals.items()
            if s['direction'] != 0 and t not in self._entry_dates and s['strength'] >= self.min_signal_strength
        ]
        candidates.sort(key=lambda x: x[1]['strength'], reverse=True)
        for ticker, signal in candidates[:2]:
            if len(self._entry_dates) >= self.max_positions:
                break

            if self.ml_filter.is_trained and self.use_ml:
                p_win = self.ml_filter.predict_win_probability(signal)
                if not self.ml_filter.should_take_trade(signal):
                    self._ml_blocked_count += 1
                    self.debug(
                        f"ML BLOCK: {ticker} | P(win)={p_win:.2f} < "
                        f"{self.ml_filter.threshold:.2f} | {signal['reason']}"
                    )
                    continue
                else:
                    self._ml_passed_count += 1
                    self.debug(
                        f"ML PASS:  {ticker} | P(win)={p_win:.2f} | {signal['reason']}"
                    )

            self._enter_option_position(ticker, signal)

    def _check_exits(self, signals):
        for ticker in list(self._entry_dates.keys()):
            entry_signal = self._entry_signals.get(ticker, {})
            contract_symbol = entry_signal.get('contract')
            if not contract_symbol:
                self._record_exit(ticker, "NO_CONTRACT")
                continue
            if not self.portfolio[contract_symbol].invested:
                self._record_exit(ticker, "EXPIRED")
                continue
            entry_price = self._entry_prices.get(ticker, 0)
            current_price = self.securities[contract_symbol].price
            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
            days_held = (self.time - self._entry_dates[ticker]).days
            sec = self.securities[contract_symbol]
            dte = (sec.expiry - self.time).days if hasattr(sec, 'expiry') else 999

            exit_reason = None
            if pnl_pct < -self.option_stop_loss:
                exit_reason = "STOP_LOSS"
            elif pnl_pct > self.option_take_profit:
                exit_reason = "TAKE_PROFIT"
            elif dte <= 5:
                exit_reason = "EXPIRY_NEAR"
            elif days_held >= self.holding_period and pnl_pct <= 0.10:
                exit_reason = "TIME_EXIT"
            elif ticker in signals:
                current_regime = signals[ticker].get('regime', 2)
                current_dir = signals[ticker].get('direction', 0)
                entry_dir = entry_signal.get('direction', 0)
                if current_regime >= 4 and days_held >= 2 and pnl_pct < 0.0:
                    exit_reason = "CRISIS_EXIT"
                elif current_regime >= 4 and days_held >= 2 and pnl_pct > 0.50:
                    exit_reason = "CRISIS_TRAIL"
                elif current_regime >= 3 and pnl_pct < -0.15 and days_held >= 3:
                    exit_reason = "ELEVATED_STOP"
                elif current_dir != 0 and current_dir == -entry_dir and days_held >= 5:
                    exit_reason = "SIGNAL_REVERSAL"

            if exit_reason:
                self.liquidate(contract_symbol)
                self.debug(
                    f"EXIT: {ticker} | PnL: {pnl_pct*100:+.1f}% | "
                    f"Days: {days_held} | DTE: {dte} | {exit_reason}"
                )
                self._record_exit(ticker, exit_reason, pnl_pct, days_held)

    def _record_exit(self, ticker, reason, pnl_pct=None, days_held=None):
        self._trade_log.append({
            'ticker': ticker, 'reason': reason, 'pnl_pct': pnl_pct,
            'days_held': days_held,
            'signal': self._entry_signals.get(ticker, {}).get('reason', 'unknown'),
            'regime': self._entry_signals.get(ticker, {}).get('regime', -1),
        })

        if pnl_pct is not None and self.use_ml:
            self.trade_collector.record_exit(ticker, pnl_pct)
            retrained = self.ml_filter.maybe_retrain(self.trade_collector)
            if retrained:
                status = self.ml_filter.get_status()
                importances = self.ml_filter.get_feature_importance(top_n=5)
                self.debug(
                    f"ML RETRAIN #{status['train_count']} | "
                    f"Samples: {self.trade_collector.n_samples} | "
                    f"CV Acc: {status['last_cv_accuracy']:.1%}"
                )
                for feat, imp in importances.items():
                    self.debug(f"  Feature: {feat:<20} Importance: {imp:.3f}")

            if not self.ml_filter.is_trained:
                X, y = self.trade_collector.get_training_data()
                if X is not None:
                    success = self.ml_filter.train(X, y)
                    if success:
                        status = self.ml_filter.get_status()
                        self.debug(
                            f"ML INITIAL TRAIN | Samples: {self.trade_collector.n_samples} | "
                            f"CV Acc: {status['last_cv_accuracy']:.1%}"
                        )
                        importances = self.ml_filter.get_feature_importance(top_n=5)
                        for feat, imp in importances.items():
                            self.debug(f"  Feature: {feat:<20} Importance: {imp:.3f}")

        self._entry_prices.pop(ticker, None)
        self._entry_dates.pop(ticker, None)
        self._entry_signals.pop(ticker, None)

    def _daily_analysis(self):
        if self.is_warming_up:
            return
        signals = {}
        for ticker in self.tickers:
            features = compute_features(
                ticker, self._price_data,
                self.min_data_for_trading, self.min_data_for_tail,
                self._option_iv_cache
            )
            if features is None:
                continue
            regime, danger = classify_regime(features)
            signal = generate_signal(features, regime, danger, self.signal_cfg)
            signals[ticker] = signal

        ref = signals.get("AAPL")
        if ref:
            self.plot("Hurst Scales", "H Short", ref.get('hurst_short', 0.5))
            self.plot("Hurst Scales", "H Med", ref.get('hurst_med', 0.5))
            self.plot("Hurst Scales", "H Long", ref.get('hurst_long', 0.5))
            self.plot("Hurst Scales", "H Divergence", ref.get('hurst_divergence', 0))
            self.plot("Mandelbrot", "Tail Index", ref.get('tail_index', 2))
            self.plot("Mandelbrot", "MF Width", ref.get('mf_width', 0))
            self.plot("Technicals", "RSI", ref.get('rsi', 50))
            self.plot("Technicals", "BB %B", ref.get('bb_pctb', 0.5))
            self.plot("Technicals", "MACD Hist", ref.get('macd_hist', 0))
            self.plot("Volatility", "Realized Vol", ref.get('realized_vol', 0))
            self.plot("Volatility", "IV/RV Ratio", ref.get('iv_rv_ratio', 1))
            self.plot("Regime", "Regime", ref.get('regime', 5))
            self.plot("Regime", "Danger", ref.get('danger_score', 0))
            self.plot("Trend", "Above SMA50", ref.get('above_sma50', 0))
            self.plot("Trend", "SMA Trend", ref.get('sma_trend', 0))

            if self.ml_filter.is_trained and self.use_ml:
                p_win = self.ml_filter.predict_win_probability(ref)
                self.plot("ML Filter", "P(Win) AAPL", p_win)
                self.plot("ML Filter", "Threshold", self.ml_filter.threshold)


        self._check_exits(signals)
        if len(self._entry_dates) < self.max_positions:
            self._check_entries(signals)
        self._manage_cash_parking(signals)

    def _manage_cash_parking(self, signals):
        parking_symbol = self.symbols[self.cash_parking_ticker]
        option_alloc = 0.0
        for ticker in self._entry_dates:
            cs = self._entry_signals.get(ticker, {}).get('contract')
            if cs and self.portfolio[cs].invested:
                option_alloc += abs(self.portfolio[cs].holdings_value) / self.portfolio.total_portfolio_value
        target = max(1.0 - option_alloc - 0.10, self.min_cash_parking_pct)
        if self.cash_parking_ticker in signals and signals[self.cash_parking_ticker].get('regime', 5) >= 3:
            target = min(target, 0.20)
        if self.portfolio[parking_symbol].invested:
            current = abs(self.portfolio[parking_symbol].holdings_value) / self.portfolio.total_portfolio_value
        else:
            current = 0
        if abs(target - current) > 0.05:
            self.set_holdings(parking_symbol, target)

    def on_end_of_algorithm(self):
        self.debug("=" * 60)
        self.debug("BACKTEST COMPLETE")
        self.debug("=" * 60)
        self.debug(f"Portfolio: ${self.portfolio.total_portfolio_value:,.2f}")
        self.debug(f"Trades: {len(self._trade_log)}")

        if self.use_ml:
            self.debug("")
            self.debug("ML TRADE FILTER SUMMARY:")
            status = self.ml_filter.get_status()
            self.debug(f"  Model trained: {status['is_trained']}")
            self.debug(f"  Times retrained: {status['train_count']}")
            self.debug(f"  Last CV accuracy: {status['last_cv_accuracy']:.1%}")
            self.debug(f"  Threshold: {status['threshold']}")
            self.debug(f"  Training samples: {self.trade_collector.n_samples}")
            self.debug(f"  Trades passed by ML: {self._ml_passed_count}")
            self.debug(f"  Trades blocked by ML: {self._ml_blocked_count}")
            if self._ml_passed_count + self._ml_blocked_count > 0:
                block_rate = self._ml_blocked_count / (self._ml_passed_count + self._ml_blocked_count)
                self.debug(f"  Block rate: {block_rate:.1%}")

            if self.ml_filter.is_trained:
                self.debug("  Top feature importances:")
                for feat, imp in self.ml_filter.get_feature_importance(top_n=10).items():
                    self.debug(f"    {feat:<22} {imp:.3f}")
            self.debug("")


        if not self._trade_log:
            return
        pnls = [t['pnl_pct'] for t in self._trade_log if t['pnl_pct'] is not None]
        if pnls:
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            self.debug(f"Win Rate: {len(wins)/len(pnls)*100:.1f}% ({len(wins)}/{len(pnls)})")
            self.debug(f"Avg Win:  {np.mean(wins)*100:+.1f}%" if wins else "Avg Win: N/A")
            self.debug(f"Avg Loss: {np.mean(losses)*100:+.1f}%" if losses else "Avg Loss: N/A")
            self.debug(f"Avg PnL:  {np.mean(pnls)*100:+.1f}%")

        self.debug("BY SIGNAL:")
        by_sig = {}
        for t in self._trade_log:
            s = t.get('signal', '?')
            if t['pnl_pct'] is not None:
                by_sig.setdefault(s, []).append(t['pnl_pct'])
        for s, pl in sorted(by_sig.items()):
            w = sum(1 for p in pl if p > 0)
            self.debug(f"  {s:<25} N={len(pl):>3} W={w/len(pl)*100:4.0f}% Avg={np.mean(pl)*100:+.1f}%")

        self.debug("BY EXIT:")
        by_exit = {}
        for t in self._trade_log:
            r = t.get('reason', '?')
            if t['pnl_pct'] is not None:
                by_exit.setdefault(r, []).append(t['pnl_pct'])
        for r, pl in sorted(by_exit.items()):
            self.debug(f"  {r:<25} N={len(pl):>3} Avg={np.mean(pl)*100:+.1f}%")

        self.debug("BY REGIME:")
        by_reg = {}
        for t in self._trade_log:
            reg = t.get('regime', -1)
            if t['pnl_pct'] is not None:
                by_reg.setdefault(reg, []).append(t['pnl_pct'])
        for reg, pl in sorted(by_reg.items()):
            w = sum(1 for p in pl if p > 0)
            self.debug(f"  Regime {reg}: N={len(pl):>3} W={w/len(pl)*100:4.0f}% Avg={np.mean(pl)*100:+.1f}%")

        self.debug("BY TICKER:")
        by_tk = {}
        for t in self._trade_log:
            tk = t.get('ticker', '?')
            if t['pnl_pct'] is not None:
                by_tk.setdefault(tk, []).append(t['pnl_pct'])
        for tk, pl in sorted(by_tk.items()):
            w = sum(1 for p in pl if p > 0)
            self.debug(f"  {tk:<8} N={len(pl):>3} W={w/len(pl)*100:4.0f}% Avg={np.mean(pl)*100:+.1f}%")