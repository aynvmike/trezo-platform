"""Hierarchical Risk Parity -- how to split capital across lanes.

Built 2026-08-05 from Marcos Lopez de Prado, *Advances in Financial Machine
Learning* (Wiley, 2018), chapter 16. Phase 6 of the library plan. Formulas are
attributed and re-implemented; no text is reproduced. Pure Python -- the engine
has no numpy, pandas or scipy.

WHY THIS CHAPTER, AND WHY NOW
-----------------------------
Mike identified the cheapest route to his goal: more working lanes. Portfolio
Sharpe rises with the square root of the number of EFFECTIVE bets, so the
question that follows immediately is how capital should be split between them.
De Prado notes that a practical application of HRP is precisely determining
allocations across multiple strategies -- which is Trezo's problem exactly.

MARKOWITZ'S CURSE
-----------------
The textbook answer is mean-variance optimisation, and it fails in a specific
and cruel way. Inverting a covariance matrix requires it to be well
conditioned; the more correlated the holdings, the worse the conditioning, so
a small estimation error produces a wildly different answer.

De Prado's phrasing of the trap: the more correlated the investments, the
greater the need for diversification -- and the more likely the solution is
unstable. The benefit of diversifying is often more than cancelled by the error
in estimating it.

There is a hard data requirement behind this. Estimating a non-singular
covariance matrix of size N needs at least N(N+1)/2 independent observations.

  For Trezo: 6 lanes needs 21 observations -- achievable. Fourteen individual
  POSITIONS would need 105, and Trezo has about 61 closed trades. So a
  position-level covariance matrix cannot honestly be estimated yet; a
  LANE-level one can. That single fact decides the right granularity.

And a caution worth repeating because it is inconvenient: de Prado cites
research showing that even naive equally-weighted portfolios have beaten
mean-variance and risk-based optimisation out of sample. Any allocation method,
including this one, has to earn its place against simply splitting evenly.

WHAT HRP DOES INSTEAD
---------------------
It never inverts anything. Three stages:

  1. TREE CLUSTERING -- turn correlations into distances and group the things
     that behave alike.
  2. QUASI-DIAGONALISATION -- reorder so similar things sit adjacent, which
     concentrates the large covariances near the diagonal.
  3. RECURSIVE BISECTION -- split capital top-down between adjacent groups in
     inverse proportion to their variance.

Because it works on a tree rather than a fully connected graph, it tolerates
ill-conditioned and even singular covariance matrices -- which is exactly the
situation a small account with correlated crypto lanes is in.

THE LIMITATION, STATED BEFORE ANYONE IS MISLED BY IT
---------------------------------------------------
HRP allocates by RISK. It knows nothing whatsoever about RETURN.

Run on Trezo's real lanes it hands forex 99.8% and crypto 0.2% -- because
forex barely trades, so its variance is tiny, so it looks safe. It earned
$3.97 in three weeks. A lane that does NOTHING has near-zero variance and
will attract almost all the capital.

That is not a defect in this implementation; it is what the method is. Risk
parity answers "how should risk be balanced", not "which risks are worth
taking". It must therefore be paired with an expectancy screen -- see
runtime/r_multiples.py. The correct division of labour:

    expectancy decides WHICH lanes deserve capital
    HRP decides HOW MUCH each of those gets

Feeding HRP a lane with no edge is asking a question it was never built to
answer, and it will give a confident wrong reply.

NOTHING HERE MOVES CAPITAL. Measurement for proposals.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence


# --------------------------------------------------------------------------
# Basic statistics, pure Python
# --------------------------------------------------------------------------

def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _cov(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    ma, mb = _mean(a[:n]), _mean(b[:n])
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (n - 1)


def covariance_matrix(series: dict[str, Sequence[float]]) -> tuple[list[str], list[list[float]]]:
    keys = list(series.keys())
    m = [[_cov(series[i], series[j]) for j in keys] for i in keys]
    return keys, m


def correlation_matrix(series: dict[str, Sequence[float]]) -> tuple[list[str], list[list[float]]]:
    keys, cov = covariance_matrix(series)
    n = len(keys)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            di, dj = math.sqrt(cov[i][i]), math.sqrt(cov[j][j])
            out[i][j] = (cov[i][j] / (di * dj)) if di > 0 and dj > 0 else 0.0
            out[i][j] = max(-1.0, min(1.0, out[i][j]))
    return keys, out


def min_observations_for(n_assets: int) -> int:
    """De Prado's floor: N(N+1)/2 observations to estimate a non-singular
    covariance matrix of size N. Below this, any allocation derived from it
    is arithmetic performed on noise."""
    return int(n_assets * (n_assets + 1) / 2)


# --------------------------------------------------------------------------
# Stage 1 -- tree clustering
# --------------------------------------------------------------------------

def correlation_distance(corr: list[list[float]]) -> list[list[float]]:
    """d[i,j] = sqrt(0.5 * (1 - rho[i,j])). A proper metric: 0 when identical,
    1 when uncorrelated, and larger still when inversely correlated."""
    n = len(corr)
    return [[math.sqrt(max(0.0, 0.5 * (1.0 - corr[i][j]))) for j in range(n)]
            for i in range(n)]


def euclidean_distance_of_distances(d: list[list[float]]) -> list[list[float]]:
    """The distance BETWEEN COLUMNS of the distance matrix.

    The subtlety that makes HRP work: d[i,j] compares two assets directly,
    while this compares how each asset relates to EVERY other asset. Two
    things can be uncorrelated with each other and still belong together
    because they relate to the rest of the book the same way.
    """
    n = len(d)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            out[i][j] = math.sqrt(sum((d[k][i] - d[k][j]) ** 2 for k in range(n)))
    return out


def linkage_tree(dbar: list[list[float]]) -> list[tuple]:
    """Agglomerative clustering, average linkage. Returns merge steps as
    (left, right, distance, size) with cluster ids >= n for merged nodes --
    the same shape scipy would produce, implemented without it."""
    n = len(dbar)
    clusters: dict[int, list[int]] = {i: [i] for i in range(n)}
    dist = {(i, j): dbar[i][j] for i in range(n) for j in range(n) if i < j}
    merges: list[tuple] = []
    nxt = n
    while len(clusters) > 1:
        best, bd = None, None
        ids = sorted(clusters)
        for a_i in range(len(ids)):
            for b_i in range(a_i + 1, len(ids)):
                a, b = ids[a_i], ids[b_i]
                key = (a, b) if a < b else (b, a)
                dv = dist.get(key)
                if dv is None:
                    continue
                if bd is None or dv < bd:
                    best, bd = (a, b), dv
        if best is None:
            break
        a, b = best
        merged = clusters.pop(a) + clusters.pop(b)
        clusters[nxt] = merged
        merges.append((a, b, bd, len(merged)))
        for c in list(clusters):
            if c == nxt:
                continue
            # average linkage between the new cluster and each remaining one
            vals = []
            for x in merged:
                for y in clusters[c]:
                    k = (x, y) if x < y else (y, x)
                    if x < n and y < n:
                        vals.append(dbar[x][y])
            if vals:
                key = (c, nxt) if c < nxt else (nxt, c)
                dist[key] = sum(vals) / len(vals)
        nxt += 1
    return merges


def quasi_diagonal_order(merges: list[tuple], n: int) -> list[int]:
    """Stage 2 -- the leaf order implied by the tree, so correlated items sit
    next to each other and the big covariances gather near the diagonal."""
    if not merges:
        return list(range(n))
    members: dict[int, list[int]] = {i: [i] for i in range(n)}
    nxt = n
    for a, b, _, _ in merges:
        members[nxt] = members.get(a, [a]) + members.get(b, [b])
        nxt += 1
    return members[nxt - 1]


# --------------------------------------------------------------------------
# Stage 3 -- recursive bisection
# --------------------------------------------------------------------------

def _cluster_variance(cov: list[list[float]], idx: Sequence[int]) -> float:
    """Variance of a group under inverse-variance weights.

    De Prado's step 3b: inverse-variance allocation is optimal for a diagonal
    covariance matrix, and stage 2 has made the matrix approximately diagonal,
    so this is a fair local estimate.
    """
    inv = []
    for i in idx:
        v = cov[i][i]
        inv.append(1.0 / v if v > 0 else 0.0)
    tot = sum(inv)
    if tot <= 0:
        return 0.0
    w = [x / tot for x in inv]
    out = 0.0
    for a, ia in enumerate(idx):
        for b, ib in enumerate(idx):
            out += w[a] * cov[ia][ib] * w[b]
    return out


def recursive_bisection(cov: list[list[float]], order: Sequence[int]) -> dict[int, float]:
    """Split capital top-down, inversely to each side's variance."""
    w = {i: 1.0 for i in order}
    groups = [list(order)]
    while groups:
        nxt = []
        for g in groups:
            if len(g) > 1:
                half = len(g) // 2
                nxt.append(g[:half])
                nxt.append(g[half:])
        groups = nxt
        for k in range(0, len(groups) - 1, 2):
            g0, g1 = groups[k], groups[k + 1]
            v0, v1 = _cluster_variance(cov, g0), _cluster_variance(cov, g1)
            tot = v0 + v1
            alpha = 1.0 - (v0 / tot) if tot > 0 else 0.5
            for i in g0:
                w[i] *= alpha
            for i in g1:
                w[i] *= (1.0 - alpha)
    return w


def hrp_weights(series: dict[str, Sequence[float]]) -> Optional[dict]:
    """Full HRP allocation across named return series.

    Returns weights plus the honesty checks: how many observations were used
    against the minimum the covariance estimate requires, and how the answer
    compares to simply splitting evenly.
    """
    names = [k for k, v in series.items() if v and len(v) >= 3]
    if len(names) < 2:
        return None
    sub = {k: list(series[k]) for k in names}
    keys, corr = correlation_matrix(sub)
    _, cov = covariance_matrix(sub)
    d = correlation_distance(corr)
    dbar = euclidean_distance_of_distances(d)
    merges = linkage_tree(dbar)
    order = quasi_diagonal_order(merges, len(keys))
    w = recursive_bisection(cov, order)
    tot = sum(w.values()) or 1.0
    weights = {keys[i]: round(w[i] / tot, 4) for i in sorted(w)}
    n_obs = min(len(v) for v in sub.values())
    need = min_observations_for(len(keys))
    equal = round(1.0 / len(keys), 4)
    return {
        "weights": weights,
        "order": [keys[i] for i in order],
        "n_assets": len(keys),
        "observations": n_obs,
        "observations_required": need,
        "estimate_trustworthy": n_obs >= need,
        "equal_weight": equal,
        "max_deviation_from_equal": round(
            max(abs(v - equal) for v in weights.values()), 4),
        "note": (
            f"{n_obs} observations against the {need} this covariance estimate "
            f"requires -- " + ("sufficient" if n_obs >= need else
                               "NOT ENOUGH, treat these weights as indicative "
                               "only and prefer equal weighting until the "
                               "sample catches up")),
    }
