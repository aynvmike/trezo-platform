#region imports
from AlgorithmImports import *
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import numpy as np
import pandas as pd
#endregion

class IRPrecisionFalcon(QCAlgorithm):
    def Initialize(self):
        # 1. STRICT ACCOUNT CONSTRAINTS
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2025, 12, 30)
        self.SetCash(10000) 
        
        # 2. ASSETS & BENCHMARK
        self.tickers = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AMD"]
        self.symbols = [self.AddEquity(t, Resolution.Daily).Symbol for t in self.tickers]
        
        # Reserved 'self._bench' for IR tracking (against QQQ)
        self._bench = self.AddEquity("QQQ", Resolution.Daily).Symbol 
        self.SetBenchmark(self._bench)
        
        # 3. ML PARAMETERS
        self.classifier = None
        self.scaler = StandardScaler()
        self.min_confidence = 0.70 # High bar to reduce Tracking Error
        
        # 4. SETTINGS
        self.SetWarmUp(252)
        # Train monthly - captures new market correlations
        self.Train(self.DateRules.MonthStart(), self.TimeRules.At(0, 0), self.TrainModel)

    def TrainModel(self):
        # Fetch data: 500 days captures roughly 2 years of regimes
        history = self.History(self.symbols + [self._bench], 500, Resolution.Daily)
        if history.empty: return
        
        # Vectorized close prices (prevents indexing errors)
        all_closes = history['close'].unstack(level=0)
        
        # Calculate 10-day returns for all assets at once
        # This removes the need for .iloc[-10] which caused your crash
        ret_10d = all_closes.pct_change(10).dropna()
        
        features, labels = [], []
        bench_ret = ret_10d[self._bench.Value]
        
        for s in self.symbols:
            if s.Value not in ret_10d.columns: continue
            
            s_ret = ret_10d[s.Value]
            active_ret = s_ret - bench_ret # The Alpha component
            
            # Use data to build features and look-forward labels
            for i in range(len(active_ret) - 5):
                # Features: [Current Return, Current Alpha]
                features.append([s_ret.iloc[i], active_ret.iloc[i]])
                
                # Label: 1 if the stock beats QQQ over the NEXT 5 trading days
                # This focuses the model specifically on maximizing the IR Numerator
                f_s = (all_closes[s.Value].iloc[i+5] / all_closes[s.Value].iloc[i]) - 1
                f_b = (all_closes[self._bench.Value].iloc[i+5] / all_closes[self._bench.Value].iloc[i]) - 1
                labels.append(1 if f_s > f_b else 0)

        if features:
            self.classifier = RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42)
            self.classifier.fit(self.scaler.fit_transform(features), labels)

    def OnData(self, data):
        if self.IsWarmingUp or self.classifier is None: return

        # 1. EVALUATE RECENT DATA
        # Fetch 11 days to safely calculate 10-day pct_change
        hist = self.History(self.symbols + [self._bench], 11, Resolution.Daily)['close'].unstack(level=0)
        if len(hist) < 11: return
        
        cur_rets = hist.pct_change(10).iloc[-1]
        b_ret = cur_rets[self._bench.Value]
        
        candidates = []
        for s in self.symbols:
            if s.Value not in cur_rets: continue
            s_ret = cur_rets[s.Value]
            
            # Predict probability of beating the benchmark
            feat = self.scaler.transform([[s_ret, s_ret - b_ret]])
            prob = self.classifier.predict_proba(feat)[0][1]
            
            if prob > self.min_confidence:
                candidates.append((s, prob))

        # 2. EXECUTION: OPTIMIZING INFORMATION RATIO
        # Scenario A: WE HAVE ALPHA SIGNAL
        if candidates:
            # Pick the single best stock to maximize concentration of alpha
            best_s = sorted(candidates, key=lambda x: x[1], reverse=True)[0][0]
            
            if not self.Portfolio[best_s].Invested:
                # Clear portfolio before switching to ensure NO margin is used
                self.Liquidate()
                # 0.98 ensures transaction fees are paid from cash, NOT margin
                self.SetHoldings(best_s, 0.98) 
        
        # Scenario B: NO CLEAR ALPHA SIGNAL
        # Default to the Benchmark (QQQ). 
        # Holding the benchmark makes your 'Tracking Error' ZERO.
        # This prevents the IR from falling during uncertain times.
        elif not self.Portfolio[self._bench].Invested:
            self.Liquidate()
            self.SetHoldings(self._bench, 0.98)