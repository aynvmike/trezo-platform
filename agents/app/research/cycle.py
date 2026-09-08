"""Public, synchronous research API. Call from an isolated/background worker."""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
import re

from .core import (Assumptions, Candidate, MAX_CANDIDATES, POLICY_VERSION, digest, finite,
                   normalize_candles, propose, refine, replay, screen)
from .store import LeaseLost, Store


def _capital_snapshot(raw, *, book_id, starting_capital):
    """Validate a caller-observed paper account; this does not fetch or attest it.

    Only allowlisted evidence is persisted, so a broker account response or
    credential cannot accidentally be copied into a research artifact. The
    read adapter owns freshness; a small receive-clock tolerance is allowed.
    """
    required = {"book_id", "source", "currency", "equity_usd", "observed_at", "account_fingerprint"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("broker equity requires a complete, allowlisted capital snapshot")
    if raw["book_id"] != book_id or raw["source"] != "alpaca_paper_account" or raw["currency"] != "USD":
        raise ValueError("capital snapshot book, source or currency is invalid")
    fingerprint = raw["account_fingerprint"]
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("capital snapshot requires a SHA-256 account fingerprint")
    equity = finite(raw["equity_usd"], "snapshot equity")
    if equity != starting_capital:
        raise ValueError("capital snapshot equity must match starting capital")
    observed = raw["observed_at"]
    if not isinstance(observed, str) or len(observed) > 64:
        raise ValueError("capital snapshot observed_at must be an aware ISO timestamp")
    try:
        observed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("capital snapshot observed_at must be an aware ISO timestamp") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("capital snapshot observed_at must include a timezone")
    observed = observed.astimezone(timezone.utc)
    if observed > datetime.now(timezone.utc) + timedelta(seconds=30):
        raise ValueError("capital snapshot cannot be future-dated")
    return {"book_id": book_id, "source": raw["source"], "currency": "USD",
            "equity_usd": equity, "observed_at": observed.isoformat(),
            "account_fingerprint": fingerprint}


def run_cycle(db_path, *, book_id: str, symbol: str, candles: list,
              starting_capital: float, commission_bps: float, slippage_bps: float,
              fixed_cost_usd: float = 0.0, cycle_key: str | None = None,
              capital_basis: str = "fixed_scenario", capital_snapshot: dict | None = None) -> dict:
    """Compose two rules, refine from TRAIN, and screen all four on validation.

    A supplied cycle key (for example a UTC date) reuses the first persisted
    snapshot for that scope; otherwise its data hash is the key. Fixed
    scenarios retain their original capital-specific identity and lineage.
    Broker-equity research requires an explicit cycle key and an observed
    paper-account snapshot. Its first capital observation is frozen for that
    key, while later cycles retest the same training lineage at new equity.
    Repeated calls resume failures or return the immutable completed result.
    No data or secret is fetched, and no trade or transfer can be executed.
    """
    if not isinstance(book_id, str) or not book_id.strip() or len(book_id) > 128:
        raise ValueError("an explicit bounded book id is required")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9./-]{0,23}", symbol):
        raise ValueError("a canonical symbol is required")
    if cycle_key is not None and (not isinstance(cycle_key, str) or not cycle_key or len(cycle_key) > 128):
        raise ValueError("cycle key must be a nonempty bounded string")
    if capital_basis not in ("fixed_scenario", "broker_equity"):
        raise ValueError("capital basis must be fixed_scenario or broker_equity")
    if capital_basis == "fixed_scenario" and capital_snapshot is not None:
        raise ValueError("fixed scenarios cannot carry a broker equity snapshot")
    if capital_basis == "broker_equity" and (cycle_key is None or not cycle_key.strip()):
        raise ValueError("broker equity requires an explicit cycle key")
    normalized = normalize_candles(candles)
    assumptions = Assumptions(finite(starting_capital, "starting capital"),
                              finite(commission_bps, "commission bps"),
                              finite(slippage_bps, "slippage bps"),
                              finite(fixed_cost_usd, "fixed cost"))
    data_hash = digest(normalized)
    lineage = {"book_id": book_id, "symbol": symbol, "assumptions": asdict(assumptions),
               "policy_version": POLICY_VERSION}
    if capital_basis == "broker_equity":
        capital_snapshot = _capital_snapshot(capital_snapshot, book_id=book_id,
                                             starting_capital=assumptions.starting_capital)
        # Do not hash the balance or observation time: a later read of the
        # same account cannot rewrite today's job or reset tomorrow's parent.
        lineage["assumptions"] = {key: value for key, value in asdict(assumptions).items()
                                  if key != "starting_capital"}
        lineage.update(capital_basis=capital_basis, source=capital_snapshot["source"],
                       currency=capital_snapshot["currency"],
                       account_fingerprint=capital_snapshot["account_fingerprint"])
    scope = {**lineage, "cycle_key": cycle_key or data_hash}
    job_id = digest(scope)
    request = {**scope, "candles": normalized, "dataset_hash": data_hash,
               "split_index": int(len(normalized) * 0.7), "lineage_scope": digest(lineage),
               "assumptions": asdict(assumptions), "capital_basis": capital_basis,
               "capital_snapshot": capital_snapshot}
    store = Store(db_path)
    # Freeze the continuation choice with the job request. A retry must
    # not change its parent because some other cycle finished meanwhile.
    request["continuation"] = store.prior_training_candidate(
        book_id, request["lineage_scope"], normalized[request["split_index"] - 1]["timestamp"])
    claim = store.claim(job_id, book_id, request)
    base = {"job_id": job_id, "book_id": book_id, "symbol": symbol,
            "execution_enabled": False, "forward_evidence_required": True}
    if claim["status"] == "completed":
        return {**claim["result"], "cached": True}
    if claim["status"] != "claimed":
        return {**base, **claim, "cached": False}

    token = claim["token"]
    frozen = claim["request"]
    # Older fixed-scenario requests have no capital metadata. Their identity,
    # stored assumptions, parent and immutable completed evidence remain valid.
    base.update(capital_basis=frozen.get("capital_basis", "fixed_scenario"),
                capital_snapshot=frozen.get("capital_snapshot"))
    bars = frozen["candles"]
    split = frozen["split_index"]
    assumptions = Assumptions(**frozen["assumptions"])
    trials = []
    try:
        seeds = propose(book_id, symbol)
        continuation = frozen.get("continuation")
        if continuation:
            spec = continuation["spec"]
            prior = Candidate(**{field.name: spec[field.name] for field in fields(Candidate)})
            seeds = [prior, next(seed for seed in seeds if seed.candidate_id != prior.candidate_id)]
        # Complete seed training BEFORE producing children. The refinement
        # function has no access to validation data or validation results.
        seed_training = []
        for candidate in seeds:
            store.candidate(job_id, token, candidate.candidate_id, candidate.spec())
            train = replay(bars, candidate, assumptions, start=0, end=split, phase="train")
            seed_training.append((candidate, train))
        parent, parent_train = max(seed_training,
                                   key=lambda pair: (pair[1]["net_pnl_usd"], pair[0].candidate_id))
        children = refine(parent, parent_train)
        candidates = seeds + children
        if len(candidates) > MAX_CANDIDATES:
            raise ValueError("research candidate budget exceeded")
        known_training = {candidate.candidate_id: train for candidate, train in seed_training}
        for candidate in candidates:
            store.candidate(job_id, token, candidate.candidate_id, candidate.spec())
            train = known_training.get(candidate.candidate_id)
            if train is None:
                train = replay(bars, candidate, assumptions, start=0, end=split, phase="train")
            validation = replay(bars, candidate, assumptions, start=split, end=len(bars), phase="validation")
            state, reasons = screen(train, validation)
            trial = {"candidate_id": candidate.candidate_id, "parent_id": candidate.parent_id,
                     "spec": candidate.spec(), "train": train, "validation": validation,
                     "state": state, "reasons": reasons, "forward_evidence_required": True,
                     "execution_enabled": False}
            store.trial(job_id, token, candidate.candidate_id, trial)
            trials.append(trial)
        result = {**base, "status": "completed", "cached": False,
                  "policy_version": POLICY_VERSION, "cycle_key": frozen["cycle_key"],
                  "dataset_hash": frozen["dataset_hash"], "bar_count": len(bars),
                  "split_index": split, "train_fraction": 0.7,
                  "assumptions": frozen["assumptions"], "trials": trials,
                  "generation_method": "restricted_deterministic_rule_composition",
                  "refinement_evidence": "training_window_only",
                  "continuation": continuation,
                  "profitability_verified": False,
                  "limitations": ["Historical screening is not verified profitability or deployment eligibility.",
                    "All four trials are retained; this pilot does not correct statistical confidence for repeated searches.",
                    "Validation must not guide additional refinement; locked forward paper evidence is still required.",
                    "Fractional, long-only, one-position simulation excludes order-book liquidity, partial fills and broker eligibility.",
                    "Drawdown uses bar-close marked equity, not intrabar extrema.",
                    "Caller must supply completed, consistently spaced bars; no news/social or arbitrary generated code is evaluated."]}
        store.finish(job_id, token, result)
        return result
    except Exception as exc:
        # Persistent failure is visible and bounded. Completed trial rows
        # remain immutable and are checked, not overwritten, on retry.
        error = f"{type(exc).__name__}: {str(exc)[:240]}"
        try:
            store.fail(job_id, token, error)
        except LeaseLost:
            pass
        return {**base, "status": "failed", "error": error,
                "attempts": claim["attempts"], "cached": False}
