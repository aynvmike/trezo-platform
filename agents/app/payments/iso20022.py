"""ISO 20022 payments adapter.

This module is the canonical money-movement model for Trezo. Every
future flow that touches real cash — KINDRIP bank pulls, vault
deposits/withdrawals, broker funding, profit withdrawals — should
build a `PaymentInstruction` here, persist it via the helpers, and
hand the rendered XML to the bank / PSP at the boundary.

Why this exists: ISO 20022 is now the global payments standard.
Fedwire cut over in March 2025; the SWIFT MT-to-MX migration
completed in November 2025; FedNow and RTP speak it natively;
SEPA Inst, CHAPS, T2/T2S are all on it. Building on top of any
proprietary format today would mean a rewrite later.

What's modeled:
- `PaymentInstruction` dataclass mirroring the pain.001
  (CustomerCreditTransferInitiation) field set with enough fields
  to also render pacs.008 (FIToFICustomerCreditTransfer).
- `to_pain001_xml()` — the customer-to-bank "please move money" doc.
- `to_pacs008_xml()` — the bank-to-bank "I'm moving money" doc.
- `persist()` / `load()` helpers around the payment_instructions table.

What's intentionally NOT here:
- Real bank connectivity. Today nothing leaves Trezo. The XML is
  rendered for inspection / audit, not transmission.
- camt.053 (statement) parsing. We'll add it when reconciliation
  needs to consume incoming bank statements.
- A schema validator. The Python stdlib `xml.etree` doesn't validate
  against XSD; production runs should pipe the rendered XML through
  `xmllint --schema iso20022/pain.001.001.09.xsd` in CI before any
  real submission.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional
from xml.etree import ElementTree as ET

import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.payments.iso20022")


PaymentMethod = Literal["TRF", "CHK", "DD", "TRA"]
ServiceLevel = Literal["INST", "NURG", "URGP", "SEPA", "SDVA"]
PaymentStatus = Literal[
    "draft", "queued", "submitted", "accepted",
    "rejected", "settled", "returned", "cancelled",
]
Flow = Literal[
    "kindrip_contribution", "vault_deposit", "vault_withdrawal",
    "broker_funding", "profit_withdrawal", "manual",
]


# --- Namespaces -------------------------------------------------------------

# We target the 2019 release set (pain.001.001.09, pacs.008.001.08) used
# by Fedwire FR23.0 and SWIFT MX. Upgrade in lockstep with the rails.
NS_PAIN001 = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
NS_PACS008 = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"


# --- Party + amount value objects -------------------------------------------

@dataclass
class Party:
    """Either side of the payment - debtor (payer) or creditor (payee).

    Field names map directly to ISO 20022 elements so the XML
    generator stays simple.
    """
    name: str
    account_id: str                              # IBAN, BBAN, or proprietary
    account_type: str = "OTHR"                   # IBAN, BBAN, OTHR
    agent_bic: Optional[str] = None              # BICFI of the bank
    agent_clearing_system: Optional[str] = None  # USABA, CHAPS, ...
    agent_clearing_id: Optional[str] = None      # routing number / sort code
    country: Optional[str] = None                # ISO 3166-1 alpha-2


@dataclass
class Amount:
    """ISO 20022 ActiveOrHistoricCurrencyAndAmount."""
    value: float
    currency: str = "USD"


# --- The canonical instruction ----------------------------------------------

@dataclass
class PaymentInstruction:
    """Trezo's canonical money-movement record. Every real money flow
    in the platform produces one of these.

    Persist it via `persist()` (writes to `payment_instructions`).
    Render the wire XML via `to_pain001_xml()` / `to_pacs008_xml()`.
    """

    # Trezo internal
    user_id: str
    flow: Flow

    # Amount + dates
    amount: Amount
    requested_execution_date: date

    # Counterparties
    debtor: Party
    creditor: Party

    # ISO 20022 envelope
    message_id: str = field(default_factory=lambda: f"TREZO-{uuid.uuid4().hex[:24].upper()}")
    end_to_end_id: str = field(default_factory=lambda: f"E2E-{uuid.uuid4().hex[:30].upper()}")
    instruction_id: Optional[str] = None
    uetr: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Payment terms
    payment_method: PaymentMethod = "TRF"
    service_level: ServiceLevel = "NURG"
    local_instrument: Optional[str] = None       # FNW, RTP, CHAPS, etc.
    category_purpose: Optional[str] = None       # INTC, CASH, SALA, ...
    purpose_code: Optional[str] = None
    remittance_info_unstructured: Optional[str] = None
    remittance_info_structured: Optional[dict[str, Any]] = None

    # Lifecycle
    status: PaymentStatus = "draft"
    status_reason: Optional[str] = None
    status_reason_description: Optional[str] = None
    settlement_date: Optional[date] = None

    # Linkbacks
    related_table: Optional[str] = None
    related_id: Optional[str] = None

    # ---- Serialization ----

    def to_row(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "message_id": self.message_id,
            "end_to_end_id": self.end_to_end_id,
            "instruction_id": self.instruction_id,
            "uetr": self.uetr,
            "status": self.status,
            "status_reason": self.status_reason,
            "status_reason_description": self.status_reason_description,
            "flow": self.flow,
            "amount_value": self.amount.value,
            "amount_currency": self.amount.currency,
            "requested_execution_date": self.requested_execution_date.isoformat(),
            "settlement_date": self.settlement_date.isoformat() if self.settlement_date else None,
            "debtor_name": self.debtor.name,
            "debtor_account_id": self.debtor.account_id,
            "debtor_account_type": self.debtor.account_type,
            "debtor_agent_bic": self.debtor.agent_bic,
            "debtor_agent_clearing_system": self.debtor.agent_clearing_system,
            "debtor_agent_clearing_id": self.debtor.agent_clearing_id,
            "debtor_country": self.debtor.country,
            "creditor_name": self.creditor.name,
            "creditor_account_id": self.creditor.account_id,
            "creditor_account_type": self.creditor.account_type,
            "creditor_agent_bic": self.creditor.agent_bic,
            "creditor_agent_clearing_system": self.creditor.agent_clearing_system,
            "creditor_agent_clearing_id": self.creditor.agent_clearing_id,
            "creditor_country": self.creditor.country,
            "payment_method": self.payment_method,
            "service_level": self.service_level,
            "local_instrument": self.local_instrument,
            "category_purpose": self.category_purpose,
            "purpose_code": self.purpose_code,
            "remittance_info_unstructured": self.remittance_info_unstructured,
            "remittance_info_structured": self.remittance_info_structured,
            "related_table": self.related_table,
            "related_id": self.related_id,
        }


# --- XML rendering ----------------------------------------------------------

def _el(parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


def _party_block(parent: ET.Element, label: str, p: Party) -> None:
    """Add a Dbtr/Cdtr block + its agent/account siblings."""
    party = _el(parent, label)
    _el(party, "Nm", p.name)
    if p.country:
        addr = _el(party, "PstlAdr")
        _el(addr, "Ctry", p.country)

    # Agent block (DbtrAgt / CdtrAgt)
    agt = _el(parent, label + "Agt")
    fin = _el(agt, "FinInstnId")
    if p.agent_bic:
        _el(fin, "BICFI", p.agent_bic)
    if p.agent_clearing_system and p.agent_clearing_id:
        clr = _el(fin, "ClrSysMmbId")
        clr_sys = _el(clr, "ClrSysId")
        _el(clr_sys, "Cd", p.agent_clearing_system)
        _el(clr, "MmbId", p.agent_clearing_id)

    # Account block (DbtrAcct / CdtrAcct)
    acct = _el(parent, label + "Acct")
    acct_id = _el(acct, "Id")
    if p.account_type == "IBAN":
        _el(acct_id, "IBAN", p.account_id)
    else:
        othr = _el(acct_id, "Othr")
        _el(othr, "Id", p.account_id)


def to_pain001_xml(pi: PaymentInstruction) -> str:
    """Render a pain.001.001.09 CustomerCreditTransferInitiation.

    This is the message a customer (Trezo, on behalf of the user)
    sends to its bank: "please initiate this credit transfer."
    """
    ET.register_namespace("", NS_PAIN001)
    root = ET.Element(f"{{{NS_PAIN001}}}Document")
    cct = _el(root, "CstmrCdtTrfInitn")

    # GroupHeader
    grp = _el(cct, "GrpHdr")
    _el(grp, "MsgId", pi.message_id)
    _el(grp, "CreDtTm", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    _el(grp, "NbOfTxs", "1")
    _el(grp, "CtrlSum", f"{pi.amount.value:.2f}")
    init = _el(grp, "InitgPty")
    _el(init, "Nm", pi.debtor.name)

    # PaymentInformation (one PmtInf per debit; one CdtTrfTxInf per credit)
    pmt = _el(cct, "PmtInf")
    _el(pmt, "PmtInfId", f"PMT-{pi.message_id}")
    _el(pmt, "PmtMtd", pi.payment_method)
    _el(pmt, "NbOfTxs", "1")
    _el(pmt, "CtrlSum", f"{pi.amount.value:.2f}")

    # PaymentTypeInformation
    ptp = _el(pmt, "PmtTpInf")
    svc = _el(ptp, "SvcLvl")
    _el(svc, "Cd", pi.service_level)
    if pi.local_instrument:
        loc = _el(ptp, "LclInstrm")
        _el(loc, "Cd", pi.local_instrument)
    if pi.category_purpose:
        cat = _el(ptp, "CtgyPurp")
        _el(cat, "Cd", pi.category_purpose)

    _el(pmt, "ReqdExctnDt", pi.requested_execution_date.isoformat())

    # Debtor side
    _party_block(pmt, "Dbtr", pi.debtor)

    # CreditTransferTransactionInformation
    tx = _el(pmt, "CdtTrfTxInf")
    pid_block = _el(tx, "PmtId")
    if pi.instruction_id:
        _el(pid_block, "InstrId", pi.instruction_id)
    _el(pid_block, "EndToEndId", pi.end_to_end_id)
    _el(pid_block, "UETR", pi.uetr)

    amt = _el(tx, "Amt")
    inst = _el(amt, "InstdAmt", f"{pi.amount.value:.2f}")
    inst.set("Ccy", pi.amount.currency)

    # Creditor side
    _party_block(tx, "Cdtr", pi.creditor)

    if pi.purpose_code:
        purp = _el(tx, "Purp")
        _el(purp, "Cd", pi.purpose_code)
    if pi.remittance_info_unstructured:
        rmt = _el(tx, "RmtInf")
        _el(rmt, "Ustrd", pi.remittance_info_unstructured)

    return _serialize(root)


def to_pacs008_xml(pi: PaymentInstruction) -> str:
    """Render a pacs.008.001.08 FIToFICustomerCreditTransfer.

    This is the bank-to-bank "I'm sending the money" leg that follows
    a pain.001. Useful for testing what a downstream FI would receive.
    """
    ET.register_namespace("", NS_PACS008)
    root = ET.Element(f"{{{NS_PACS008}}}Document")
    fitofi = _el(root, "FIToFICstmrCdtTrf")

    grp = _el(fitofi, "GrpHdr")
    _el(grp, "MsgId", pi.message_id)
    _el(grp, "CreDtTm", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    _el(grp, "NbOfTxs", "1")
    sttlm = _el(grp, "SttlmInf")
    _el(sttlm, "SttlmMtd", "CLRG")  # cleared

    tx = _el(fitofi, "CdtTrfTxInf")
    pid_block = _el(tx, "PmtId")
    if pi.instruction_id:
        _el(pid_block, "InstrId", pi.instruction_id)
    _el(pid_block, "EndToEndId", pi.end_to_end_id)
    _el(pid_block, "UETR", pi.uetr)

    amt = _el(tx, "IntrBkSttlmAmt", f"{pi.amount.value:.2f}")
    amt.set("Ccy", pi.amount.currency)

    if pi.settlement_date:
        _el(tx, "IntrBkSttlmDt", pi.settlement_date.isoformat())

    _party_block(tx, "Dbtr", pi.debtor)
    _party_block(tx, "Cdtr", pi.creditor)
    if pi.remittance_info_unstructured:
        rmt = _el(tx, "RmtInf")
        _el(rmt, "Ustrd", pi.remittance_info_unstructured)

    return _serialize(root)


def _serialize(root: ET.Element) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(root, encoding="unicode"))


# --- Supabase persistence ---------------------------------------------------

def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


async def persist(pi: PaymentInstruction, *, render_xml: bool = True) -> Optional[str]:
    """Insert (or upsert by end_to_end_id) the instruction. When
    render_xml is True, also caches the rendered pain.001 + pacs.008
    XML on the row for inspection. Returns the row id, or None on
    miss."""
    client = _supabase()
    if not client:
        return None

    row = pi.to_row()
    if render_xml:
        row["rendered_pain001_xml"] = to_pain001_xml(pi)
        row["rendered_pacs008_xml"] = to_pacs008_xml(pi)
        row["rendered_at"] = datetime.now(timezone.utc).isoformat()

    def _sync():
        return (
            client.table("payment_instructions")
            .upsert(row, on_conflict="user_id,end_to_end_id")
            .execute()
        )

    try:
        res = await asyncio.to_thread(_sync)
        data = res.data or []
        return data[0]["id"] if data else None
    except Exception as e:  # noqa: BLE001
        log.warning("iso20022.persist_failed", error=str(e)[:200])
        return None


async def load(instruction_id: str) -> Optional[dict[str, Any]]:
    """Read an instruction back by id. Used by reconciliation paths
    and the admin inspector."""
    client = _supabase()
    if not client:
        return None

    def _sync():
        return (
            client.table("payment_instructions")
            .select("*")
            .eq("id", instruction_id)
            .maybe_single()
            .execute()
        )

    try:
        res = await asyncio.to_thread(_sync)
        return res.data if res else None
    except Exception as e:  # noqa: BLE001
        log.warning("iso20022.load_failed", error=str(e)[:200])
        return None
