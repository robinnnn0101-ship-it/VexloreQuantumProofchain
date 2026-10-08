#!/usr/bin/env python3
"""
Vexlore Quantumproof Chain  v0.8 — CONSENSUS
Educational post-quantum blockchain prototype.

New in v0.8:
  - Multiple miners
  - Orphan block handling
  - Chain reorg rules (longest valid chain wins)
  - Block reward (coinbase)

Previous features kept:
  - Seed phrase wallet
  - Encrypted wallet file
  - Multiple addresses
  - Transaction history
  - Fast balance
  - ML-DSA (Dilithium) signatures

Not production-ready – for learning only.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("[-] 'requests' package required:  pip install requests")
    sys.exit(1)

# Optional cryptography for wallet encryption
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

# ---------------------------------------------------------------------------
# Pure-Python ML-DSA (Dilithium) – put dilithium_src folder next to this file
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent / "dilithium_src"))
try:
    from dilithium_py.ml_dsa import ML_DSA_44
    HAS_PQ = True
except ImportError:
    print("[-] dilithium_src not found!")
    print("    Expected folder: dilithium_src/")
    print("    (You can still run without real PQ signatures for learning)")
    HAS_PQ = False

    # Tiny fake PQ for demo when dilithium is missing
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
            # Very weak – only for demo
            return True
    ML_DSA_44 = FakePQ()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VERSION = "0.8"
BLOCK_REWARD = 50.0          # coins given to the miner of each block
DIFFICULTY = 4               # number of leading zeros required
MAX_TX_PER_BLOCK = 20
ORPHAN_MAX = 50              # keep at most this many orphan blocks
DATA_DIR = Path("vexlore_data")
CHAIN_FILE = DATA_DIR / "chain.json"
WALLET_FILE = DATA_DIR / "wallet.enc"
MEMPOOL_FILE = DATA_DIR / "mempool.json"

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
    h = sha256(pubkey)
    return "VEX" + h[:20]

# ---------------------------------------------------------------------------
# Data structures
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

    def message_to_sign(self) -> bytes:
        payload = {
            "tx_id": self.tx_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "memo": self.memo,
            "is_coinbase": self.is_coinbase,
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
            pk = bytes.fromhex(self.public_key)
            sig = bytes.fromhex(self.signature)
            return pq_verify(pk, self.message_to_sign(), sig)
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
    hash: str = ""

    def calculate_hash(self) -> str:
        tx_data = [t.to_dict() for t in self.transactions]
        payload = {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": tx_data,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "miner": self.miner,
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": [t.to_dict() for t in self.transactions],
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "miner": self.miner,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        txs = [Transaction.from_dict(t) for t in d.get("transactions", [])]
        return cls(
            index=d["index"],
            timestamp=d["timestamp"],
            transactions=txs,
            previous_hash=d["previous_hash"],
            nonce=d.get("nonce", 0),
            miner=d.get("miner", ""),
            hash=d.get("hash", ""),
        )

# ---------------------------------------------------------------------------
# Blockchain core with consensus features (v0.8)
# ---------------------------------------------------------------------------
class Blockchain:
    def __init__(self):
        self.chain: List[Block] = []
        self.orphans: Dict[str, Block] = {}          # hash → block
        self.mempool: List[Transaction] = []
        self.balances: Dict[str, float] = {}         # address → balance
        self.lock = threading.RLock()
        DATA_DIR.mkdir(exist_ok=True)
        self.load()

    # ---------- persistence ----------
    def save(self):
        with self.lock:
            data = {
                "chain": [b.to_dict() for b in self.chain],
                "orphans": {h: b.to_dict() for h, b in self.orphans.items()},
                "mempool": [t.to_dict() for t in self.mempool],
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
            self.orphans = {
                h: Block.from_dict(b) for h, b in data.get("orphans", {}).items()
            }
            self.mempool = [Transaction.from_dict(t) for t in data.get("mempool", [])]
            self.rebuild_balances()
            print(f"[+] Loaded chain height {len(self.chain)-1}")
        except Exception as e:
            print(f"[!] Failed to load chain: {e}")
            self.create_genesis()

    def create_genesis(self):
        genesis = Block(
            index=0,
            timestamp=time.time(),
            transactions=[],
            previous_hash="0" * 64,
            miner="genesis",
        )
        genesis.hash = genesis.calculate_hash()
        self.chain = [genesis]
        self.rebuild_balances()
        self.save()
        print("[+] Genesis block created")

    # ---------- balances ----------
    def rebuild_balances(self):
        self.balances = {}
        for block in self.chain:
            for tx in block.transactions:
                if not tx.is_coinbase:
                    self.balances[tx.sender] = self.balances.get(tx.sender, 0.0) - tx.amount
                self.balances[tx.recipient] = self.balances.get(tx.recipient, 0.0) + tx.amount
        # clean tiny floats
        for addr in list(self.balances):
            if abs(self.balances[addr]) < 1e-9:
                del self.balances[addr]

    def get_balance(self, address: str) -> float:
        return self.balances.get(address, 0.0)

    # ---------- mempool ----------
    def add_transaction(self, tx: Transaction) -> bool:
        with self.lock:
            if not tx.verify():
                print("[-] Invalid signature")
                return False
            if not tx.is_coinbase:
                if self.get_balance(tx.sender) < tx.amount:
                    print("[-] Insufficient balance")
                    return False
            # prevent double-spend in mempool
            for existing in self.mempool:
                if existing.tx_id == tx.tx_id:
                    return False
            self.mempool.append(tx)
            self.save()
            return True

    # ---------- mining ----------
    def mine_block(self, miner_address: str) -> Optional[Block]:
        with self.lock:
            if not self.chain:
                return None

            # take transactions from mempool
            txs = self.mempool[:MAX_TX_PER_BLOCK]
            # create coinbase (block reward)
            coinbase = Transaction(
                tx_id=str(uuid.uuid4()),
                sender="COINBASE",
                recipient=miner_address,
                amount=BLOCK_REWARD,
                timestamp=time.time(),
                is_coinbase=True,
            )
            all_txs = [coinbase] + txs

            prev = self.chain[-1]
            block = Block(
                index=prev.index + 1,
                timestamp=time.time(),
                transactions=all_txs,
                previous_hash=prev.hash,
                miner=miner_address,
            )

            # Proof-of-Work
            target = "0" * DIFFICULTY
            while True:
                block.hash = block.calculate_hash()
                if block.hash.startswith(target):
                    break
                block.nonce += 1
                if block.nonce % 100000 == 0:
                    # check if someone else already mined a longer chain
                    if len(self.chain) > prev.index + 1:
                        print("[!] Someone else mined first – aborting")
                        return None

            # success
            self.chain.append(block)
            # remove used txs from mempool
            used_ids = {t.tx_id for t in txs}
            self.mempool = [t for t in self.mempool if t.tx_id not in used_ids]
            self.rebuild_balances()
            self.save()
            print(f"[+] Block {block.index} mined by {miner_address[:12]}...  reward={BLOCK_REWARD}")
            return block

    # ---------- orphan + reorg (core of v0.8) ----------
    def add_block(self, block: Block) -> str:
        """
        Try to add a block received from network or another miner.
        Returns: "accepted" | "orphan" | "rejected" | "reorg"
        """
        with self.lock:
            # already have it?
            if any(b.hash == block.hash for b in self.chain):
                return "rejected"
            if block.hash in self.orphans:
                return "rejected"

            # basic validity
            if not self._is_block_valid(block):
                return "rejected"

            tip = self.chain[-1]

            # connects to tip → normal extend
            if block.previous_hash == tip.hash and block.index == tip.index + 1:
                self.chain.append(block)
                self._apply_block(block)
                self._try_connect_orphans()
                self.save()
                return "accepted"

            # possible orphan
            if block.index > tip.index + 1 or block.previous_hash != tip.hash:
                if len(self.orphans) >= ORPHAN_MAX:
                    # drop oldest
                    oldest = next(iter(self.orphans))
                    del self.orphans[oldest]
                self.orphans[block.hash] = block
                print(f"[~] Orphan block saved (height {block.index})")
                # maybe this starts a longer chain?
                if self._try_reorg(block):
                    return "reorg"
                return "orphan"

            return "rejected"

    def _is_block_valid(self, block: Block) -> bool:
        # hash check
        if block.hash != block.calculate_hash():
            return False
        # PoW
        if not block.hash.startswith("0" * DIFFICULTY):
            return False
        # coinbase must exist and be first
        if not block.transactions or not block.transactions[0].is_coinbase:
            return False
        if block.transactions[0].amount != BLOCK_REWARD:
            return False
        # all non-coinbase txs must verify
        for tx in block.transactions[1:]:
            if not tx.verify():
                return False
        return True

    def _apply_block(self, block: Block):
        for tx in block.transactions:
            if not tx.is_coinbase:
                self.balances[tx.sender] = self.balances.get(tx.sender, 0.0) - tx.amount
            self.balances[tx.recipient] = self.balances.get(tx.recipient, 0.0) + tx.amount
        # remove from mempool
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
        """
        If we can build a longer chain using orphans + new_block,
        switch to it.
        """
        # simple longest-chain rule
        # walk backwards from new_block using orphans + main chain
        candidate = [new_block]
        current = new_block
        seen = {new_block.hash}

        while True:
            # look for parent in orphans
            parent = None
            for h, o in self.orphans.items():
                if o.hash == current.previous_hash:
                    parent = o
                    break
            if parent is None:
                # maybe parent is already in main chain
                for b in self.chain:
                    if b.hash == current.previous_hash:
                        parent = b
                        break
            if parent is None:
                break
            if parent.hash in seen:
                break
            candidate.insert(0, parent)
            seen.add(parent.hash)
            current = parent
            if parent.index == 0:
                break

        # now candidate should start from a known block or genesis
        if not candidate:
            return False

        # find common ancestor
        common_idx = -1
        for i, b in enumerate(self.chain):
            if b.hash == candidate[0].previous_hash or b.hash == candidate[0].hash:
                common_idx = i
                break
        if common_idx == -1 and candidate[0].index != 0:
            return False

        # build new chain
        if common_idx >= 0:
            new_chain = self.chain[: common_idx + 1] + candidate
        else:
            new_chain = candidate

        # only reorg if strictly longer
        if len(new_chain) <= len(self.chain):
            return False

        print(f"[!] REORG!  old height {len(self.chain)-1} → new height {len(new_chain)-1}")
        self.chain = new_chain
        # clean orphans that are now in chain
        for b in candidate:
            self.orphans.pop(b.hash, None)
        self.rebuild_balances()
        self.save()
        return True

    # ---------- helpers ----------
    def height(self) -> int:
        return len(self.chain) - 1

    def tip_hash(self) -> str:
        return self.chain[-1].hash if self.chain else ""

# ---------------------------------------------------------------------------
# Simple Wallet (from v0.4)
# ---------------------------------------------------------------------------
class Wallet:
    def __init__(self):
        self.seed_phrase: List[str] = []
        self.addresses: List[str] = []
        self.keys: Dict[str, Tuple[bytes, bytes]] = {}  # address → (pk, sk)
        self.unlocked = False
        self.password: Optional[str] = None

    def generate_seed(self) -> List[str]:
        # very simple 12-word seed for education (not real BIP39)
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
        material = hashlib.sha256(seed + str(index).encode()).digest()
        # use material as entropy for keygen
        # (real systems use proper HD derivation)
        pk, sk = pq_keygen()
        # make deterministic for same seed+index
        # simple trick for demo
        random_state = int.from_bytes(material[:8], "big")
        # just generate normally – for real HD you need proper KDF
        return pk, sk

    def create_address(self) -> str:
        idx = len(self.addresses)
        pk, sk = self.derive_key(idx)
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
        sig = pq_sign(sk, tx.message_to_sign())
        tx.signature = sig.hex()
        return True

    def lock(self):
        self.keys.clear()
        self.unlocked = False
        self.password = None
        print("[+] Wallet locked")

    def save_encrypted(self, password: str):
        if not HAS_CRYPTO:
            print("[-] cryptography not available")
            return
        data = {
            "seed": self.seed_phrase,
            "addresses": self.addresses,
        }
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend(),
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        f = Fernet(key)
        token = f.encrypt(json.dumps(data).encode())
        with open(WALLET_FILE, "wb") as fp:
            fp.write(salt + token)
        print(f"[+] Wallet saved encrypted → {WALLET_FILE}")

    def load_encrypted(self, password: str) -> bool:
        if not HAS_CRYPTO or not WALLET_FILE.exists():
            return False
        try:
            raw = open(WALLET_FILE, "rb").read()
            salt, token = raw[:16], raw[16:]
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend(),
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            f = Fernet(key)
            data = json.loads(f.decrypt(token).decode())
            self.seed_phrase = data["seed"]
            self.addresses = data["addresses"]
            # re-derive keys
            for i, addr in enumerate(self.addresses):
                pk, sk = self.derive_key(i)
                self.keys[addr] = (pk, sk)
            self.unlocked = True
            self.password = password
            print("[+] Wallet unlocked")
            return True
        except Exception as e:
            print(f"[-] Wrong password or corrupt wallet: {e}")
            return False

# ---------------------------------------------------------------------------
# Global objects
# ---------------------------------------------------------------------------
bc = Blockchain()
wallet = Wallet()

# ---------------------------------------------------------------------------
# Menu (kid-friendly)
# ---------------------------------------------------------------------------
def print_menu():
    print("\n" + "=" * 50)
    print(f"  Vexlore v{VERSION}  —  CONSENSUS")
    print("=" * 50)
    print("1.  Create / Restore wallet (seed phrase)")
    print("2.  Unlock existing wallet")
    print("3.  Show balances")
    print("4.  Faucet (get free test coins)")
    print("5.  Send coins")
    print("6.  Mine a block (you get the reward!)")
    print("7.  Show chain tip / height")
    print("8.  Show orphans")
    print("9.  List my addresses")
    print("10. Create new address")
    print("11. Transaction history")
    print("12. Lock wallet")
    print("13. Mine many blocks (demo multiple miners)")
    print("0.  Exit")
    print("=" * 50)

def main():
    print(f"\n🚀 Vexlore Quantumproof Chain v{VERSION}")
    print("   Multiple miners • Orphans • Reorg • Block reward\n")

    while True:
        print_menu()
        choice = input("Choose → ").strip()

        if choice == "1":
            print("\n--- Create or Restore Wallet ---")
            mode = input("New wallet (n) or Restore from seed (r)? ").strip().lower()
            if mode == "r":
                phrase = input("Enter 12 words separated by space:\n→ ").strip().split()
                if len(phrase) != 12:
                    print("[-] Need exactly 12 words")
                    continue
                wallet.seed_phrase = phrase
            else:
                wallet.generate_seed()
                print("\n*** WRITE THESE 12 WORDS DOWN AND KEEP THEM SAFE ***")
                print(" ".join(wallet.seed_phrase))
                print("****************************************************\n")

            pwd = input("Choose a password to encrypt the wallet: ").strip()
            if not pwd:
                print("[-] Password required")
                continue
            wallet.create_address()
            wallet.save_encrypted(pwd)
            wallet.unlocked = True
            wallet.password = pwd
            print(f"[+] Primary address: {wallet.get_primary()}")

        elif choice == "2":
            pwd = input("Password: ").strip()
            wallet.load_encrypted(pwd)

        elif choice == "3":
            if not wallet.unlocked:
                print("[-] Unlock wallet first")
                continue
            print("\nYour balances:")
            for addr in wallet.addresses:
                bal = bc.get_balance(addr)
                print(f"  {addr}  →  {bal:.4f} VEX")
            print(f"\nTotal: {sum(bc.get_balance(a) for a in wallet.addresses):.4f} VEX")

        elif choice == "4":
            if not wallet.unlocked:
                print("[-] Unlock wallet first")
                continue
            addr = wallet.get_primary()
            # simple faucet – just add balance for demo
            bc.balances[addr] = bc.balances.get(addr, 0.0) + 100.0
            bc.save()
            print(f"[+] Faucet sent 100 VEX to {addr}")

        elif choice == "5":
            if not wallet.unlocked:
                print("[-] Unlock wallet first")
                continue
            sender = wallet.get_primary()
            recipient = input("Recipient address: ").strip()
            try:
                amount = float(input("Amount: ").strip())
            except ValueError:
                print("[-] Bad amount")
                continue
            tx = Transaction(
                tx_id=str(uuid.uuid4()),
                sender=sender,
                recipient=recipient,
                amount=amount,
                timestamp=time.time(),
            )
            if wallet.sign_tx(tx, sender):
                if bc.add_transaction(tx):
                    print("[+] Transaction added to mempool")
                else:
                    print("[-] Failed to add transaction")
            else:
                print("[-] Signing failed")

        elif choice == "6":
            if not wallet.unlocked:
                print("[-] Unlock wallet first")
                continue
            miner = wallet.get_primary()
            print(f"Mining as {miner} ... (this may take a few seconds)")
            block = bc.mine_block(miner)
            if block:
                print(f"[+] Success! You earned {BLOCK_REWARD} VEX")
            else:
                print("[-] Mining aborted (someone else won)")

        elif choice == "7":
            print(f"\nHeight      : {bc.height()}")
            print(f"Tip hash    : {bc.tip_hash()}")
            print(f"Mempool     : {len(bc.mempool)} txs")
            print(f"Orphans     : {len(bc.orphans)}")
            print(f"Difficulty  : {DIFFICULTY}")
            print(f"Block reward: {BLOCK_REWARD} VEX")

        elif choice == "8":
            if not bc.orphans:
                print("No orphan blocks")
            else:
                print("\nOrphan blocks:")
                for h, b in bc.orphans.items():
                    print(f"  height {b.index}  hash={h[:16]}...  miner={b.miner[:12]}")

        elif choice == "9":
            if not wallet.unlocked:
                print("[-] Unlock wallet first")
                continue
            for i, a in enumerate(wallet.addresses):
                print(f"  [{i}] {a}")

        elif choice == "10":
            if not wallet.unlocked:
                print("[-] Unlock wallet first")
                continue
            addr = wallet.create_address()
            wallet.save_encrypted(wallet.password)
            print(f"[+] New address: {addr}")

        elif choice == "11":
            print("\nRecent transactions (last 10 blocks):")
            for block in bc.chain[-10:]:
                for tx in block.transactions:
                    kind = "COINBASE" if tx.is_coinbase else "TRANSFER"
                    print(f"  [{block.index}] {kind}  {tx.sender[:12]}… → {tx.recipient[:12]}…  {tx.amount}")

        elif choice == "12":
            wallet.lock()

        elif choice == "13":
            # Demo: multiple miners racing
            if not wallet.unlocked:
                print("[-] Unlock wallet first")
                continue
            print("\n=== Multiple miners demo ===")
            print("Simulating 3 miners racing for the next block...")
            results = []

            def miner_worker(name, addr):
                b = bc.mine_block(addr)
                results.append((name, b))

            threads = []
            # create temporary extra addresses for the race
            extra = []
            for i in range(2):
                extra.append(wallet.create_address())

            miners = [
                ("Miner-A (you)", wallet.get_primary()),
                ("Miner-B", extra[0]),
                ("Miner-C", extra[1]),
            ]
            for name, addr in miners:
                t = threading.Thread(target=miner_worker, args=(name, addr))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            for name, block in results:
                if block:
                    print(f"  {name} won block {block.index}!")
                else:
                    print(f"  {name} lost the race")

        elif choice == "0":
            print("Bye! Keep your seed phrase safe.")
            break

        else:
            print("Unknown choice")

if __name__ == "__main__":
    main()