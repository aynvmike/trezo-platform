from AlgorithmImports import *
import numpy as np

class TheOmniscientParadox(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2019, 1, 1)
        self.set_end_date(datetime.now())
        self.set_cash(100000)
        self.settings.rebalance_portfolio_on_insight_changes = False
        self.universe_settings.resolution = Resolution.MINUTE
        self.universe_settings.leverage = 1.0

        self.tickers = ["SOXL", "TECL", "TQQQ", "FAS", "ERX", "UUP", "TMF", "BIL"]
        self.symbols = [self.add_equity(t, Resolution.MINUTE).symbol for t in self.tickers]
        self.safe = self.symbols[-1]

        self.indicators = {}
        for s in self.symbols:
            self.indicators[s] = {
                'roc_fast': self.rocp(s, 9, Resolution.DAILY),
                'roc_med': self.rocp(s, 21, Resolution.DAILY),
                'roc_slow': self.rocp(s, 63, Resolution.DAILY),
                'vol': self.std(s, 21, Resolution.DAILY),
                'rsi': self.rsi(s, 14, MovingAverageType.WILDERS, Resolution.DAILY),
                'sma': self.sma(s, 50, Resolution.DAILY)
            }

        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.spy_sma = self.sma(self.spy, 200, Resolution.DAILY)

        self.lookback_vol = 20
        self.target_vol = 0.80
        self.confidence_threshold = 0.10
        self.current_holding = None
        
        self.schedule.on(self.date_rules.every_day(self.symbols[0]), 
                         self.time_rules.before_market_close(self.symbols[0], 5), 
                         self.rebalance)
        self.set_warm_up(100)

    def on_data(self, data):
        pass

    def rebalance(self):
        if self.is_warming_up: return
        
        spy_trend = self.securities[self.spy].close > self.spy_sma.current.value
        
        scores = {}
        for s in self.symbols:
            if s == self.safe: continue
            
            inds = self.indicators[s]
            if not inds['roc_slow'].is_ready: continue
            
            fast = inds['roc_fast'].current.value
            med = inds['roc_med'].current.value
            slow = inds['roc_slow'].current.value
            vol = inds['vol'].current.value
            rsi = inds['rsi'].current.value
            price = self.securities[s].close
            sma = inds['sma'].current.value
            
            if vol == 0: vol = 1.0
            
            weighted_mom = (fast * 0.5) + (med * 0.3) + (slow * 0.2)
            
            risk_adj_mom = weighted_mom / vol
            
            trend_score = 1.0 if price > sma else 0.5
            
            rsi_penalty = 1.0
            if rsi > 85: rsi_penalty = 0.9
            elif rsi < 30: rsi_penalty = 0.9
            
            final_score = risk_adj_mom * trend_score * rsi_penalty
            scores[s] = final_score

        if not scores: return

        sorted_assets = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_asset = sorted_assets[0][0]
        best_score = sorted_assets[0][1]
        
        target_asset = self.current_holding
        
        if self.current_holding is None:
            if best_score > 0:
                target_asset = best_asset
            else:
                target_asset = self.safe
        else:
            current_score = scores.get(self.current_holding, -999)
            
            if self.current_holding == self.safe:
                if best_score > 0.02:
                    target_asset = best_asset
            else:
                if best_score > current_score * (1 + self.confidence_threshold):
                    target_asset = best_asset
                elif current_score < -0.02:
                    target_asset = self.safe

        if not spy_trend and target_asset != self.safe:
             uup_sym = self.symbols[self.tickers.index("UUP")]
             uup_score = scores.get(uup_sym, -999)
             
             if uup_score > 0 and uup_score > scores.get(target_asset, -999):
                 target_asset = uup_sym
             elif scores.get(target_asset, -999) < 0:
                 target_asset = self.safe

        if target_asset and target_asset != self.safe:
            hist = self.history(target_asset, self.lookback_vol + 1, Resolution.DAILY)
            if not hist.empty:
                rets = hist.close.pct_change().dropna()
                curr_vol = np.std(rets) * np.sqrt(252)
                
                if curr_vol > 0:
                    weight = self.target_vol / curr_vol
                else:
                    weight = 1.0
                
                target_weight = min(1.0, weight)
            else:
                target_weight = 1.0
        elif target_asset == self.safe:
            target_weight = 1.0
        else:
            target_weight = 0.0

        self.current_holding = target_asset
        
        invested = [x.symbol for x in self.active_securities.values() if x.invested]
        for s in invested:
            if s != target_asset:
                self.liquidate(s)

        if target_asset:
            curr_val = self.portfolio[target_asset].holdings_value
            tot_val = self.portfolio.total_portfolio_value
            curr_w = curr_val / tot_val if tot_val > 0 else 0
            
            if abs(curr_w - target_weight) > 0.05:
                self.set_holdings(target_asset, target_weight)
                
            rem = 1.0 - target_weight
            if rem > 0.1 and target_asset != self.safe:
                self.set_holdings(self.safe, rem)