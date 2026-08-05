"""Is this result real, or did we get lucky? -- statistical honesty for Trezo.

Built 2026-08-05 from Marcos Lopez de Prado, *Advances in Financial Machine
Learning* (Wiley, 2018), chapters 14.7 and 15. Mike bought the book after a
day in which Trezo nearly changed three trading rules on the strength of about
thirty trades. Formulas are attributed; no text is reproduced.

THE PROBLEM THIS SOLVES
-----------------------
A backtest that looks good is not evidence. Three ways it lies:

1. SHORT AND SKEWED. A Sharpe ratio computed on a few dozen returns with fat
   tails is mostly noise. The PROBABILISTIC SHARPE RATIO asks the honest
   question instead: what is the probability the true Sharpe exceeds a
   benchmark, given how few observations we have and how ugly their shape is?

2. TOO MANY TRIES. If you test four giveback values and report the best, the
   winner is roughly four times more likely to be luck. De Prado's third law
   of backtesting is that a result must be reported together with the number
   of trials that produced it -- without that, its false-discovery rate cannot
   be assessed at all. The DEFLATED SHARPE RATIO raises the bar to match the
   number of trials, so trying harder no longer counts as finding something.
   Trezo has already violated this: the crypto giveback sweep on 2026-08-05
   tried four values and reported the best, unadjusted.

3. THE GEOMETRY WAS NEVER GOING TO WORK. Separately from luck, a rule can be
   arithmetically doomed: IMPLIED PRECISION says what win rate a given stop,
   target and trade frequency REQUIRE to hit a target Sharpe. If the lane's
   actual win rate is far below that, no amount of tuning saves it, and the
   honest move is to change the geometry rather than the entry filter.

And a distinction worth keeping: STRATEGY RISK is not portfolio risk. Trezo
already measures portfolio risk -- correlated baskets, concentration, effective
bets. Strategy risk is the probability that the strategy itself stops working,
which is a different question and, for a small account, the more urgent one.

NOTHING HERE DECIDES ANYTHING. These are measurements that go into proposals.
"""

from __future__ import annotations

import math
import random
from typing import Optional, Sequence

EULER_MASCHERONI = 0.5772156649015329


# --------------------------------------------------------------------------
# Normal distribution helpers -- implemented here so the module has no
# dependency on scipy, which is not in the engine's requirements.
# --------------------------------------------------------------------------

def norm_cdf(x: float) -> float:
    """P(Z <= x) for a standard normal."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse of norm_cdf. Acklam's rational approximation, accurate to
    about 1.15e-9 -- far beyond what any of this needs."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _moments(xs: Sequence[float]) -> tuple[float, float, float, float]:
    """mean, stdev, skewness, kurtosis (kurtosis = 3 for a normal)."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0, 3.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd == 0:
        return m, 0.0, 0.0, 3.0
    skew = sum(((x - m) / sd) ** 3 for x in xs) / n
    kurt = sum(((x - m) / sd) ** 4 for x in xs) / n
    return m, sd, skew, kurt


def sharpe(returns: Sequence[float]) -> Optional[float]:
    """Non-annualised Sharpe of a return series."""
    m, sd, _, _ = _moments(returns)
    if sd <= 0:
        return None
    return m / sd


# --------------------------------------------------------------------------
# 1. Probabilistic Sharpe Ratio  (de Prado 14.7.2, after Bailey & de Prado 2012)
# --------------------------------------------------------------------------

def probabilistic_sharpe_ratio(returns: Sequence[float],
                               benchmark_sr: float = 0.0) -> Optional[float]:
    """Probability that the TRUE Sharpe exceeds `benchmark_sr`.

    Rises with a longer track record and with positive skew; FALLS with fat
    tails. A short record of lumpy returns is penalised exactly as it should
    be. Returns a probability in [0,1], or None if it cannot be computed.
    """
    n = len(returns)
    if n < 3:
        return None
    sr = sharpe(returns)
    if sr is None:
        return None
    _, _, skew, kurt = _moments(returns)
    denom_sq = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom_sq <= 0:
        return None
    z = (sr - benchmark_sr) * math.sqrt(n - 1) / math.sqrt(denom_sq)
    return norm_cdf(z)


# --------------------------------------------------------------------------
# 2. Deflated Sharpe Ratio  (de Prado 14.7.3, after Bailey & de Prado 2014)
# --------------------------------------------------------------------------

def expected_max_sharpe(trial_sharpes: Sequence[float]) -> Optional[float]:
    """The Sharpe you would expect to see from the BEST of N trials even if
    every strategy were worthless. This is the bar a result must clear."""
    n = len(trial_sharpes)
    if n < 2:
        return None
    m = sum(trial_sharpes) / n
    var = sum((s - m) ** 2 for s in trial_sharpes) / (n - 1)
    if var <= 0:
        return 0.0
    g = EULER_MASCHERONI
    return math.sqrt(var) * ((1 - g) * norm_ppf(1 - 1.0 / n)
                             + g * norm_ppf(1 - 1.0 / (n * math.e)))


def deflated_sharpe_ratio(returns: Sequence[float],
                          trial_sharpes: Sequence[float]) -> Optional[float]:
    """PSR measured against the expected best-of-N benchmark rather than zero.

    `trial_sharpes` must include EVERY variant tried, not just the winner --
    that is the whole point of de Prado's third law. Passing only the winner
    silently defeats the correction.
    """
    sr_star = expected_max_sharpe(trial_sharpes)
    if sr_star is None:
        return None
    return probabilistic_sharpe_ratio(returns, benchmark_sr=sr_star)


# --------------------------------------------------------------------------
# 3. Implied precision  (de Prado 15.3, snippet 15.3 `binHR`)
# --------------------------------------------------------------------------

def implied_precision(stop_loss: float, profit_take: float,
                      freq: float, target_sr: float) -> Optional[float]:
    """The MINIMUM win rate a geometry needs to reach `target_sr`.

    stop_loss   negative fraction, e.g. -0.018 for a 1.8% stop
    profit_take positive fraction, e.g.  0.030 for a 3.0% target
    freq        bets per year
    target_sr   the annualised Sharpe being aimed at

    This is the forward-looking version of the geometry question. It says what
    the arithmetic demands, before any argument about entry quality.
    """
    try:
        sl, pt = float(stop_loss), float(profit_take)
        if pt <= sl or freq <= 0:
            return None
        a = (freq + target_sr ** 2) * (pt - sl) ** 2
        b = (2 * freq * sl - target_sr ** 2 * (pt - sl)) * (pt - sl)
        c = freq * sl ** 2
        disc = b * b - 4 * a * c
        # At target_sr = 0 the discriminant is analytically EXACTLY zero, so
        # floating-point noise pushes it a hair negative and the break-even
        # answer is lost. The clamp must be RELATIVE: an absolute 1e-12
        # tolerance silently failed on ordinary dollar-scale inputs, where
        # b^2 is ~1e5 and the rounding error is ~1e-9.
        if disc < 0 and abs(disc) <= 1e-9 * max(b * b, 1.0):
            disc = 0.0
        if disc < 0 or a == 0:
            return None
        p = (-b + math.sqrt(disc)) / (2.0 * a)
        return p if 0.0 <= p <= 1.0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def sharpe_from_geometry(stop_loss: float, profit_take: float,
                         freq: float, win_rate: float) -> Optional[float]:
    """The forward Sharpe a geometry implies at a given win rate.

    The inverse of implied_precision, and the sanity check on it: feeding one
    into the other must return the input.
    """
    try:
        sl, pt, p = float(stop_loss), float(profit_take), float(win_rate)
        if not (0 < p < 1) or pt <= sl or freq <= 0:
            return None
        num = (pt - sl) * p + sl
        den = (pt - sl) * math.sqrt(p * (1 - p))
        if den == 0:
            return None
        return (num / den) * math.sqrt(freq)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# --------------------------------------------------------------------------
# 4. Strategy risk  (de Prado 15.4)
# --------------------------------------------------------------------------

def strategy_risk(outcomes: Sequence[float], target_sr: float = 0.0,
                  years_elapsed: float = 1.0, years_to_assess: float = 2.0,
                  iterations: int = 2000,
                  seed: Optional[int] = 7) -> Optional[dict]:
    """P[the win rate falls below what this geometry needs] -- the chance the
    STRATEGY fails, which is not the same as the portfolio losing money.

    `outcomes` is a series of per-trade P&L figures. The win and loss legs are
    estimated from the data itself, so the geometry measured is the one that
    actually happened rather than the one that was configured.
    """
    wins = [o for o in outcomes if o > 0]
    losses = [o for o in outcomes if o <= 0]
    if len(wins) < 2 or len(losses) < 2 or years_elapsed <= 0:
        return None
    pi_plus = sum(wins) / len(wins)
    pi_minus = sum(losses) / len(losses)
    if pi_plus <= 0 or pi_minus >= 0:
        return None
    # Express the legs as fractions of the average absolute bet so the
    # geometry is scale-free and comparable across lanes of different size.
    scale = (abs(pi_plus) + abs(pi_minus)) / 2.0
    if scale <= 0:
        return None
    pt, sl = pi_plus / scale, pi_minus / scale
    n_per_year = len(outcomes) / years_elapsed
    p_needed = implied_precision(sl, pt, n_per_year, target_sr)
    if p_needed is None:
        return None

    rng = random.Random(seed)
    draws = max(1, int(n_per_year * years_to_assess))
    ps = []
    for _ in range(iterations):
        sample = [outcomes[rng.randrange(len(outcomes))] for _ in range(draws)]
        ps.append(len([s for s in sample if s > 0]) / draws)
    p_bar = sum(ps) / len(ps)
    var = sum((x - p_bar) ** 2 for x in ps) / (len(ps) - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    risk = norm_cdf((p_needed - p_bar) / sd) if sd > 0 else (
        1.0 if p_bar < p_needed else 0.0)
    return {
        "observed_win_rate": round(p_bar, 4),
        "required_win_rate": round(p_needed, 4),
        "margin": round(p_bar - p_needed, 4),
        "prob_strategy_fails": round(risk, 4),
        "avg_win": round(pi_plus, 4), "avg_loss": round(pi_minus, 4),
        "bets_per_year": round(n_per_year, 1),
        "target_sharpe": target_sr,
    }


# --------------------------------------------------------------------------
# 5. Sequence and bootstrap tests
# --------------------------------------------------------------------------
#
# A correction worth recording. The first version of this shuffled the order
# of a fixed list of trade outcomes and compared the total against the real
# total -- but shuffling a list cannot change its sum, so the comparison was
# TRUE on every iteration and the p-value was meaningless. It looked like a
# test and tested nothing.
#
# Order can only affect PATH, so that is what sequence_test measures. Whether
# the average outcome is distinguishable from zero is a different question,
# answerable from the outcomes alone, and that is bootstrap_mean_test.
#
# Chan's full permutation test -- randomising ENTRY DATES against the real
# price series -- needs the price path, not just the outcomes, and therefore
# belongs in the rule-replay harness rather than here.

def sequence_test(outcomes: Sequence[float], iterations: int = 10000,
                  seed: Optional[int] = 7) -> Optional[dict]:
    """Was the ORDER of results unusually kind or cruel?

    The total is invariant under shuffling, so the only thing sequence can
    change is the path: how deep the worst drawdown ran. That matters for any
    path-dependent rule -- a trailing stop, a kill-switch, a margin call --
    because two identical totals are not equivalent if one of them passed
    through a hole that would have tripped a guard.
    """
    n = len(outcomes)
    if n < 5:
        return None

    def max_dd(seq):
        run = peak = 0.0
        worst = 0.0
        for x in seq:
            run += x
            peak = max(peak, run)
            worst = min(worst, run - peak)
        return worst

    real_dd = max_dd(outcomes)
    rng = random.Random(seed)
    pool = list(outcomes)
    worse = 0
    for _ in range(iterations):
        rng.shuffle(pool)
        if max_dd(pool) <= real_dd:
            worse += 1
    return {
        "real_max_drawdown": round(real_dd, 2),
        "iterations": iterations,
        "fraction_of_orderings_at_least_as_deep": round(worse / iterations, 4),
        "note": ("total P&L is unchanged by shuffling, so this tests PATH only. "
                 "A low fraction means the real ordering was unusually gentle; "
                 "a high one means the drawdown was luck of the draw."),
    }


def bootstrap_mean_test(outcomes: Sequence[float], iterations: int = 10000,
                        seed: Optional[int] = 7) -> Optional[dict]:
    """Is the average outcome distinguishable from zero?

    Resamples the trades with replacement and reports how often the resampled
    average lands on the other side of zero. With a small sample this will
    usually be inconclusive -- which is the honest answer, and the whole
    reason this module exists.
    """
    n = len(outcomes)
    if n < 5:
        return None
    real_mean = sum(outcomes) / n
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        s = [outcomes[rng.randrange(n)] for _ in range(n)]
        means.append(sum(s) / n)
    means.sort()
    lo = means[int(0.025 * iterations)]
    hi = means[int(0.975 * iterations)]
    crossed = len([m for m in means if (m <= 0) != (real_mean <= 0)]) / iterations
    return {
        "mean_per_trade": round(real_mean, 3),
        "ci95_low": round(lo, 3), "ci95_high": round(hi, 3),
        "fraction_crossing_zero": round(crossed, 4),
        "conclusive": bool(lo > 0 or hi < 0),
        "note": ("if the 95% interval straddles zero the sample cannot tell "
                 "profit from noise, however suggestive the total looks"),
    }
