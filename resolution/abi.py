"""Decode UMA Optimistic Oracle dispute logs and Polymarket ancillary data.

Every dispute of a Polymarket question emits, from UMA's Optimistic Oracle
(V2 and its managed variant share the event):

    event DisputePrice(address indexed requester, address indexed proposer,
                       address indexed disputer, bytes32 identifier,
                       uint256 timestamp, bytes ancillaryData, int256 proposedPrice)

``requester`` is the UmaCtfAdapter that asked the question. The adapter
derives the question's id as keccak256(ancillaryData) when it is initialized,
and its dispute callback recomputes it from the same bytes, so
``keccak256(ancillaryData) == questionID`` joins a dispute to its market
(Polymarket/uma-ctf-adapter, src/UmaCtfAdapter.sol). The ancillary data is
the question text as listed, ``q: title: ..., description: ...`` followed by
``res_data`` and ``,initializer:<address>``, and it never changes, which makes
it the listing-time rule text.
"""
from __future__ import annotations

import re

from .keccak import keccak256, keccak_hex

DISPUTE_PRICE_SIG = "DisputePrice(address,address,address,bytes32,uint256,bytes,int256)"
DISPUTE_PRICE_TOPIC = "0x5165909c3d1c01c5d1e121ac6f6d01dda1ba24bc9e1f975b5a375339c15be7f3"

# Proposed prices are 18-decimal fixed point: 1e18 = first outcome (YES),
# 0 = second outcome (NO), 0.5e18 = 50-50, and int256 min = "too early".
ONE = 10 ** 18
TOO_EARLY = -(2 ** 255)

# UmaCtfAdapter deployments listed in Polymarket's docs and the neg-risk
# operator's adapter; used only to label requesters in the data audit.
KNOWN_ADAPTERS = {
    "0xcb1822859cef82cd2eb4e6276c7916e692995130": "UmaCtfAdapter v1",
    "0x6a9d222616c90fca5754cd1333cfd9b7fb6a4f74": "UmaCtfAdapter v2",
    "0x157ce2d672854c848c9b79c49a8cc6cc89176a49": "UmaCtfAdapter v3",
    "0x2f5e3684cb1f318ec51b00edba38d79ac2c0aa9d": "UmaCtfAdapter (neg risk)",
}


def _word(data: bytes, k: int) -> bytes:
    return data[32 * k: 32 * k + 32]


def topic_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def price_to_outcome(price: int | None) -> float | None:
    """Map an oracle price to the share paid to the first outcome."""
    if price is None:
        return None
    if price == TOO_EARLY:
        return None
    return price / ONE


def decode_dispute_log(log: dict) -> dict:
    """Decode one eth_getLogs entry for DisputePrice."""
    topics = log["topics"]
    if topics[0].lower() != DISPUTE_PRICE_TOPIC:
        raise ValueError("not a DisputePrice log")
    raw = log["data"]
    data = bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
    identifier = _word(data, 0).rstrip(b"\x00").decode("ascii", "replace")
    timestamp = int.from_bytes(_word(data, 1), "big")
    offset = int.from_bytes(_word(data, 2), "big")
    proposed = int.from_bytes(_word(data, 3), "big", signed=True)
    length = int.from_bytes(data[offset: offset + 32], "big")
    ancillary = data[offset + 32: offset + 32 + length]
    block = log.get("blockNumber")
    ts = log.get("blockTimestamp")
    return {
        "oracle": log.get("address", "").lower(),
        "requester": topic_address(topics[1]),
        "proposer": topic_address(topics[2]),
        "disputer": topic_address(topics[3]),
        "identifier": identifier,
        "request_timestamp": timestamp,
        "proposed_price": str(proposed),
        "too_early": proposed == TOO_EARLY,
        "ancillary_hex": "0x" + ancillary.hex(),
        "question_id": keccak_hex(ancillary),
        "block": int(block, 16) if isinstance(block, str) else block,
        "block_timestamp": int(ts, 16) if isinstance(ts, str) else ts,
        "tx": log.get("transactionHash"),
        "log_index": int(log["logIndex"], 16) if isinstance(log.get("logIndex"), str)
        else log.get("logIndex"),
    }


def encode_dispute_log(*, requester: str, proposer: str, disputer: str,
                       ancillary: bytes, proposed_price: int, request_timestamp: int,
                       block: int, oracle: str = "0x" + "ee" * 20,
                       identifier: bytes = b"YES_OR_NO_QUERY", tx: str | None = None,
                       log_index: int = 0) -> dict:
    """Build a DisputePrice log as eth_getLogs returns it (for tests and demos)."""
    def addr(a: str) -> str:
        return "0x" + "0" * 24 + a.lower().removeprefix("0x")
    padded = ancillary + b"\x00" * ((-len(ancillary)) % 32)
    head = (identifier.ljust(32, b"\x00")
            + request_timestamp.to_bytes(32, "big")
            + (128).to_bytes(32, "big")
            + proposed_price.to_bytes(32, "big", signed=True))
    body = len(ancillary).to_bytes(32, "big") + padded
    return {
        "address": oracle,
        "topics": [DISPUTE_PRICE_TOPIC, addr(requester), addr(proposer), addr(disputer)],
        "data": "0x" + (head + body).hex(),
        "blockNumber": hex(block),
        "transactionHash": tx or "0x" + keccak256(f"{block}:{log_index}".encode()).hex(),
        "logIndex": hex(log_index),
        "removed": False,
    }


_INIT = re.compile(r",\s*initializer:\s*(?:0x)?([0-9a-fA-F]{40})\s*$")


def parse_ancillary(text: str | bytes) -> dict:
    """Split Polymarket ancillary data into title, description and initializer."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    out = {"title": None, "description": None, "initializer": None}
    m = _INIT.search(text)
    if m:
        out["initializer"] = "0x" + m.group(1).lower()
        text = text[: m.start()]
    body = text
    res = re.search(r"\s*res_data:", body)
    if res:
        body = body[: res.start()]
    m = re.match(r"\s*q:\s*title:\s*(.*?),\s*description:\s*(.*)\Z", body, re.S)
    if m:
        out["title"], out["description"] = m.group(1).strip(), m.group(2).strip()
    else:
        out["description"] = body.strip()
    return out


def ancillary_for(title: str, description: str, initializer: str) -> bytes:
    """Ancillary data in the shape Polymarket lists questions (for synthetic data)."""
    return (f"q: title: {title}, description: {description} res_data: p1: 0, p2: 1, "
            f"p3: 0.5. Where p1 corresponds to No, p2 to Yes, p3 to unknown/50-50."
            f",initializer:{initializer.lower().removeprefix('0x')}").encode("utf-8")


def condition_id(oracle: str, question_id: str, outcome_slots: int = 2) -> str:
    """Gnosis CTF condition id: keccak256(oracle . questionId . outcomeSlotCount)."""
    packed = (bytes.fromhex(oracle.lower().removeprefix("0x"))
              + bytes.fromhex(question_id.lower().removeprefix("0x"))
              + outcome_slots.to_bytes(32, "big"))
    return keccak_hex(packed)
