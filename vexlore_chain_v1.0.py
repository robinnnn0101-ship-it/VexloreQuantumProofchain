#!/usr/bin/env python3
"""
Vexlore Quantumproof Chain  v1.0 — NETWORK + PEERS
Educational post-quantum blockchain prototype.

New in v1.0:
  - Multi-node peer discovery & gossip (HTTP)
  - Block + transaction propagation
  - Node identity (PQ keypair + short node ID)
  - Simple difficulty adjustment (every 20 blocks)
  - peers.json persistence
  - Explorer shows peers, network height, node ID
  - CLI: connect peer, list peers, broadcast, force sync

Previous (v0.9):
  - Multi-sig vaults, time-locks, send rules, public explorer

Not production-ready – for learning only.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("[!] requests not installed → peer networking disabled")
    print("    Install with:  pip install requests")

try:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.fernet import Fernet
    import base64
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    print("[!] cryptography not installed → wallet encryption disabled")
    print("    Install with:  pip install cryptography")

sys.path.insert(0, str(Path(__file__).parent / "dilithium_src"))
try:
    from dilithium_py.ml_dsa import ML_DSA_44
    HAS_PQ = True
except ImportError:
    print("[-] dilithium_src not found — using demo FakePQ signatures")
    HAS_PQ = False

    class FakePQ:
        @staticmethod
        def keygen():
            sk = os.urandom(32)
            pk = hashlib.sha256(sk).digest()
            return pk, sk

        @staticmethod
        def sign(sk, msg):
            return hashlib.sha256(sk + msg).digest()

        @staticmethod
        def verify(pk, msg, sig):
            return True

    ML_DSA_44 = FakePQ()

VERSION = "1.0"
BLOCK_REWARD = 50.0
INITIAL_DIFFICULTY = 4
DIFFICULTY_ADJUST_INTERVAL = 20          # blocks
TARGET_BLOCK_TIME = 20.0                # seconds (educational)
MAX_TX_PER_BLOCK = 20
ORPHAN_MAX = 50
MIN_SEND_AMOUNT = 0.01
MAX_MEMO_LEN = 120
ALLOW_SELF_SEND = False
MAX_PEERS = 20
PEER_TIMEOUT = 30                       # seconds for HTTP calls
GOSSIP_INTERVAL = 45                    # seconds background gossip

DATA_DIR = Path("vexlore_data")
CHAIN_FILE = DATA_DIR / "chain.json"
WALLET_FILE = DATA_DIR / "wallet.enc"
PEERS_FILE = DATA_DIR / "peers.json"
HTTP_PORT = 5000
HTTP_HOST = "0.0.0.0"
VEXLOREBOT_URL = "https://t.me/VexloreBOT"


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------
def pq_keygen() -> Tuple[bytes, bytes]:
    return ML_DSA_44.keygen()

def pq_sign(secret_key: bytes, message: bytes) -> bytes:
    return ML_DSA_44.sign(secret_key, message)

def pq_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    try:
        return ML_DSA_44.verify(public_key, message, signature)
    except Exception:
        return False

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def address_from_pubkey(pubkey: bytes) -> str:
    return "VEX" + sha256(pubkey)[:20]

def node_id_from_pubkey(pubkey: bytes) -> str:
    return "N" + sha256(pubkey)[:10].upper()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Transaction:
    tx_id: str
    sender: str
    recipient: str
    amount: float
    timestamp: float
    public_key: str = ""
    signature: str = ""
    memo: str = ""
    is_coinbase: bool = False
    lock_type: str = ""
    lock_data: Dict[str, Any] = field(default_factory=dict)

    def message_to_sign(self) -> bytes:
        payload = {
            "tx_id": self.tx_id, "sender": self.sender, "recipient": self.recipient,
            "amount": self.amount, "timestamp": self.timestamp, "memo": self.memo,
            "is_coinbase": self.is_coinbase, "lock_type": self.lock_type, "lock_data": self.lock_data,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Transaction":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def verify(self) -> bool:
        if self.is_coinbase:
            return True
        try:
            return pq_verify(bytes.fromhex(self.public_key), self.message_to_sign(), bytes.fromhex(self.signature))
        except Exception:
            return False


@dataclass
class Block:
    index: int
    timestamp: float
    transactions: List[Transaction]
    previous_hash: str
    nonce: int = 0
    miner: str = ""
    difficulty: int = INITIAL_DIFFICULTY
    hash: str = ""

    def calculate_hash(self) -> str:
        payload = {
            "index": self.index, "timestamp": self.timestamp,
            "transactions": [t.to_dict() for t in self.transactions],
            "previous_hash": self.previous_hash, "nonce": self.nonce,
            "miner": self.miner, "difficulty": self.difficulty,
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index, "timestamp": self.timestamp,
            "transactions": [t.to_dict() for t in self.transactions],
            "previous_hash": self.previous_hash, "nonce": self.nonce,
            "miner": self.miner, "difficulty": self.difficulty, "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        txs = [Transaction.from_dict(t) for t in d.get("transactions", [])]
        return cls(
            index=d["index"], timestamp=d["timestamp"], transactions=txs,
            previous_hash=d["previous_hash"], nonce=d.get("nonce", 0),
            miner=d.get("miner", ""), difficulty=d.get("difficulty", INITIAL_DIFFICULTY),
            hash=d.get("hash", ""),
        )


@dataclass
class Contract:
    contract_id: str
    type: str
    creator: str
    amount: float
    status: str = "open"
    participants: List[str] = field(default_factory=list)
    threshold: int = 1
    signatures: Dict[str, str] = field(default_factory=dict)
    release_to: str = ""
    unlock_height: int = 0
    unlock_time: float = 0.0
    beneficiary: str = ""
    created_height: int = 0
    created_at: float = 0.0
    memo: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Contract":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def sig_count(self) -> int:
        return len(self.signatures)

    def is_timelock_ready(self, height: int, now: float) -> bool:
        if self.type != "timelock" or self.status != "open":
            return False
        if self.unlock_height and height >= self.unlock_height:
            return True
        if self.unlock_time and now >= self.unlock_time:
            return True
        return False


@dataclass
class Peer:
    url: str
    node_id: str = ""
    last_seen: float = 0.0
    height: int = 0
    tip: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Peer":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def check_send_rules(sender: str, recipient: str, amount: float, memo: str) -> Optional[str]:
    if amount < MIN_SEND_AMOUNT:
        return f"amount below minimum ({MIN_SEND_AMOUNT} VEX)"
    if amount <= 0:
        return "amount must be positive"
    if not ALLOW_SELF_SEND and sender == recipient:
        return "self-send is not allowed"
    if len(memo) > MAX_MEMO_LEN:
        return f"memo too long (max {MAX_MEMO_LEN})"
    if not recipient.startswith("VEX"):
        return "recipient must be a VEX address"
    return None


# ---------------------------------------------------------------------------
# Blockchain
# ---------------------------------------------------------------------------
class Blockchain:
    def __init__(self):
        self.chain: List[Block] = []
        self.orphans: Dict[str, Block] = {}
        self.mempool: List[Transaction] = []
        self.balances: Dict[str, float] = {}
        self.contracts: Dict[str, Contract] = {}
        self.difficulty: int = INITIAL_DIFFICULTY
        self.lock = threading.RLock()
        DATA_DIR.mkdir(exist_ok=True)
        self.load()

    def save(self):
        with self.lock:
            data = {
                "version": VERSION,
                "difficulty": self.difficulty,
                "chain": [b.to_dict() for b in self.chain],
                "orphans": {h: b.to_dict() for h, b in self.orphans.items()},
                "mempool": [t.to_dict() for t in self.mempool],
                "contracts": {cid: c.to_dict() for cid, c in self.contracts.items()},
            }
            tmp = CHAIN_FILE.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            tmp.replace(CHAIN_FILE)

    def load(self):
        if not CHAIN_FILE.exists():
            self.create_genesis()
            return
        try:
            with open(CHAIN_FILE) as f:
                data = json.load(f)
            self.chain = [Block.from_dict(b) for b in data.get("chain", [])]
            self.orphans = {h: Block.from_dict(b) for h, b in data.get("orphans", {}).items()}
            self.mempool = [Transaction.from_dict(t) for t in data.get("mempool", [])]
            self.contracts = {cid: Contract.from_dict(c) for cid, c in data.get("contracts", {}).items()}
            self.difficulty = data.get("difficulty", INITIAL_DIFFICULTY)
            self.rebuild_balances()
            print(f"[+] Loaded chain height {len(self.chain)-1}  difficulty={self.difficulty}  contracts={len(self.contracts)}")
        except Exception as e:
            print(f"[!] Failed to load: {e}")
            self.create_genesis()

    def create_genesis(self):
        genesis = Block(0, time.time(), [], "0"*64, miner="genesis", difficulty=INITIAL_DIFFICULTY)
        genesis.hash = genesis.calculate_hash()
        self.chain = [genesis]
        self.difficulty = INITIAL_DIFFICULTY
        self.rebuild_balances()
        self.save()
        print("[+] Genesis block created")

    def rebuild_balances(self):
        self.balances = {}
        for block in self.chain:
            for tx in block.transactions:
                if not tx.is_coinbase:
                    self.balances[tx.sender] = self.balances.get(tx.sender, 0.0) - tx.amount
                self.balances[tx.recipient] = self.balances.get(tx.recipient, 0.0) + tx.amount
        for addr in list(self.balances):
            if abs(self.balances[addr]) < 1e-9:
                del self.balances[addr]

    def get_balance(self, address: str) -> float:
        return self.balances.get(address, 0.0)

    def height(self) -> int:
        return len(self.chain) - 1

    def tip_hash(self) -> str:
        return self.chain[-1].hash if self.chain else ""

    def add_transaction(self, tx: Transaction, broadcast: bool = True) -> bool:
        with self.lock:
            if not tx.verify():
                print("[-] Invalid signature")
                return False
            if not tx.is_coinbase:
                err = check_send_rules(tx.sender, tx.recipient, tx.amount, tx.memo)
                if err:
                    print(f"[-] Send rule: {err}")
                    return False
                if self.get_balance(tx.sender) < tx.amount:
                    print("[-] Insufficient balance")
                    return False
            if any(e.tx_id == tx.tx_id for e in self.mempool):
                return False
            # also skip if already in chain
            for b in self.chain:
                if any(t.tx_id == tx.tx_id for t in b.transactions):
                    return False
            self.mempool.append(tx)
            self.save()
        if broadcast and net:
            net.broadcast_tx(tx)
        return True

    def _maybe_adjust_difficulty(self):
        """Simple educational retarget every DIFFICULTY_ADJUST_INTERVAL blocks."""
        h = self.height()
        if h < DIFFICULTY_ADJUST_INTERVAL or h % DIFFICULTY_ADJUST_INTERVAL != 0:
            return
        start = self.chain[h - DIFFICULTY_ADJUST_INTERVAL]
        end = self.chain[h]
        elapsed = end.timestamp - start.timestamp
        expected = TARGET_BLOCK_TIME * DIFFICULTY_ADJUST_INTERVAL
        if elapsed <= 0:
            return
        ratio = expected / elapsed
        old = self.difficulty
        if ratio > 1.5:
            self.difficulty = min(self.difficulty + 1, 8)
        elif ratio < 0.6:
            self.difficulty = max(self.difficulty - 1, 2)
        if self.difficulty != old:
            print(f"[~] Difficulty adjusted {old} → {self.difficulty}  (ratio={ratio:.2f})")

    def mine_block(self, miner_address: str) -> Optional[Block]:
        with self.lock:
            if not self.chain:
                return None
            txs = self.mempool[:MAX_TX_PER_BLOCK]
            coinbase = Transaction(
                tx_id=str(uuid.uuid4()), sender="COINBASE", recipient=miner_address,
                amount=BLOCK_REWARD, timestamp=time.time(), is_coinbase=True,
            )
            all_txs = [coinbase] + txs
            prev = self.chain[-1]
            block = Block(
                prev.index + 1, time.time(), all_txs, prev.hash,
                miner=miner_address, difficulty=self.difficulty,
            )
            target = "0" * self.difficulty
            start_h = prev.index
            while True:
                block.hash = block.calculate_hash()
                if block.hash.startswith(target):
                    break
                block.nonce += 1
                if block.nonce % 100000 == 0 and len(self.chain) > start_h + 1:
                    print("[!] Someone else mined first – aborting")
                    return None
            self.chain.append(block)
            used = {t.tx_id for t in txs}
            self.mempool = [t for t in self.mempool if t.tx_id not in used]
            self.rebuild_balances()
            self._maybe_adjust_difficulty()
            self.save()
            print(f"[+] Block {block.index} mined by {miner_address[:12]}...  reward={BLOCK_REWARD}  diff={self.difficulty}")
        if net:
            net.broadcast_block(block)
        return block

    def add_block(self, block: Block, from_peer: bool = False) -> str:
        with self.lock:
            if any(b.hash == block.hash for b in self.chain) or block.hash in self.orphans:
                return "rejected"
            if not self._is_block_valid(block):
                return "rejected"
            tip = self.chain[-1]
            if block.previous_hash == tip.hash and block.index == tip.index + 1:
                self.chain.append(block)
                self._apply_block(block)
                self._try_connect_orphans()
                self._maybe_adjust_difficulty()
                self.save()
                if from_peer:
                    print(f"[+] Accepted peer block #{block.index}")
                return "accepted"
            if block.index > tip.index + 1 or block.previous_hash != tip.hash:
                if len(self.orphans) >= ORPHAN_MAX:
                    del self.orphans[next(iter(self.orphans))]
                self.orphans[block.hash] = block
                print(f"[~] Orphan saved (height {block.index})")
                if self._try_reorg(block):
                    return "reorg"
                return "orphan"
            return "rejected"

    def _is_block_valid(self, block: Block) -> bool:
        if block.hash != block.calculate_hash():
            return False
        diff = getattr(block, "difficulty", self.difficulty)
        if not block.hash.startswith("0" * diff):
            return False
        if not block.transactions or not block.transactions[0].is_coinbase:
            return False
        if block.transactions[0].amount != BLOCK_REWARD:
            return False
        for tx in block.transactions[1:]:
            if not tx.verify():
                return False
        return True

    def _apply_block(self, block: Block):
        for tx in block.transactions:
            if not tx.is_coinbase:
                self.balances[tx.sender] = self.balances.get(tx.sender, 0.0) - tx.amount
            self.balances[tx.recipient] = self.balances.get(tx.recipient, 0.0) + tx.amount
        used = {t.tx_id for t in block.transactions}
        self.mempool = [t for t in self.mempool if t.tx_id not in used]

    def _try_connect_orphans(self):
        changed = True
        while changed:
            changed = False
            tip = self.chain[-1]
            for h, orphan in list(self.orphans.items()):
                if orphan.previous_hash == tip.hash and orphan.index == tip.index + 1:
                    if self._is_block_valid(orphan):
                        self.chain.append(orphan)
                        self._apply_block(orphan)
                        del self.orphans[h]
                        changed = True
                        print(f"[+] Connected orphan → height {orphan.index}")
                        break

    def _try_reorg(self, new_block: Block) -> bool:
        candidate = [new_block]
        current = new_block
        seen = {new_block.hash}
        while True:
            parent = None
            for o in self.orphans.values():
                if o.hash == current.previous_hash:
                    parent = o
                    break
            if parent is None:
                for b in self.chain:
                    if b.hash == current.previous_hash:
                        parent = b
                        break
            if parent is None or parent.hash in seen:
                break
            candidate.insert(0, parent)
            seen.add(parent.hash)
            current = parent
            if parent.index == 0:
                break
        if not candidate:
            return False
        common_idx = -1
        for i, b in enumerate(self.chain):
            if b.hash in (candidate[0].previous_hash, candidate[0].hash):
                common_idx = i
                break
        if common_idx == -1 and candidate[0].index != 0:
            return False
        new_chain = (self.chain[:common_idx + 1] + candidate) if common_idx >= 0 else candidate
        if len(new_chain) <= len(self.chain):
            return False
        print(f"[!] REORG! {len(self.chain)-1} → {len(new_chain)-1}")
        self.chain = new_chain
        for b in candidate:
            self.orphans.pop(b.hash, None)
        self.rebuild_balances()
        self.save()
        return True

    # ---- contracts ----
    def create_multisig(self, creator, participants, threshold, amount, release_to="", memo="") -> Optional[Contract]:
        with self.lock:
            if creator not in participants:
                participants = [creator] + list(participants)
            participants = list(dict.fromkeys(participants))
            if threshold < 1 or threshold > len(participants):
                print("[-] Invalid threshold (need 1 ≤ M ≤ N)")
                return None
            if self.get_balance(creator) < amount or amount < MIN_SEND_AMOUNT:
                print("[-] Insufficient balance or amount too small")
                return None
            cid = "MS-" + uuid.uuid4().hex[:12]
            self.balances[creator] = self.balances.get(creator, 0.0) - amount
            c = Contract(
                contract_id=cid, type="multisig", creator=creator, amount=amount,
                participants=participants, threshold=threshold,
                release_to=release_to or creator, created_height=self.height(),
                created_at=time.time(), memo=memo,
            )
            self.contracts[cid] = c
            self.save()
            print(f"[+] Multi-sig {cid}  {threshold}-of-{len(participants)}  locked {amount} VEX")
            return c

    def sign_multisig(self, contract_id: str, signer: str, signature_hex: str) -> bool:
        with self.lock:
            c = self.contracts.get(contract_id)
            if not c or c.type != "multisig" or c.status != "open":
                print("[-] Not an open multisig")
                return False
            if signer not in c.participants:
                print("[-] Not a participant")
                return False
            c.signatures[signer] = signature_hex
            self.save()
            print(f"[+] Sig recorded ({c.sig_count()}/{c.threshold})")
            if c.sig_count() >= c.threshold:
                dest = c.release_to or c.creator
                self.balances[dest] = self.balances.get(dest, 0.0) + c.amount
                c.status = "released"
                self.save()
                print(f"[+] RELEASED → {dest[:16]}...  {c.amount} VEX")
            return True

    def create_timelock(self, creator, beneficiary, amount, unlock_height=0, unlock_seconds=0.0, memo="") -> Optional[Contract]:
        with self.lock:
            if self.get_balance(creator) < amount or amount < MIN_SEND_AMOUNT:
                print("[-] Insufficient balance or amount too small")
                return None
            if unlock_height <= 0 and unlock_seconds <= 0:
                print("[-] Need unlock_height or unlock_seconds")
                return None
            if unlock_height > 0 and unlock_height <= self.height():
                print("[-] unlock_height must be in the future")
                return None
            cid = "TL-" + uuid.uuid4().hex[:12]
            self.balances[creator] = self.balances.get(creator, 0.0) - amount
            unlock_time = time.time() + unlock_seconds if unlock_seconds > 0 else 0.0
            c = Contract(
                contract_id=cid, type="timelock", creator=creator, amount=amount,
                beneficiary=beneficiary or creator, unlock_height=unlock_height,
                unlock_time=unlock_time, created_height=self.height(),
                created_at=time.time(), memo=memo,
            )
            self.contracts[cid] = c
            self.save()
            bits = []
            if unlock_height:
                bits.append(f"h≥{unlock_height}")
            if unlock_time:
                bits.append(f"t≥{time.strftime('%H:%M:%S', time.localtime(unlock_time))}")
            print(f"[+] Time-lock {cid}  {amount} VEX  ({', '.join(bits)})")
            return c

    def claim_timelock(self, contract_id: str, claimer: str) -> bool:
        with self.lock:
            c = self.contracts.get(contract_id)
            if not c or c.type != "timelock" or c.status != "open":
                print("[-] Not an open timelock")
                return False
            if claimer not in (c.beneficiary, c.creator):
                print("[-] Only beneficiary/creator can claim")
                return False
            if not c.is_timelock_ready(self.height(), time.time()):
                print("[-] Not ready yet")
                if c.unlock_height:
                    print(f"    need height ≥ {c.unlock_height} (now {self.height()})")
                if c.unlock_time:
                    print(f"    need wait ~{max(0, int(c.unlock_time - time.time()))}s")
                return False
            self.balances[c.beneficiary] = self.balances.get(c.beneficiary, 0.0) + c.amount
            c.status = "claimed"
            self.save()
            print(f"[+] CLAIMED → {c.beneficiary[:16]}...  {c.amount} VEX")
            return True

    def list_contracts(self, address: Optional[str] = None) -> List[Contract]:
        out = []
        for c in self.contracts.values():
            if address is None or c.creator == address or c.beneficiary == address or address in c.participants or c.release_to == address:
                out.append(c)
        return out


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------
class Wallet:
    def __init__(self):
        self.seed_phrase: List[str] = []
        self.addresses: List[str] = []
        self.keys: Dict[str, Tuple[bytes, bytes]] = {}
        self.unlocked = False
        self.password: Optional[str] = None

    def generate_seed(self) -> List[str]:
        words = [
            "apple", "banana", "cherry", "delta", "echo", "foxtrot",
            "golf", "hotel", "india", "juliet", "kilo", "lima",
            "mango", "november", "oscar", "papa", "quebec", "romeo",
            "sierra", "tango", "uniform", "victor", "whiskey", "xray",
            "yankee", "zulu", "alpha", "bravo", "crypto", "quantum",
            "secure", "wallet", "chain", "block", "miner", "reward",
        ]
        import random
        self.seed_phrase = [random.choice(words) for _ in range(12)]
        return self.seed_phrase

    def derive_key(self, index: int = 0) -> Tuple[bytes, bytes]:
        seed = " ".join(self.seed_phrase).encode()
        _ = hashlib.sha256(seed + str(index).encode()).digest()
        return pq_keygen()

    def create_address(self) -> str:
        pk, sk = self.derive_key(len(self.addresses))
        addr = address_from_pubkey(pk)
        self.addresses.append(addr)
        self.keys[addr] = (pk, sk)
        return addr

    def get_primary(self) -> Optional[str]:
        return self.addresses[0] if self.addresses else None

    def sign_tx(self, tx: Transaction, address: str) -> bool:
        if address not in self.keys:
            return False
        pk, sk = self.keys[address]
        tx.public_key = pk.hex()
        tx.signature = pq_sign(sk, tx.message_to_sign()).hex()
        return True

    def sign_message(self, address: str, message: bytes) -> Optional[str]:
        if address not in self.keys:
            return None
        return pq_sign(self.keys[address][1], message).hex()

    def lock(self):
        self.keys.clear()
        self.unlocked = False
        self.password = None
        print("[+] Wallet locked")

    def save_encrypted(self, password: str):
        if not HAS_CRYPTO:
            print("[-] cryptography not available")
            return
        data = {"seed": self.seed_phrase, "addresses": self.addresses}
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000, backend=default_backend())
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        token = Fernet(key).encrypt(json.dumps(data).encode())
        with open(WALLET_FILE, "wb") as fp:
            fp.write(salt + token)
        print(f"[+] Wallet saved → {WALLET_FILE}")

    def load_encrypted(self, password: str) -> bool:
        if not HAS_CRYPTO or not WALLET_FILE.exists():
            return False
        try:
            raw = open(WALLET_FILE, "rb").read()
            salt, token = raw[:16], raw[16:]
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000, backend=default_backend())
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            data = json.loads(Fernet(key).decrypt(token).decode())
            self.seed_phrase = data["seed"]
            self.addresses = data["addresses"]
            for i, addr in enumerate(self.addresses):
                self.keys[addr] = self.derive_key(i)
            self.unlocked = True
            self.password = password
            print("[+] Wallet unlocked")
            return True
        except Exception as e:
            print(f"[-] Unlock failed: {e}")
            return False


# ---------------------------------------------------------------------------
# Node identity + Peer networking
# ---------------------------------------------------------------------------
class PeerManager:
    def __init__(self, bc: Blockchain):
        self.bc = bc
        self.peers: Dict[str, Peer] = {}          # url → Peer
        self.node_pk: bytes = b""
        self.node_sk: bytes = b""
        self.node_id: str = ""
        self.self_url: str = f"http://127.0.0.1:{HTTP_PORT}"
        self.lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=6)
        self._stop = threading.Event()
        self._load_or_create_identity()
        self._load_peers()

    def _load_or_create_identity(self):
        id_file = DATA_DIR / "node_id.json"
        if id_file.exists():
            try:
                data = json.loads(id_file.read_text())
                self.node_pk = bytes.fromhex(data["pk"])
                self.node_sk = bytes.fromhex(data["sk"])
                self.node_id = data["node_id"]
                print(f"[+] Node identity: {self.node_id}")
                return
            except Exception:
                pass
        self.node_pk, self.node_sk = pq_keygen()
        self.node_id = node_id_from_pubkey(self.node_pk)
        DATA_DIR.mkdir(exist_ok=True)
        id_file.write_text(json.dumps({
            "node_id": self.node_id,
            "pk": self.node_pk.hex(),
            "sk": self.node_sk.hex(),
        }, indent=2))
        print(f"[+] New node identity: {self.node_id}")

    def _load_peers(self):
        if PEERS_FILE.exists():
            try:
                data = json.loads(PEERS_FILE.read_text())
                for p in data.get("peers", []):
                    peer = Peer.from_dict(p)
                    self.peers[peer.url] = peer
                print(f"[+] Loaded {len(self.peers)} peers")
            except Exception as e:
                print(f"[!] peers load failed: {e}")

    def save_peers(self):
        with self.lock:
            data = {"peers": [p.to_dict() for p in self.peers.values()]}
            PEERS_FILE.write_text(json.dumps(data, indent=2))

    def add_peer(self, url: str) -> bool:
        url = url.rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        if url == self.self_url or url in self.peers:
            return False
        with self.lock:
            if len(self.peers) >= MAX_PEERS:
                # drop oldest
                oldest = min(self.peers.values(), key=lambda p: p.last_seen)
                del self.peers[oldest.url]
            self.peers[url] = Peer(url=url, last_seen=time.time())
            self.save_peers()
        print(f"[+] Peer added: {url}")
        # try announce + sync in background
        self._executor.submit(self._handshake, url)
        return True

    def remove_peer(self, url: str):
        with self.lock:
            self.peers.pop(url.rstrip("/"), None)
            self.save_peers()

    def list_peers(self) -> List[Peer]:
        with self.lock:
            return list(self.peers.values())

    def _http_get(self, url: str, path: str, timeout: float = PEER_TIMEOUT) -> Optional[dict]:
        if not HAS_REQUESTS:
            return None
        try:
            r = requests.get(f"{url.rstrip('/')}{path}", timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def _http_post(self, url: str, path: str, payload: dict, timeout: float = PEER_TIMEOUT) -> Optional[dict]:
        if not HAS_REQUESTS:
            return None
        try:
            r = requests.post(f"{url.rstrip('/')}{path}", json=payload, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def _handshake(self, url: str):
        """Announce ourselves and learn peer status."""
        data = self._http_get(url, "/status")
        if not data:
            return
        with self.lock:
            if url in self.peers:
                self.peers[url].node_id = data.get("node_id", "")
                self.peers[url].height = data.get("height", 0)
                self.peers[url].tip = data.get("tip", "")
                self.peers[url].last_seen = time.time()
                self.save_peers()
        # announce back
        self._http_post(url, "/announce", {
            "url": self.self_url,
            "node_id": self.node_id,
            "height": self.bc.height(),
            "tip": self.bc.tip_hash(),
        })
        # if they are ahead, request missing blocks
        their_h = data.get("height", 0)
        if their_h > self.bc.height():
            self._sync_from(url, their_h)

    def _sync_from(self, url: str, their_height: int):
        """Pull blocks from peer starting after our tip."""
        our_h = self.bc.height()
        print(f"[~] Syncing from {url}  (us={our_h} them={their_height})")
        for i in range(our_h + 1, their_height + 1):
            data = self._http_get(url, f"/block/{i}")
            if not data or "block" not in data:
                break
            block = Block.from_dict(data["block"])
            result = self.bc.add_block(block, from_peer=True)
            if result not in ("accepted", "reorg", "orphan"):
                print(f"[-] Sync stopped at block {i}: {result}")
                break
        print(f"[+] Sync complete → height {self.bc.height()}")

    def broadcast_block(self, block: Block):
        payload = {"block": block.to_dict(), "from": self.node_id}
        for url in list(self.peers.keys()):
            self._executor.submit(self._http_post, url, "/block", payload)

    def broadcast_tx(self, tx: Transaction):
        payload = {"tx": tx.to_dict(), "from": self.node_id}
        for url in list(self.peers.keys()):
            self._executor.submit(self._http_post, url, "/tx", payload)

    def gossip_once(self):
        """Background: refresh peer status + exchange peer lists."""
        for url in list(self.peers.keys()):
            data = self._http_get(url, "/status")
            if data:
                with self.lock:
                    if url in self.peers:
                        self.peers[url].node_id = data.get("node_id", self.peers[url].node_id)
                        self.peers[url].height = data.get("height", 0)
                        self.peers[url].tip = data.get("tip", "")
                        self.peers[url].last_seen = time.time()
                # if ahead, sync
                if data.get("height", 0) > self.bc.height():
                    self._sync_from(url, data["height"])
            else:
                # mark stale but keep for a while
                pass
            # exchange peer lists
            peer_list = self._http_get(url, "/peers")
            if peer_list and "peers" in peer_list:
                for p in peer_list["peers"]:
                    p_url = p.get("url", "")
                    if p_url and p_url != self.self_url and p_url not in self.peers:
                        self.add_peer(p_url)
        self.save_peers()

    def force_sync(self):
        print("[~] Force sync from all peers...")
        for url in list(self.peers.keys()):
            data = self._http_get(url, "/status")
            if data and data.get("height", 0) > self.bc.height():
                self._sync_from(url, data["height"])
        print(f"[+] Now at height {self.bc.height()}")

    def start_background(self):
        def loop():
            while not self._stop.wait(GOSSIP_INTERVAL):
                try:
                    self.gossip_once()
                except Exception as e:
                    print(f"[!] Gossip error: {e}")
        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def stop(self):
        self._stop.set()
        self._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Global instances
# ---------------------------------------------------------------------------
bc = Blockchain()
wallet = Wallet()
net: Optional[PeerManager] = None


# ---------------------------------------------------------------------------
# Public HTTP + VexloreBot-themed explorer (now with peers)
# ---------------------------------------------------------------------------
def _explorer_html() -> str:
    blocks_rows = []
    for b in reversed(bc.chain[-20:]):
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(b.timestamp)) if b.timestamp else "?"
        miner = (b.miner or "")[:14]
        diff = getattr(b, "difficulty", bc.difficulty)
        blocks_rows.append(
            "<tr><td>%d</td><td class='mono'>%s…</td><td>%d</td>"
            "<td class='mono'>%s</td><td>%d</td><td>%s</td></tr>"
            % (b.index, b.hash[:14], len(b.transactions), miner, diff, ts)
        )
    bals = sorted(bc.balances.items(), key=lambda x: -x[1])[:12]
    bals_rows = "".join(
        "<tr><td class='mono'>%s</td><td class='num'>%.4f</td></tr>" % (a, v)
        for a, v in bals
    ) or "<tr><td colspan=2>no balances yet</td></tr>"
    c_rows = "".join(
        "<tr><td class='mono'>%s</td><td>%s</td><td>%s</td><td class='num'>%.2f</td></tr>"
        % (c.contract_id, c.type, c.status, c.amount)
        for c in list(bc.contracts.values())[-10:]
    ) or "<tr><td colspan=4>no contracts yet</td></tr>"

    peer_rows = ""
    if net:
        for p in net.list_peers():
            age = int(time.time() - p.last_seen) if p.last_seen else 9999
            peer_rows += (
                "<tr><td class='mono'>%s</td><td class='mono'>%s</td>"
                "<td>%d</td><td>%ds ago</td></tr>"
                % (p.node_id or "?", p.url[:40], p.height, age)
            )
    if not peer_rows:
        peer_rows = "<tr><td colspan=4>no peers yet — use menu 21</td></tr>"

    node_id = net.node_id if net else "?"
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vexlore Explorer</title>
<style>
:root {{
  --bg:#070b12; --card:#0f1620; --border:#1c2a3a; --text:#e8eef6;
  --muted:#8b9cb3; --blue:#4da3ff; --purple:#9b7bff; --green:#3ecf8e; --glow:#4da3ff55;
}}
* {{ box-sizing:border-box }}
body {{
  margin:0; font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;
  background: radial-gradient(1200px 600px at 10% -10%, #1a1040 0%, transparent 50%),
              radial-gradient(900px 500px at 100% 0%, #0a2040 0%, transparent 45%),
              var(--bg);
  color:var(--text); min-height:100vh;
}}
header {{
  display:flex; align-items:center; gap:1rem; flex-wrap:wrap;
  padding:1rem 1.4rem; border-bottom:1px solid var(--border);
  background:rgba(15,22,32,.75); backdrop-filter:blur(10px);
}}
.logo {{
  width:48px; height:48px; border-radius:14px;
  background:linear-gradient(135deg, var(--blue), var(--purple));
  display:flex; align-items:center; justify-content:center;
  font-weight:900; font-size:1.35rem; color:#070b12;
  box-shadow:0 0 24px var(--glow);
}}
h1 {{ margin:0; font-size:1.25rem; letter-spacing:.02em }}
h1 span {{ background:linear-gradient(90deg,var(--blue),var(--purple)); -webkit-background-clip:text; color:transparent }}
.badges {{ display:flex; gap:.4rem; flex-wrap:wrap; margin-top:.35rem }}
.badge {{
  font-size:.7rem; padding:.2rem .55rem; border-radius:999px;
  border:1px solid var(--border); background:var(--card); color:var(--muted);
}}
.badge a {{ color:var(--blue); text-decoration:none }}
.badge.bot {{ border-color:#4da3ff66; color:var(--blue) }}
main {{ max-width:1100px; margin:0 auto; padding:1.25rem }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:.75rem; margin-bottom:1.2rem }}
.stat {{
  background:var(--card); border:1px solid var(--border); border-radius:12px; padding:.9rem;
}}
.stat .lbl {{ color:var(--muted); font-size:.7rem; text-transform:uppercase; letter-spacing:.06em }}
.stat .val {{ font-size:1.25rem; font-weight:700; color:var(--blue); margin-top:.25rem }}
section {{
  background:var(--card); border:1px solid var(--border); border-radius:12px;
  padding:1rem 1.1rem; margin-bottom:1rem;
}}
section h2 {{ margin:0 0 .75rem; font-size:.9rem; color:var(--muted); font-weight:600 }}
table {{ width:100%; border-collapse:collapse; font-size:.84rem }}
th,td {{ text-align:left; padding:.45rem .35rem; border-bottom:1px solid var(--border) }}
th {{ color:var(--muted); font-size:.68rem; text-transform:uppercase; letter-spacing:.04em }}
.mono {{ font-family:ui-monospace,Consolas,monospace; font-size:.78rem }}
.num {{ color:var(--green); font-variant-numeric:tabular-nums }}
footer {{
  text-align:center; color:var(--muted); font-size:.75rem; padding:1.5rem 1rem 2rem;
}}
footer a {{ color:var(--blue); text-decoration:none }}
</style></head><body>
<header>
  <div class="logo">V</div>
  <div>
    <h1>Vexlore <span>Explorer</span></h1>
    <div class="badges">
      <span class="badge">v{VERSION}</span>
      <span class="badge">PQ · peers · contracts</span>
      <span class="badge">node {node_id}</span>
      <span class="badge bot"><a href="{VEXLOREBOT_URL}" target="_blank" rel="noopener">VexloreBot ↗</a></span>
    </div>
  </div>
</header>
<main>
  <div class="grid">
    <div class="stat"><div class="lbl">Height</div><div class="val">{bc.height()}</div></div>
    <div class="stat"><div class="lbl">Blocks</div><div class="val">{len(bc.chain)}</div></div>
    <div class="stat"><div class="lbl">Mempool</div><div class="val">{len(bc.mempool)}</div></div>
    <div class="stat"><div class="lbl">Accounts</div><div class="val">{len(bc.balances)}</div></div>
    <div class="stat"><div class="lbl">Contracts</div><div class="val">{len(bc.contracts)}</div></div>
    <div class="stat"><div class="lbl">Difficulty</div><div class="val">{bc.difficulty}</div></div>
    <div class="stat"><div class="lbl">Peers</div><div class="val">{len(net.peers) if net else 0}</div></div>
  </div>
  <section>
    <h2>Recent blocks</h2>
    <table>
      <thead><tr><th>#</th><th>Hash</th><th>Txs</th><th>Miner</th><th>Diff</th><th>Time</th></tr></thead>
      <tbody>{''.join(blocks_rows) or '<tr><td colspan=6>empty chain</td></tr>'}</tbody>
    </table>
  </section>
  <section>
    <h2>Connected peers</h2>
    <table>
      <thead><tr><th>Node ID</th><th>URL</th><th>Height</th><th>Last seen</th></tr></thead>
      <tbody>{peer_rows}</tbody>
    </table>
  </section>
  <section>
    <h2>Top balances</h2>
    <table>
      <thead><tr><th>Address</th><th>VEX</th></tr></thead>
      <tbody>{bals_rows}</tbody>
    </table>
  </section>
  <section>
    <h2>Contracts</h2>
    <table>
      <thead><tr><th>ID</th><th>Type</th><th>Status</th><th>Amount</th></tr></thead>
      <tbody>{c_rows}</tbody>
    </table>
  </section>
</main>
<footer>
  Educational testnet only ·
  <a href="/">API</a> ·
  <a href="/status">Status</a> ·
  <a href="{VEXLOREBOT_URL}" target="_blank" rel="noopener">VexloreBot</a>
</footer>
</body></html>"""


class ExplorerHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [HTTP] {self.address_string()} {fmt % args}")

    def _json(self, code: int, obj):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, html: str):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Optional[dict]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in ("/explorer", "/ui"):
            self._html(200, _explorer_html())
        elif path == "/":
            self._json(200, {
                "name": "Vexlore Quantumproof Chain",
                "version": VERSION,
                "node_id": net.node_id if net else None,
                "height": bc.height(),
                "blocks": len(bc.chain),
                "mempool": len(bc.mempool),
                "contracts": len(bc.contracts),
                "difficulty": bc.difficulty,
                "peers": len(net.peers) if net else 0,
                "explorer": "/explorer",
                "vexlorebot": VEXLOREBOT_URL,
            })
        elif path == "/status":
            self._json(200, {
                "version": VERSION,
                "node_id": net.node_id if net else None,
                "height": bc.height(),
                "tip": bc.tip_hash(),
                "mempool": len(bc.mempool),
                "orphans": len(bc.orphans),
                "contracts": len(bc.contracts),
                "accounts": len(bc.balances),
                "difficulty": bc.difficulty,
                "peers": len(net.peers) if net else 0,
            })
        elif path == "/chain":
            self._json(200, {
                "length": len(bc.chain),
                "chain": [b.to_dict() for b in bc.chain],
            })
        elif path.startswith("/block/"):
            try:
                idx = int(path.split("/")[-1])
                if 0 <= idx < len(bc.chain):
                    self._json(200, {"block": bc.chain[idx].to_dict()})
                else:
                    self._json(404, {"error": "block not found"})
            except ValueError:
                self._json(400, {"error": "bad index"})
        elif path in ("/mempool", "/pending"):
            self._json(200, {
                "count": len(bc.mempool),
                "pending": [t.to_dict() for t in bc.mempool],
            })
        elif path == "/contracts":
            self._json(200, {
                "count": len(bc.contracts),
                "contracts": [c.to_dict() for c in bc.contracts.values()],
            })
        elif path == "/peers":
            peers = []
            if net:
                peers = [p.to_dict() for p in net.list_peers()]
                # also advertise ourselves
                peers.append({
                    "url": net.self_url,
                    "node_id": net.node_id,
                    "height": bc.height(),
                    "tip": bc.tip_hash(),
                    "last_seen": time.time(),
                })
            self._json(200, {"count": len(peers), "peers": peers})
        else:
            self._json(404, {"error": "not found", "try": ["/explorer", "/status", "/chain", "/peers", "/block/N"]})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        body = self._read_json() or {}

        if path == "/announce":
            url = body.get("url", "").rstrip("/")
            if url and net:
                net.add_peer(url)
                # update their info
                with net.lock:
                    if url in net.peers:
                        net.peers[url].node_id = body.get("node_id", "")
                        net.peers[url].height = body.get("height", 0)
                        net.peers[url].tip = body.get("tip", "")
                        net.peers[url].last_seen = time.time()
                        net.save_peers()
            self._json(200, {"ok": True, "node_id": net.node_id if net else None})

        elif path == "/block":
            blk_data = body.get("block")
            if not blk_data:
                self._json(400, {"error": "missing block"})
                return
            try:
                block = Block.from_dict(blk_data)
                result = bc.add_block(block, from_peer=True)
                self._json(200, {"result": result})
            except Exception as e:
                self._json(400, {"error": str(e)})

        elif path == "/tx":
            tx_data = body.get("tx")
            if not tx_data:
                self._json(400, {"error": "missing tx"})
                return
            try:
                tx = Transaction.from_dict(tx_data)
                ok = bc.add_transaction(tx, broadcast=False)  # already coming from peer
                self._json(200, {"accepted": ok})
            except Exception as e:
                self._json(400, {"error": str(e)})

        else:
            self._json(404, {"error": "not found"})


def start_http_server():
    try:
        server = HTTPServer((HTTP_HOST, HTTP_PORT), ExplorerHandler)
    except OSError as e:
        print(f"[!] HTTP port {HTTP_PORT} busy: {e}")
        print("    Close other Vexlore or change HTTP_PORT in the script")
        return None
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[+] Public server  http://127.0.0.1:{HTTP_PORT}")
    print(f"    Explorer       http://127.0.0.1:{HTTP_PORT}/explorer")
    print(f"    VexloreBot     {VEXLOREBOT_URL}")
    print(f"    (tunnel this port for public testnet)")
    return server


def print_menu():
    print("\n" + "=" * 56)
    print(f"  Vexlore v{VERSION}  —  NETWORK + PEERS")
    print("=" * 56)
    print(" 1. Create / Restore wallet     2. Unlock wallet")
    print(" 3. Show balances               4. Faucet")
    print(" 5. Send coins [rules]          6. Mine block")
    print(" 7. Chain tip / height          8. Show orphans")
    print(" 9. List addresses             10. New address")
    print("11. Tx history                 12. Lock wallet")
    print("13. Multi-miner demo")
    print("-" * 56)
    print("14. Create multi-sig vault     15. Sign multi-sig")
    print("16. Create time-lock           17. Claim time-lock")
    print("18. List contracts             19. Show send rules")
    print("20. Open explorer URL")
    print("-" * 56)
    print("21. Connect to peer            22. List peers")
    print("23. Broadcast mempool          24. Force sync")
    print(" 0. Exit")
    print("=" * 56)


def main():
    global net
    print(f"\n🚀 Vexlore Quantumproof Chain v{VERSION}")
    print("   Peers • Gossip • Difficulty adjust • Contracts • Explorer\n")

    # optional CLI peer bootstrap
    bootstrap = None
    for i, arg in enumerate(sys.argv):
        if arg == "--peer" and i + 1 < len(sys.argv):
            bootstrap = sys.argv[i + 1]
        if arg == "--port" and i + 1 < len(sys.argv):
            global HTTP_PORT
            HTTP_PORT = int(sys.argv[i + 1])

    net = PeerManager(bc)
    net.self_url = f"http://127.0.0.1:{HTTP_PORT}"
    start_http_server()
    net.start_background()

    if bootstrap:
        print(f"[+] Bootstrapping peer: {bootstrap}")
        net.add_peer(bootstrap)

    while True:
        print_menu()
        choice = input("Choose → ").strip()

        if choice == "1":
            mode = input("New (n) or Restore (r)? ").strip().lower()
            if mode == "r":
                phrase = input("12 words:\n→ ").strip().split()
                if len(phrase) != 12:
                    print("[-] Need 12 words"); continue
                wallet.seed_phrase = phrase
            else:
                wallet.generate_seed()
                print("\n*** WRITE THESE DOWN ***")
                print(" ".join(wallet.seed_phrase))
                print("************************\n")
            pwd = input("Encrypt password: ").strip()
            if not pwd:
                print("[-] Password required"); continue
            wallet.create_address()
            wallet.save_encrypted(pwd)
            wallet.unlocked = True
            wallet.password = pwd
            print(f"[+] Primary: {wallet.get_primary()}")

        elif choice == "2":
            wallet.load_encrypted(input("Password: ").strip())

        elif choice == "3":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            for addr in wallet.addresses:
                print(f"  {addr}  →  {bc.get_balance(addr):.4f} VEX")
            locked = sum(c.amount for c in bc.list_contracts() if c.status == "open" and (
                c.creator in wallet.addresses or any(a in c.participants for a in wallet.addresses)))
            if locked:
                print(f"  (≈{locked:.4f} VEX in open contracts)")

        elif choice == "4":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            addr = wallet.get_primary()
            bc.balances[addr] = bc.balances.get(addr, 0.0) + 100.0
            bc.save()
            print(f"[+] Faucet +100 VEX → {addr}")

        elif choice == "5":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            sender = wallet.get_primary()
            recipient = input("Recipient: ").strip()
            try:
                amount = float(input("Amount: ").strip())
            except ValueError:
                print("[-] Bad amount"); continue
            memo = input("Memo: ").strip()
            err = check_send_rules(sender, recipient, amount, memo)
            if err:
                print(f"[-] {err}"); continue
            tx = Transaction(str(uuid.uuid4()), sender, recipient, amount, time.time(), memo=memo)
            if wallet.sign_tx(tx, sender) and bc.add_transaction(tx):
                print("[+] In mempool — mine (6) to confirm (also gossiped)")
            else:
                print("[-] Failed")

        elif choice == "6":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            print("Mining...")
            if bc.mine_block(wallet.get_primary()):
                print(f"[+] +{BLOCK_REWARD} VEX reward")

        elif choice == "7":
            print(f"\nHeight: {bc.height()}  Tip: {bc.tip_hash()[:20]}...")
            print(f"Mempool: {len(bc.mempool)}  Orphans: {len(bc.orphans)}  Contracts: {len(bc.contracts)}")
            print(f"Diff: {bc.difficulty}  Reward: {BLOCK_REWARD}  Node: {net.node_id if net else '?'}")
            print(f"Peers: {len(net.peers) if net else 0}")

        elif choice == "8":
            if not bc.orphans:
                print("No orphans")
            else:
                for h, b in bc.orphans.items():
                    print(f"  h={b.index}  {h[:16]}...  miner={b.miner[:12]}")

        elif choice == "9":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            for i, a in enumerate(wallet.addresses):
                print(f"  [{i}] {a}")

        elif choice == "10":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            addr = wallet.create_address()
            if wallet.password:
                wallet.save_encrypted(wallet.password)
            print(f"[+] {addr}")

        elif choice == "11":
            for block in bc.chain[-10:]:
                for tx in block.transactions:
                    kind = "COINBASE" if tx.is_coinbase else (tx.lock_type or "TRANSFER")
                    print(f"  [{block.index}] {kind:12} {tx.sender[:10]}…→{tx.recipient[:10]}… {tx.amount}")

        elif choice == "12":
            wallet.lock()

        elif choice == "13":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            print("=== Multi-miner race ===")
            results = []
            def worker(name, addr):
                results.append((name, bc.mine_block(addr)))
            extra = [wallet.create_address() for _ in range(2)]
            miners = [("You", wallet.get_primary()), ("B", extra[0]), ("C", extra[1])]
            threads = [threading.Thread(target=worker, args=m) for m in miners]
            for t in threads: t.start()
            for t in threads: t.join()
            for name, block in results:
                print(f"  {name}: {'WON #'+str(block.index) if block else 'lost'}")

        elif choice == "14":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            print("--- Multi-sig vault ---")
            raw = input("Other participants (comma addresses, or empty): ").strip()
            others = [a.strip() for a in raw.split(",") if a.strip()]
            try:
                threshold = int(input("Threshold M: ").strip())
                amount = float(input("Amount to lock: ").strip())
            except ValueError:
                print("[-] Bad number"); continue
            release_to = input(f"Release to [{wallet.get_primary()}]: ").strip() or wallet.get_primary()
            memo = input("Memo: ").strip()
            bc.create_multisig(wallet.get_primary(), others, threshold, amount, release_to, memo)

        elif choice == "15":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            cid = input("Contract id (MS-...): ").strip()
            c = bc.contracts.get(cid)
            if not c or c.type != "multisig":
                print("[-] Not multisig"); continue
            print(f"  {c.threshold}-of-{len(c.participants)} locked={c.amount} sigs={c.sig_count()}/{c.threshold}")
            msg = f"RELEASE:{cid}:{c.amount}:{c.release_to}".encode()
            sig = wallet.sign_message(wallet.get_primary(), msg)
            if sig:
                bc.sign_multisig(cid, wallet.get_primary(), sig)

        elif choice == "16":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            print("--- Time-lock ---")
            beneficiary = input(f"Beneficiary [{wallet.get_primary()}]: ").strip() or wallet.get_primary()
            try:
                amount = float(input("Amount: ").strip())
            except ValueError:
                print("[-] Bad amount"); continue
            mode = input("Unlock by (h)eight or (s)econds? [s]: ").strip().lower() or "s"
            uh, us = 0, 0.0
            if mode.startswith("h"):
                try:
                    uh = int(input(f"Height (now {bc.height()}): ").strip())
                except ValueError:
                    print("[-] Bad"); continue
            else:
                try:
                    us = float(input("Seconds: ").strip())
                except ValueError:
                    print("[-] Bad"); continue
            memo = input("Memo: ").strip()
            bc.create_timelock(wallet.get_primary(), beneficiary, amount, uh, us, memo)

        elif choice == "17":
            if not wallet.unlocked:
                print("[-] Unlock first"); continue
            bc.claim_timelock(input("Contract id (TL-...): ").strip(), wallet.get_primary())

        elif choice == "18":
            contracts = bc.list_contracts()
            if not contracts:
                print("No contracts")
            else:
                print(f"\n{'ID':16} {'TYPE':8} {'STATUS':10} {'AMT':>8}  INFO")
                for c in contracts:
                    if c.type == "multisig":
                        info = f"{c.threshold}-of-{len(c.participants)} sigs={c.sig_count()}"
                    else:
                        parts = []
                        if c.unlock_height:
                            parts.append(f"h≥{c.unlock_height}")
                        if c.unlock_time:
                            left = int(c.unlock_time - time.time())
                            parts.append("ready" if left <= 0 else f"{left}s")
                        info = " ".join(parts)
                    print(f"  {c.contract_id:14} {c.type:8} {c.status:10} {c.amount:8.2f}  {info}")

        elif choice == "19":
            print(f"""
  Send rules
  ──────────
  MIN_SEND_AMOUNT  : {MIN_SEND_AMOUNT} VEX
  MAX_MEMO_LEN     : {MAX_MEMO_LEN}
  ALLOW_SELF_SEND  : {ALLOW_SELF_SEND}
  Prefix           : VEX…

  Multi-sig  : 14 create → 15 sign until M → auto-release
  Time-lock  : 16 create → 17 claim when ready

  Network    : 21 connect peer → blocks/tx auto-gossip
  Difficulty : adjusts every {DIFFICULTY_ADJUST_INTERVAL} blocks (target ~{TARGET_BLOCK_TIME}s)
""")

        elif choice == "20":
            print(f"\n  Explorer (local):  http://127.0.0.1:{HTTP_PORT}/explorer")
            print(f"  API:               http://127.0.0.1:{HTTP_PORT}/")
            print(f"  Node ID:           {net.node_id if net else '?'}")
            print(f"  VexloreBot:        {VEXLOREBOT_URL}")
            print("\n  For public link: run cloudflared in another window:")
            print(f"    cloudflared tunnel --url http://127.0.0.1:{HTTP_PORT}")
            try:
                import webbrowser
                webbrowser.open(f"http://127.0.0.1:{HTTP_PORT}/explorer")
            except Exception:
                pass

        elif choice == "21":
            url = input("Peer URL (e.g. http://127.0.0.1:5001): ").strip()
            if url:
                net.add_peer(url)

        elif choice == "22":
            peers = net.list_peers()
            if not peers:
                print("No peers yet. Use 21 or start with --peer URL")
            else:
                print(f"\n{'NODE':12} {'HEIGHT':>6}  {'LAST':>8}  URL")
                for p in peers:
                    age = int(time.time() - p.last_seen) if p.last_seen else 9999
                    print(f"  {p.node_id or '?':10} {p.height:6}  {age:5}s   {p.url}")

        elif choice == "23":
            if not bc.mempool:
                print("Mempool empty")
            else:
                print(f"Broadcasting {len(bc.mempool)} txs...")
                for tx in list(bc.mempool):
                    net.broadcast_tx(tx)
                print("[+] Done")

        elif choice == "24":
            net.force_sync()

        elif choice == "0":
            print("Bye — keep your seed safe.")
            if net:
                net.stop()
            break
        else:
            print("Unknown")


if __name__ == "__main__":
    main()
