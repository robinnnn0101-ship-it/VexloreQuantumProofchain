#!/usr/bin/env python3
"""
Vexlore Quantumproof Chain  v0.9 — CONTRACTS + EXPLORER
Educational post-quantum blockchain.

Built on the easy v0.5 core (hybrid PQ, networking, wallets) and adds:
  • Light contracts — multi-sig vaults, time-locks, send rules
  • Vexlore Explorer — local web UI with VexloreBot branding
  • Same simple CLI flow you already know

Still includes:
  ML-KEM-512 • Hybrid Ed25519+ML-DSA-44 • VEXQ addresses • Key rotation
  Seed wallets • Multi-address • Peers • Gossip

Not production-ready — for learning only.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
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
    print("[-] pip install requests")
    sys.exit(1)

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    import base64
except ImportError:
    print("[-] pip install cryptography")
    sys.exit(1)

# ---- Post-quantum libraries ----
sys.path.insert(0, str(Path(__file__).parent / "dilithium_src"))
sys.path.insert(0, str(Path(__file__).parent / "kyber_src"))
try:
    from dilithium_py.ml_dsa import ML_DSA_44
except ImportError:
    print("[-] dilithium_src missing")
    sys.exit(1)
try:
    from kyber_py.ml_kem import ML_KEM_512
except ImportError:
    print("[-] kyber_src missing (ML-KEM)")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CHAIN_NAME = "Vexlore Quantumproof Chain"
VERSION = "0.9.0-contracts-explorer"

INITIAL_DIFFICULTY = 3
TARGET_BLOCK_TIME = 20
DIFFICULTY_ADJUST_EVERY = 5
MIN_DIFFICULTY = 2
MAX_DIFFICULTY = 6
MAX_TX_PER_BLOCK = 50
DEFAULT_PORT = 5000
SYNC_INTERVAL = 15
MNEMONIC_WORDS = 12
PBKDF2_ITERATIONS = 100_000
ADDR_PREFIX = "VEXQ"          # quantum-safe address prefix
MIN_SEND_AMOUNT = 0.01
MAX_MEMO_LEN = 120
ALLOW_SELF_SEND = False
BLOCK_REWARD = 10.0           # network mint on mine (unchanged faucet separate)

DATA_DIR = Path(__file__).parent / "data"
CHAIN_FILE = DATA_DIR / "vexlore_chain.json"
PEERS_FILE = DATA_DIR / "peers.json"
WALLETS_DIR = Path(__file__).parent / "wallet"
DATA_DIR.mkdir(exist_ok=True)
WALLETS_DIR.mkdir(exist_ok=True)

# Short BIP-39 wordlist reference (full list embedded compactly)
BIP39_WORDLIST = open(Path(__file__).parent / "bip39_words.txt").read().split() if (Path(__file__).parent / "bip39_words.txt").exists() else None

# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_bytes(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()

def pq_keygen_from_seed(zeta: bytes) -> Tuple[bytes, bytes]:
    if len(zeta) != 32:
        zeta = sha256_bytes(zeta)
    return ML_DSA_44._keygen_internal(zeta)

def pq_sign(sk: bytes, msg: bytes) -> bytes:
    return ML_DSA_44.sign(sk, msg)

def pq_verify(pk: bytes, msg: bytes, sig: bytes) -> bool:
    return ML_DSA_44.verify(pk, msg, sig)

def ed_keygen_from_seed(seed32: bytes) -> Tuple[ed25519.Ed25519PrivateKey, bytes]:
    """Deterministic Ed25519 from 32-byte seed."""
    # Use first 32 bytes as seed material for Ed25519
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed32)
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub

def hybrid_sign(ed_priv: ed25519.Ed25519PrivateKey, mldsa_sk: bytes, message: bytes) -> str:
    """Hybrid signature: ed25519_sig || mldsa_sig  (both hex, joined by '.')"""
    ed_sig = ed_priv.sign(message)
    pq_sig = pq_sign(mldsa_sk, message)
    return ed_sig.hex() + "." + pq_sig.hex()

def hybrid_verify(ed_pk_hex: str, mldsa_pk_hex: str, message: bytes, sig_blob: str) -> bool:
    try:
        ed_part, pq_part = sig_blob.split(".", 1)
        ed_pk = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(ed_pk_hex))
        ed_pk.verify(bytes.fromhex(ed_part), message)
        return pq_verify(bytes.fromhex(mldsa_pk_hex), message, bytes.fromhex(pq_part))
    except Exception:
        return False

def quantum_safe_address(mldsa_pk: bytes, ed_pk: bytes) -> str:
    """VEXQ + 28 hex chars of SHA256(mldsa_pk || ed_pk)"""
    h = sha256_bytes(mldsa_pk + ed_pk)
    return ADDR_PREFIX + h.hex()[:28]

def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

def encrypt_blob(data: bytes, password: str) -> dict:
    salt = secrets.token_bytes(16)
    f = Fernet(_derive_fernet_key(password, salt))
    return {"salt": base64.b64encode(salt).decode(),
            "ciphertext": base64.b64encode(f.encrypt(data)).decode(),
            "kdf": "pbkdf2-sha256", "iterations": PBKDF2_ITERATIONS}

def decrypt_blob(enc: dict, password: str) -> bytes:
    f = Fernet(_derive_fernet_key(password, base64.b64decode(enc["salt"])))
    return f.decrypt(base64.b64decode(enc["ciphertext"]))

def shared_secret_to_fernet(shared: bytes) -> Fernet:
    """Turn 32-byte ML-KEM shared secret into a Fernet key."""
    key = base64.urlsafe_b64encode(
        HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"vexlore-node-v09").derive(shared)
    )
    return Fernet(key)

# ---------------------------------------------------------------------------
# Mnemonic (fallback if no bip39 file – generate simple 12-word from entropy)
# ---------------------------------------------------------------------------
_FALLBACK_WORDS = (
    "abandon ability able about above absent absorb abstract absurd abuse access "
    "accident account accuse achieve acid acoustic acquire across act action actor "
    "actress actual adapt add addict address adjust admit adult advance advice "
    "aerobic affair afford afraid again age agent agree ahead aim air airport "
    "aisle alarm album alcohol alert alien all alley allow almost alone alpha "
    "already also alter always amateur amazing among amount amused analyst anchor "
    "ancient anger angle angry animal ankle announce annual another answer antenna "
    "antique anxiety any apart apology appear apple approve april arch arctic "
    "area arena argue arm armed armor army around arrange arrest arrive arrow "
    "art artefact artist artwork ask aspect assault asset assist assume asthma "
    "athlete atom attack attend attitude attract auction audit august aunt author "
    "auto autumn average avocado avoid awake aware away awesome awful awkward "
    "axis baby bachelor bacon badge bag balance balcony ball bamboo banana banner "
    "bar barely bargain barrel base basic basket battle beach bean beauty because "
    "become beef before begin behave behind believe below belt bench benefit best "
    "betray better between beyond bicycle bid bike bind biology bird birth bitter "
    "black blade blame blanket blast bleak bless blind blood blossom blouse blue "
    "blur blush board boat body boil bomb bone bonus book boost border boring "
    "borrow boss bottom bounce box boy bracket brain brand brass brave bread "
    "breeze brick bridge brief bright bring brisk broccoli broken bronze broom "
    "brother brown brush bubble buddy budget buffalo build bulb bulk bullet bundle "
    "bunker burden burger burst bus business busy butter buyer buzz cabbage cabin "
    "cable cactus cage cake call calm camera camp can canal cancel candy cannon "
    "canoe canvas canyon capable capital captain car carbon card cargo carpet carry "
    "cart case cash casino castle casual cat catalog catch category cattle caught "
    "cause caution cave ceiling celery cement census century cereal certain chair "
    "chalk champion change chaos chapter charge chase chat cheap check cheese chef "
    "cherry chest chicken chief child chimney choice choose chronic chuckle chunk "
    "churn cigar cinnamon circle citizen city civil claim clap clarify claw clay "
    "clean clerk clever click client cliff climb clinic clip clock clog close "
    "cloth cloud clown club clump cluster clutch coach coast coconut code coffee "
    "coil coin collect color column combine come comfort comic common company "
    "concert conduct confirm congress connect consider control convince cook cool "
    "copper copy coral core corn correct cost cotton couch country couple course "
    "cousin cover coyote crack cradle craft cram crane crash crater crawl crazy "
    "cream credit creek crew cricket crime crisp critic crop cross crouch crowd "
    "crucial cruel cruise crumble crunch crush cry crystal cube culture cup cupboard "
    "curious current curtain curve cushion custom cute cycle dad damage damp dance "
    "danger daring dash daughter dawn day deal debate debris decade december decide "
    "decline decorate decrease deer defense define defy degree delay deliver demand "
    "demise denial dentist deny depart depend deposit depth deputy derive describe "
    "desert design desk despair destroy detail detect develop device devote diagram "
    "dial diamond diary dice diesel diet differ digital dignity dilemma dinner "
    "dinosaur direct dirt disagree discover disease dish dismiss disorder display "
    "distance divert divide divorce dizzy doctor document dog doll dolphin domain "
    "donate donkey donor door dose double dove draft dragon drama drastic draw "
    "dream dress drift drill drink drip drive drop drum dry duck dumb dune during "
    "dust dutch duty dwarf dynamic eager eagle early earn earth easily east easy "
    "echo ecology economy edge edit educate effort egg eight either elbow elder "
    "electric elegant element elephant elevator elite else embark embody embrace "
    "emerge emotion employ empower empty enable enact end endless endorse enemy "
    "energy enforce engage engine enhance enjoy enlist enough enrich enroll ensure "
    "enter entire entry envelope episode equal equip era erase erode erosion error "
    "erupt escape essay essence estate eternal ethics evidence evil evoke evolve "
    "exact example excess exchange excite exclude excuse execute exercise exhaust "
    "exhibit exile exist exit exotic expand expect expire explain expose express "
    "extend extra eye eyebrow fabric face faculty fade faint faith fall false "
    "fame family famous fan fancy fantasy farm fashion fat fatal father fatigue "
    "fault favorite feature february federal fee feed feel female fence festival "
    "fetch fever few fiber fiction field figure file film filter final find fine "
    "finger finish fire firm first fiscal fish fit fitness fix flag flame flash "
    "flat flavor flee flight flip float flock floor flower fluid flush fly foam "
    "focus fog foil fold follow food foot force forest forget fork fortune forum "
    "forward fossil foster found fox fragile frame frequent fresh friend fringe "
    "frog front frost frown frozen fruit fuel fun funny furnace fury future gadget "
    "gain galaxy gallery game gap garage garbage garden garlic garment gas gasp "
    "gate gather gauge gaze general genius genre gentle genuine gesture ghost giant "
    "gift giggle ginger giraffe girl give glad glance glare glass glide glimpse "
    "globe gloom glory glove glow glue goat goddess gold good goose gorilla gospel "
    "gossip govern gown grab grace grain grant grape grass gravity great green "
    "grid grief grit grocery group grow grunt guard guess guide guilt guitar gun "
    "gym habit hair half hammer hamster hand happy harbor hard harsh harvest hat "
    "have hawk hazard head health heart heavy hedgehog height hello helmet help "
    "hen hero hidden high hill hint hip hire history hobby hockey hold hole holiday "
    "hollow home honey hood hope horn horror horse hospital host hotel hour hover "
    "hub huge human humble humor hundred hungry hunt hurdle hurry hurt husband "
    "hybrid ice icon idea identify idle ignore ill illegal illness image imitate "
    "immense immune impact impose improve impulse inch include income increase "
    "index indicate indoor industry infant inflict inform inhale inherit initial "
    "inject injury inmate inner innocent input inquiry insane insect inside inspire "
    "install intact interest into invest invite involve iron island isolate issue "
    "item ivory jacket jaguar jar jazz jealous jeans jelly jewel job join joke "
    "journey joy judge juice jump jungle junior junk just kangaroo keen keep ketchup "
    "key kick kid kidney kind kingdom kiss kit kitchen kite kitten kiwi knee knife "
    "knock know lab label labor ladder lady lake lamp language laptop large later "
    "latin laugh laundry lava law lawn lawsuit layer lazy leader leaf learn leave "
    "lecture left leg legal legend leisure lemon lend length lens leopard lesson "
    "letter level liar liberty library license life lift light like limb limit "
    "link lion liquid list little live lizard load loan lobster local lock logic "
    "lonely long loop lottery loud lounge love loyal lucky luggage lumber lunar "
    "lunch luxury lyrics machine mad magic magnet maid mail main major make mammal "
    "man manage mandate mango mansion manual maple marble march margin marine market "
    "marriage mask mass master match material math matrix matter maximum maze "
    "meadow mean measure meat mechanic medal media melody melt member memory mention "
    "menu mercy merge merit merry mesh message metal method middle midnight milk "
    "million mimic mind minimum minor minute miracle mirror misery miss mistake "
    "mix mixed mixture mobile model modify mom moment monitor monkey monster month "
    "moon moral more morning mosquito mother motion motor mountain mouse move movie "
    "much muffin mule multiply muscle museum mushroom music must mutual myself mystery "
    "myth naive name napkin narrow nasty nation nature near neck need negative "
    "neglect neither nephew nerve nest net network neutral never news next nice "
    "night noble noise nominee noodle normal north nose notable note nothing notice "
    "novel now nuclear number nurse nut oak obey object oblige obscure observe "
    "obtain obvious occur ocean october odor off offer office often oil okay old "
    "olive olympic omit once one onion online only open opera opinion oppose option "
    "orange orbit orchard order ordinary organ orient original orphan ostrich other "
    "outdoor outer output outside oval oven over own owner oxygen oyster ozone "
    "pact paddle page pair palace palm panda panel panic panther paper parade "
    "parent park parrot party pass patch path patient patrol pattern pause pave "
    "payment peace peanut pear peasant pelican pen penalty pencil people pepper "
    "perfect permit person pet phone photo phrase physical piano picnic picture "
    "piece pig pigeon pill pilot pink pioneer pipe pistol pitch pizza place planet "
    "plastic plate play please pledge pluck plug plunge poem poet point polar pole "
    "police pond pony pool popular portion position possible post potato pottery "
    "poverty powder power practice praise predict prefer prepare present pretty "
    "prevent price pride primary print priority prison private prize problem process "
    "produce profit program project promote proof property prosper protect proud "
    "provide public pudding pull pulp pulse pumpkin punch pupil puppy purchase purity "
    "purpose purse push put puzzle pyramid quality quantum quarter question quick "
    "quit quiz quote rabbit raccoon race rack radar radio rail rain raise rally "
    "ramp ranch random range rapid rare rate rather raven raw razor ready real "
    "reason rebel rebuild recall receive recipe record recycle reduce reflect reform "
    "refuse region regret regular reject relax release relief rely remain remember "
    "remind remove render renew rent reopen repair repeat replace report require "
    "rescue resemble resist resource response result retire retreat return reunion "
    "reveal review reward rhythm rib ribbon rice rich ride ridge rifle right rigid "
    "ring riot ripple risk ritual rival river road roast robot robust rocket romance "
    "roof rookie room rose rotate rough round route royal rubber rude rug rule "
    "run runway rural sad saddle sadness safe sail salad salmon salon salt salute "
    "same sample sand satisfy satoshi sauce sausage save say scale scan scare scatter "
    "scene scheme school science scissors scorpion scream screen screw script scrub "
    "sea search season seat second secret section security seed seek segment select "
    "sell seminar senior sense sentence series service session settle setup seven "
    "shadow shaft shallow share shed shell sheriff shield shift shine ship shiver "
    "shock shoe shoot shop shore short shoulder shove shrimp shrug shuffle shy "
    "sibling sick side siege sight sign silent silk silly silver similar simple "
    "since sing siren sister situate six size skate sketch ski skill skin skirt "
    "skull slab slam sleep slender slice slide slight slim slogan slot slow slush "
    "small smart smile smoke smooth snack snake snap sniff snow soap soccer social "
    "sock soda soft solar soldier solid solution solve someone song soon sorry "
    "sort soul sound soup source south space spare spatial spawn speak special "
    "speed spell spend sphere spice spider spike spin spirit split spoil sponsor "
    "spoon sport spot spray spread spring spy square squeeze squirrel stable stadium "
    "staff stage stairs stamp stand start state stay steak steel stem step stereo "
    "stick still sting stock stomach stone stool story stove strategy street strike "
    "strong struggle student stuff stumble style subject submit subway success such "
    "sudden suffer sugar suggest suit summer sun sunny sunset super supply supreme "
    "sure surface surge surprise surround survey suspect sustain swallow swamp swap "
    "swarm swear sweet swift swim swing switch sword symbol symptom syrup system "
    "table tackle tag tail talent talk tank tape target task taste tattoo taxi "
    "teach team tell ten tenant tennis tent term test text thank that the their "
    "them then theory there they thing this thought three thrive throw thumb thunder "
    "ticket tide tiger tilt timber time tiny tip tired tissue title toast tobacco "
    "today toddler toe together toilet token tomato tomorrow tone tongue tonight "
    "tool tooth top topic topple torch tornado tortoise toss total tourist toward "
    "tower town toy track trade traffic tragic train transfer trap trash travel "
    "tray treat tree trend trial tribe trick trigger trim trip trophy trouble truck "
    "true truly trumpet trust truth try tube tuition tumble tuna tunnel turkey "
    "turn turtle twelve twenty twice twin twist two type typical ugly umbrella "
    "unable unaware uncle uncover under undo unfair unfold unhappy unique unit "
    "universe unknown unlock until unusual unveil update upgrade uphold upon upper "
    "upset urban urge usage use used useful useless usual utility vacant vacuum "
    "vague valid valley valve van vanish vapor various vast vault vehicle velvet "
    "vendor venture venue verb verify version very vessel veteran viable vibrant "
    "vicious victory video view village vintage violin virtual virus visa visit "
    "visual vital vivid vocal voice void volcano volume vote voyage wage wagon "
    "wait walk wall walnut want warfare warm warrior wash wasp waste water wave "
    "way wealth weapon wear weasel weather web wedding weekend weird welcome west "
    "wet whale what wheat wheel when where whip whisper wide width wife wild will "
    "win window wine wing wink winner winter wire wisdom wise wish witness wolf "
    "woman wonder wood wool word work world worry worth wrap wreck wrestle wrist "
    "write wrong yard year yellow you young youth zebra zero zone zoo"
).split()

WORDLIST = BIP39_WORDLIST if BIP39_WORDLIST and len(BIP39_WORDLIST) >= 2048 else _FALLBACK_WORDS

def generate_mnemonic() -> str:
    entropy = secrets.token_bytes(16)
    h = hashlib.sha256(entropy).digest()
    bits = "".join(bin(b)[2:].zfill(8) for b in entropy) + bin(h[0])[2:].zfill(8)[:4]
    return " ".join(WORDLIST[int(bits[i:i+11], 2) % len(WORDLIST)] for i in range(0, 132, 11))

def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    mn = " ".join(mnemonic.strip().lower().split())
    return hashlib.pbkdf2_hmac("sha512", mn.encode(), ("mnemonic" + passphrase).encode(), 2048, 64)[:32]

def validate_mnemonic(mnemonic: str) -> bool:
    words = mnemonic.strip().lower().split()
    return len(words) == 12 and all(w in WORDLIST for w in words)

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
    public_key: str          # ML-DSA public key hex
    ed_public_key: str       # Ed25519 public key hex (hybrid)
    signature: str           # hybrid sig "ed.hex.mldsa.hex"
    memo: str = ""
    key_version: int = 0     # for rotation tracking
    lock_type: str = ""      # v0.9: multisig_deposit | timelock | ""
    lock_data: Dict[str, Any] = field(default_factory=dict)

    def message_to_sign(self) -> bytes:
        payload = {
            "tx_id": self.tx_id, "sender": self.sender, "recipient": self.recipient,
            "amount": self.amount, "timestamp": self.timestamp, "memo": self.memo,
            "key_version": self.key_version,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Transaction":
        # backward compat for old txs without hybrid fields
        d.setdefault("ed_public_key", "")
        d.setdefault("key_version", 0)
        d.setdefault("lock_type", "")
        d.setdefault("lock_data", {})
        if d.get("lock_data") is None: d["lock_data"] = {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    def verify(self) -> bool:
        if not self.ed_public_key:  # old-style pure ML-DSA
            try:
                return pq_verify(bytes.fromhex(self.public_key), self.message_to_sign(), bytes.fromhex(self.signature))
            except Exception:
                return False
        return hybrid_verify(self.ed_public_key, self.public_key, self.message_to_sign(), self.signature)


def check_send_rules(sender: str, recipient: str, amount: float, memo: str) -> Optional[str]:
    """Basic token send rules (v0.9). Returns error or None."""
    if amount < MIN_SEND_AMOUNT:
        return f"amount below minimum ({MIN_SEND_AMOUNT} VEX)"
    if amount <= 0:
        return "amount must be positive"
    if not ALLOW_SELF_SEND and sender == recipient:
        return "self-send is not allowed"
    if len(memo or "") > MAX_MEMO_LEN:
        return f"memo too long (max {MAX_MEMO_LEN})"
    if recipient and not (recipient.startswith(ADDR_PREFIX) or recipient == "VEXLORE_NETWORK"):
        return f"recipient must start with {ADDR_PREFIX}"
    return None


@dataclass
class Contract:
    """Light on-chain lock / vault (v0.9)."""
    contract_id: str
    type: str                  # multisig | timelock
    creator: str
    amount: float
    status: str = "open"       # open | released | claimed
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
class Block:
    index: int
    timestamp: float
    transactions: List[Transaction]
    previous_hash: str
    difficulty: int = INITIAL_DIFFICULTY
    nonce: int = 0
    hash: str = ""
    miner: str = "genesis"

    def compute_hash(self) -> str:
        tx_data = [t.to_dict() for t in self.transactions]
        s = json.dumps({"index": self.index, "timestamp": self.timestamp, "transactions": tx_data,
                        "previous_hash": self.previous_hash, "difficulty": self.difficulty,
                        "nonce": self.nonce, "miner": self.miner},
                       sort_keys=True, separators=(",", ":"))
        return sha256(s.encode())

    def mine(self) -> None:
        target = "0" * self.difficulty
        while True:
            self.hash = self.compute_hash()
            if self.hash.startswith(target):
                break
            self.nonce += 1

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "timestamp": self.timestamp,
                "transactions": [t.to_dict() for t in self.transactions],
                "previous_hash": self.previous_hash, "difficulty": self.difficulty,
                "nonce": self.nonce, "hash": self.hash, "miner": self.miner}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        txs = [Transaction.from_dict(t) for t in d["transactions"]]
        return cls(index=d["index"], timestamp=d["timestamp"], transactions=txs,
                   previous_hash=d["previous_hash"], difficulty=d.get("difficulty", INITIAL_DIFFICULTY),
                   nonce=d.get("nonce", 0), hash=d.get("hash", ""), miner=d.get("miner", ""))

# ---------------------------------------------------------------------------
# Wallet v0.5 – hybrid keys + rotation + seed + encrypted
# ---------------------------------------------------------------------------
class Wallet:
    def __init__(self, name: str = "default", password: Optional[str] = None):
        self.name = name
        self.path = WALLETS_DIR / f"{name}.json"
        self.master_seed: bytes = b""
        self.mnemonic: str = ""
        self.addresses: List[Dict[str, Any]] = []  # each entry has hybrid keys + version
        self.history: List[Dict[str, Any]] = []
        self._password: Optional[str] = password
        self._unlocked = False
        if self.path.exists():
            if password is None:
                print(f"[!] Wallet '{name}' encrypted – unlock first")
                return
            self.unlock(password)
        else:
            if password is None:
                password = self._ask_password(create=True)
            self._create_new(password)

    def _create_new(self, password: str) -> None:
        print(f"[*] Creating hybrid quantum-safe wallet '{self.name}' ...")
        self.mnemonic = generate_mnemonic()
        self.master_seed = mnemonic_to_seed(self.mnemonic)
        self._password = password
        self._derive_address(0)
        self._unlocked = True
        self._save()
        print(f"[+] Wallet ready (hybrid Ed25519 + ML-DSA-44)")
        print(f"    Primary address : {self.address}")
        print()
        print("  ╔══════════════════════════════════════════════════════════╗")
        print("  ║  WRITE DOWN YOUR SEED PHRASE AND KEEP IT SAFE!           ║")
        print("  ╚══════════════════════════════════════════════════════════╝")
        print(f"\n  {self.mnemonic}\n")

    @classmethod
    def restore(cls, name: str, mnemonic: str, password: str) -> "Wallet":
        mnemonic = " ".join(mnemonic.strip().lower().split())
        if not validate_mnemonic(mnemonic):
            raise ValueError("Invalid mnemonic")
        w = cls.__new__(cls)
        w.name, w.path = name, WALLETS_DIR / f"{name}.json"
        w.mnemonic, w.master_seed = mnemonic, mnemonic_to_seed(mnemonic)
        w.addresses, w.history = [], []
        w._password, w._unlocked = password, True
        w._derive_address(0)
        w._save()
        print(f"[+] Restored '{name}' → {w.address}")
        return w

    def unlock(self, password: str) -> bool:
        try:
            raw = json.loads(self.path.read_text())
            data = json.loads(decrypt_blob(raw["encrypted"], password).decode())
            self.master_seed = bytes.fromhex(data["master_seed"])
            self.addresses = data.get("addresses", [])
            self.history = data.get("history", [])
            self._password, self._unlocked = password, True
            if not self.addresses:
                self._derive_address(0)
                self._save()
            print(f"[+] Unlocked '{self.name}' → {self.address}")
            return True
        except Exception as e:
            print(f"[-] Unlock failed: {e}")
            return False

    def _save(self) -> None:
        data = {"master_seed": self.master_seed.hex(), "addresses": self.addresses,
                "history": self.history[-500:], "version": VERSION}
        enc = encrypt_blob(json.dumps(data).encode(), self._password)
        out = {"name": self.name, "encrypted": enc, "address_count": len(self.addresses),
               "primary_address": self.address, "version": VERSION, "algo": "hybrid-Ed25519+ML-DSA-44"}
        self.path.write_text(json.dumps(out, indent=2))

    def lock(self) -> None:
        self.master_seed = b""; self.addresses = []; self.history = []
        self._password = None; self._unlocked = False
        print(f"[+] Locked '{self.name}'")

    def _derive_address(self, index: int, version: int = 0) -> Dict[str, Any]:
        material = self.master_seed + index.to_bytes(4, "big") + version.to_bytes(2, "big")
        zeta = sha256_bytes(material)
        mldsa_pk, mldsa_sk = pq_keygen_from_seed(zeta)
        # separate seed for Ed25519
        ed_seed = sha256_bytes(b"ed25519" + material)
        ed_priv, ed_pk = ed_keygen_from_seed(ed_seed)
        addr = quantum_safe_address(mldsa_pk, ed_pk)
        entry = {
            "index": index, "version": version, "address": addr,
            "public_key": mldsa_pk.hex(), "secret_key": mldsa_sk.hex(),
            "ed_public_key": ed_pk.hex(),
            "ed_secret_key": ed_priv.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            ).hex(),
            "rotated": False,
        }
        for i, a in enumerate(self.addresses):
            if a["index"] == index and a.get("version", 0) == version:
                self.addresses[i] = entry
                return entry
        self.addresses.append(entry)
        self.addresses.sort(key=lambda x: (x["index"], x.get("version", 0)))
        return entry

    def new_address(self) -> str:
        self._require_unlocked()
        next_idx = max((a["index"] for a in self.addresses), default=-1) + 1
        entry = self._derive_address(next_idx)
        self._save()
        print(f"[+] New address #{next_idx}: {entry['address']}")
        return entry["address"]

    def rotate_key(self, address: Optional[str] = None) -> str:
        """Key rotation: create new version of an address (same index, higher version)."""
        self._require_unlocked()
        target = address or self.address
        old = next((a for a in self.addresses if a["address"] == target), None)
        if not old:
            raise ValueError("Address not found")
        new_ver = old.get("version", 0) + 1
        # mark old as rotated
        old["rotated"] = True
        entry = self._derive_address(old["index"], version=new_ver)
        self._save()
        print(f"[+] Key rotated  {target[:16]}... → {entry['address'][:16]}...  (v{new_ver})")
        print(f"    Old key still valid for receiving; use new address for sending.")
        return entry["address"]

    def list_addresses(self) -> List[str]:
        self._require_unlocked()
        return [a["address"] for a in self.addresses if not a.get("rotated")]

    @property
    def address(self) -> str:
        active = [a for a in self.addresses if not a.get("rotated")]
        return active[0]["address"] if active else (self.addresses[0]["address"] if self.addresses else "")

    def get_keys(self, address: Optional[str] = None):
        self._require_unlocked()
        target = address or self.address
        for a in self.addresses:
            if a["address"] == target:
                ed_priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(a["ed_secret_key"]))
                return (bytes.fromhex(a["public_key"]), bytes.fromhex(a["secret_key"]),
                        ed_priv, a["ed_public_key"], a.get("version", 0))
        raise ValueError(f"Address {target} not found")

    def create_transaction(self, recipient: str, amount: float, memo: str = "",
                           from_address: Optional[str] = None) -> Transaction:
        self._require_unlocked()
        sender = from_address or self.address
        mldsa_pk, mldsa_sk, ed_priv, ed_pk_hex, ver = self.get_keys(sender)
        tx = Transaction(
            tx_id=str(uuid.uuid4()), sender=sender, recipient=recipient, amount=amount,
            timestamp=time.time(), public_key=mldsa_pk.hex(), ed_public_key=ed_pk_hex,
            signature="", memo=memo, key_version=ver,
        )
        tx.signature = hybrid_sign(ed_priv, mldsa_sk, tx.message_to_sign())
        return tx

    def record_history(self, tx: Transaction, direction: str = "out") -> None:
        self._require_unlocked()
        self.history.append({
            "tx_id": tx.tx_id, "direction": direction,
            "counterparty": tx.recipient if direction == "out" else tx.sender,
            "amount": tx.amount, "memo": tx.memo, "timestamp": tx.timestamp,
            "address": tx.sender if direction == "out" else tx.recipient,
        })
        self._save()

    def show_history(self, limit: int = 20) -> None:
        self._require_unlocked()
        if not self.history:
            print("  (no history yet)")
            return
        for h in reversed(self.history[-limit:]):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["timestamp"]))
            arrow = "→" if h["direction"] == "out" else "←"
            print(f"  {ts}  {arrow}  {h['amount']:>8.2f} VEX  {h['counterparty'][:16]}...")

    def _require_unlocked(self):
        if not self._unlocked:
            raise RuntimeError("Wallet locked")

    @staticmethod
    def _ask_password(create: bool = False) -> str:
        import getpass
        while True:
            p1 = getpass.getpass("  Password: ")
            if len(p1) < 4:
                print("  Too short")
                continue
            if create and getpass.getpass("  Confirm: ") != p1:
                print("  Mismatch")
                continue
            return p1

# ---------------------------------------------------------------------------
# Chain (core unchanged + hybrid verify)
# ---------------------------------------------------------------------------
class VexloreChain:
    def __init__(self):
        self.chain: List[Block] = []
        self.pending: List[Transaction] = []
        self.balances: Dict[str, float] = {}
        self.contracts: Dict[str, Contract] = {}
        self.current_difficulty = INITIAL_DIFFICULTY
        self._load_or_create()

    def _load_or_create(self):
        if CHAIN_FILE.exists():
            try:
                raw = json.loads(CHAIN_FILE.read_text())
                self.chain = [Block.from_dict(b) for b in raw["chain"]]
                self.balances = raw.get("balances", {})
                self.contracts = {cid: Contract.from_dict(c) for cid, c in raw.get("contracts", {}).items()}
                self.current_difficulty = raw.get("difficulty", INITIAL_DIFFICULTY)
                print(f"[+] Loaded {len(self.chain)} blocks (diff={self.current_difficulty}, contracts={len(self.contracts)})")
            except Exception as e:
                print(f"[!] Load failed: {e}")
                self._create_genesis()
        else:
            self._create_genesis()

    def _create_genesis(self):
        print("[*] Creating Genesis ...")
        tx = Transaction(tx_id="genesis", sender="VEXLORE_NETWORK", recipient="VEXLORE_NETWORK",
                         amount=0.0, timestamp=time.time(), public_key="", ed_public_key="",
                         signature="", memo="Genesis v0.5 – hybrid post-quantum")
        block = Block(0, time.time(), [tx], "0"*64, INITIAL_DIFFICULTY, miner="genesis")
        block.hash = block.compute_hash()
        self.chain.append(block)
        self._save()
        print(f"[+] Genesis {block.hash[:16]}...")

    def _atomic_save(self, data: dict):
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, CHAIN_FILE)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _save(self):
        self._atomic_save({"name": CHAIN_NAME, "version": VERSION, "algo": "hybrid-Ed25519+ML-DSA-44 + ML-KEM-512",
                           "difficulty": self.current_difficulty,
                           "chain": [b.to_dict() for b in self.chain], "balances": self.balances,
                           "contracts": {cid: c.to_dict() for cid, c in self.contracts.items()}})

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    def _adjust_difficulty(self) -> int:
        if len(self.chain) < DIFFICULTY_ADJUST_EVERY + 1:
            return self.current_difficulty
        recent = self.chain[-DIFFICULTY_ADJUST_EVERY:]
        taken = recent[-1].timestamp - recent[0].timestamp
        expected = TARGET_BLOCK_TIME * (DIFFICULTY_ADJUST_EVERY - 1)
        d = self.current_difficulty
        if taken < expected * 0.7:
            d = min(MAX_DIFFICULTY, d + 1)
        elif taken > expected * 1.4:
            d = max(MIN_DIFFICULTY, d - 1)
        if d != self.current_difficulty:
            print(f"[*] Difficulty {self.current_difficulty} → {d}")
        return d

    def add_transaction(self, tx: Transaction) -> bool:
        if tx.sender != "VEXLORE_NETWORK" and not tx.verify():
            print("[-] Invalid hybrid signature")
            return False
        if tx.sender != "VEXLORE_NETWORK":
            err = check_send_rules(tx.sender, tx.recipient, tx.amount, tx.memo)
            if err:
                print(f"[-] Send rule: {err}")
                return False
        if tx.sender != "VEXLORE_NETWORK" and self.balances.get(tx.sender, 0) < tx.amount:
            print(f"[-] Insufficient balance")
            return False
        if any(p.tx_id == tx.tx_id for p in self.pending):
            return False
        if len(self.pending) >= MAX_TX_PER_BLOCK * 3:
            print("[-] Mempool full")
            return False
        self.pending.append(tx)
        print(f"[+] Pending {tx.tx_id[:8]}... {tx.amount} VEX → {tx.recipient[:14]}... (mempool {len(self.pending)})")
        return True

    def mine_pending(self, miner_address: str) -> Optional[Block]:
        if not self.pending:
            print("[-] Nothing to mine")
            return None
        txs = self.pending[:MAX_TX_PER_BLOCK]
        remaining = self.pending[MAX_TX_PER_BLOCK:]
        reward = Transaction(tx_id=str(uuid.uuid4()), sender="VEXLORE_NETWORK", recipient=miner_address,
                             amount=10.0, timestamp=time.time(), public_key="", ed_public_key="",
                             signature="", memo="Block reward")
        txs = txs + [reward]
        self.current_difficulty = self._adjust_difficulty()
        block = Block(len(self.chain), time.time(), txs, self.last_block.hash,
                      self.current_difficulty, miner=miner_address)
        print(f"[*] Mining #{block.index} (diff {block.difficulty}) ...")
        t0 = time.time()
        block.mine()
        print(f"[+] Mined in {time.time()-t0:.2f}s  {block.hash[:20]}...")
        for tx in txs:
            if tx.sender != "VEXLORE_NETWORK":
                self.balances[tx.sender] = self.balances.get(tx.sender, 0) - tx.amount
            self.balances[tx.recipient] = self.balances.get(tx.recipient, 0) + tx.amount
        self.chain.append(block)
        self.pending = remaining
        self._save()
        return block

    def get_balance(self, address: str) -> float:
        return self.balances.get(address, 0.0)

    def is_valid(self, chain: Optional[List[Block]] = None) -> bool:
        blocks = chain or self.chain
        if not blocks or blocks[0].index != 0 or blocks[0].previous_hash != "0"*64:
            return False
        for i in range(1, len(blocks)):
            cur, prev = blocks[i], blocks[i-1]
            if cur.index != prev.index+1 or cur.previous_hash != prev.hash:
                return False
            if not cur.hash.startswith("0"*cur.difficulty) or cur.hash != cur.compute_hash():
                return False
            for tx in cur.transactions:
                if tx.sender != "VEXLORE_NETWORK" and not tx.verify():
                    return False
        return True

    def faucet(self, address: str, amount: float = 100.0):
        tx = Transaction(tx_id=str(uuid.uuid4()), sender="VEXLORE_NETWORK", recipient=address,
                         amount=amount, timestamp=time.time(), public_key="", ed_public_key="",
                         signature="", memo="Faucet")
        self.pending.append(tx)
        print(f"[+] Faucet {amount} VEX → {address[:16]}... (mempool {len(self.pending)})")

    def replace_chain(self, new_blocks: List[Block]) -> bool:
        if len(new_blocks) <= len(self.chain) or not self.is_valid(new_blocks):
            return False
        print(f"[+] Adopting longer chain ({len(self.chain)} → {len(new_blocks)})")
        self.chain = new_blocks
        self.balances = {}
        for b in self.chain:
            for tx in b.transactions:
                if tx.sender != "VEXLORE_NETWORK":
                    self.balances[tx.sender] = self.balances.get(tx.sender, 0) - tx.amount
                self.balances[tx.recipient] = self.balances.get(tx.recipient, 0) + tx.amount
        self.pending = []
        self.current_difficulty = self.chain[-1].difficulty
        self._save()
        return True

    def add_block_from_peer(self, block: Block) -> bool:
        if (block.index != len(self.chain) or block.previous_hash != self.last_block.hash or
            block.hash != block.compute_hash() or not block.hash.startswith("0"*block.difficulty)):
            return False
        for tx in block.transactions:
            if tx.sender != "VEXLORE_NETWORK" and not tx.verify():
                return False
        for tx in block.transactions:
            if tx.sender != "VEXLORE_NETWORK":
                self.balances[tx.sender] = self.balances.get(tx.sender, 0) - tx.amount
            self.balances[tx.recipient] = self.balances.get(tx.recipient, 0) + tx.amount
        ids = {t.tx_id for t in block.transactions}
        self.pending = [t for t in self.pending if t.tx_id not in ids]
        self.chain.append(block)
        self.current_difficulty = block.difficulty
        self._save()
        print(f"[+] Accepted block #{block.index} from peer")
        return True

    def scan_history_for(self, addresses: Set[str]) -> List[Dict]:
        found = []
        for b in self.chain:
            for tx in b.transactions:
                if tx.sender in addresses or tx.recipient in addresses:
                    found.append({"block": b.index, "tx_id": tx.tx_id, "sender": tx.sender,
                                  "recipient": tx.recipient, "amount": tx.amount, "timestamp": tx.timestamp})
        return found


    # ---------- v0.9 light contracts ----------
    def create_multisig(self, creator: str, participants: List[str], threshold: int,
                        amount: float, release_to: str = "", memo: str = "") -> Optional[Contract]:
        if creator not in participants:
            participants = [creator] + list(participants)
        participants = list(dict.fromkeys(participants))
        if threshold < 1 or threshold > len(participants):
            print("[-] Invalid threshold (need 1 ≤ M ≤ N)")
            return None
        if self.balances.get(creator, 0) < amount or amount < MIN_SEND_AMOUNT:
            print("[-] Insufficient balance or amount too small")
            return None
        cid = "MS-" + uuid.uuid4().hex[:12]
        self.balances[creator] = self.balances.get(creator, 0) - amount
        c = Contract(
            contract_id=cid, type="multisig", creator=creator, amount=amount,
            participants=participants, threshold=threshold,
            release_to=release_to or creator, created_height=len(self.chain) - 1,
            created_at=time.time(), memo=memo,
        )
        self.contracts[cid] = c
        self._save()
        print(f"[+] Multi-sig {cid}  {threshold}-of-{len(participants)}  locked {amount} VEX")
        return c

    def sign_multisig(self, contract_id: str, signer: str, signature_hex: str) -> bool:
        c = self.contracts.get(contract_id)
        if not c or c.type != "multisig" or c.status != "open":
            print("[-] Not an open multisig")
            return False
        if signer not in c.participants:
            print("[-] Not a participant")
            return False
        c.signatures[signer] = signature_hex
        print(f"[+] Sig recorded ({c.sig_count()}/{c.threshold})")
        if c.sig_count() >= c.threshold:
            dest = c.release_to or c.creator
            self.balances[dest] = self.balances.get(dest, 0) + c.amount
            c.status = "released"
            print(f"[+] RELEASED → {dest[:16]}...  {c.amount} VEX")
        self._save()
        return True

    def create_timelock(self, creator: str, beneficiary: str, amount: float,
                        unlock_height: int = 0, unlock_seconds: float = 0.0,
                        memo: str = "") -> Optional[Contract]:
        if self.balances.get(creator, 0) < amount or amount < MIN_SEND_AMOUNT:
            print("[-] Insufficient balance or amount too small")
            return None
        if unlock_height <= 0 and unlock_seconds <= 0:
            print("[-] Need unlock_height or unlock_seconds")
            return None
        height_now = len(self.chain) - 1
        if unlock_height > 0 and unlock_height <= height_now:
            print("[-] unlock_height must be in the future")
            return None
        cid = "TL-" + uuid.uuid4().hex[:12]
        self.balances[creator] = self.balances.get(creator, 0) - amount
        unlock_time = time.time() + unlock_seconds if unlock_seconds > 0 else 0.0
        c = Contract(
            contract_id=cid, type="timelock", creator=creator, amount=amount,
            beneficiary=beneficiary or creator, unlock_height=unlock_height,
            unlock_time=unlock_time, created_height=height_now,
            created_at=time.time(), memo=memo,
        )
        self.contracts[cid] = c
        self._save()
        bits = []
        if unlock_height:
            bits.append(f"h≥{unlock_height}")
        if unlock_time:
            bits.append(f"t≥{time.strftime('%H:%M:%S', time.localtime(unlock_time))}")
        print(f"[+] Time-lock {cid}  {amount} VEX  ({', '.join(bits)})")
        return c

    def claim_timelock(self, contract_id: str, claimer: str) -> bool:
        c = self.contracts.get(contract_id)
        if not c or c.type != "timelock" or c.status != "open":
            print("[-] Not an open timelock")
            return False
        if claimer not in (c.beneficiary, c.creator):
            print("[-] Only beneficiary/creator can claim")
            return False
        height_now = len(self.chain) - 1
        if not c.is_timelock_ready(height_now, time.time()):
            print("[-] Not ready yet")
            if c.unlock_height:
                print(f"    need height ≥ {c.unlock_height} (now {height_now})")
            if c.unlock_time:
                print(f"    need wait ~{max(0, int(c.unlock_time - time.time()))}s")
            return False
        self.balances[c.beneficiary] = self.balances.get(c.beneficiary, 0) + c.amount
        c.status = "claimed"
        self._save()
        print(f"[+] CLAIMED → {c.beneficiary[:16]}...  {c.amount} VEX")
        return True

    def list_contracts(self, address: Optional[str] = None) -> List[Contract]:
        out = []
        for c in self.contracts.values():
            if address is None or c.creator == address or c.beneficiary == address \
                    or address in c.participants or c.release_to == address:
                out.append(c)
        return out


# ---------------------------------------------------------------------------
# Networking + ML-KEM encrypted messages
# ---------------------------------------------------------------------------
class PeerManager:
    def __init__(self, self_url: str = "", kem_ek: bytes = b""):
        self.self_url = self_url.rstrip("/")
        self.peers: Set[str] = set()
        self.peer_kem: Dict[str, bytes] = {}   # peer_url → ML-KEM encapsulation key
        self.kem_ek = kem_ek
        self._load()

    def _load(self):
        if PEERS_FILE.exists():
            try:
                data = json.loads(PEERS_FILE.read_text())
                self.peers = set(data.get("peers", []))
                self.peer_kem = {k: bytes.fromhex(v) for k, v in data.get("peer_kem", {}).items()}
            except Exception:
                pass

    def _save(self):
        PEERS_FILE.write_text(json.dumps({
            "peers": sorted(self.peers),
            "peer_kem": {k: v.hex() for k, v in self.peer_kem.items()},
            "updated": time.time(),
        }, indent=2))

    def add(self, url: str) -> bool:
        url = url.rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        if url == self.self_url or url in self.peers:
            return False
        self.peers.add(url)
        self._save()
        print(f"[+] Peer added: {url}")
        return True

    def remove(self, url: str) -> bool:
        url = url.rstrip("/")
        if url in self.peers:
            self.peers.discard(url)
            self.peer_kem.pop(url, None)
            self._save()
            return True
        return False

    def list(self) -> List[str]:
        return sorted(self.peers)

    def _encrypt_for_peer(self, peer: str, payload: dict) -> Optional[dict]:
        """ML-KEM encapsulate + Fernet encrypt the JSON payload for a peer."""
        ek = self.peer_kem.get(peer)
        if not ek:
            return None  # fall back to plaintext
        try:
            shared, ct = ML_KEM_512.encaps(ek)
            f = shared_secret_to_fernet(shared)
            plain = json.dumps(payload).encode()
            return {
                "kem_ct": base64.b64encode(ct).decode(),
                "ciphertext": base64.b64encode(f.encrypt(plain)).decode(),
                "vexlore_enc": "mlkem512-fernet",
            }
        except Exception:
            return None

    def broadcast_block(self, block: Block, kem_dk: bytes = b""):
        payload = block.to_dict()
        for peer in list(self.peers):
            try:
                enc = self._encrypt_for_peer(peer, payload)
                body = enc if enc else payload
                r = requests.post(f"{peer}/block", json=body, timeout=6)
                status = "encrypted" if enc else "plain"
                print(f"    → block to {peer} ({status}) [{r.status_code}]")
            except Exception as e:
                print(f"    → {peer} unreachable ({type(e).__name__})")

    def broadcast_tx(self, tx: Transaction):
        payload = tx.to_dict()
        for peer in list(self.peers):
            try:
                enc = self._encrypt_for_peer(peer, payload)
                body = enc if enc else payload
                requests.post(f"{peer}/transaction", json=body, timeout=5)
            except Exception:
                pass

    def fetch_chain(self, peer: str) -> Optional[List[Block]]:
        try:
            r = requests.get(f"{peer}/chain", timeout=8)
            if r.status_code != 200:
                return None
            return [Block.from_dict(b) for b in r.json().get("chain", [])]
        except Exception:
            return None

    def fetch_peers(self, peer: str) -> List[str]:
        try:
            r = requests.get(f"{peer}/peers", timeout=5)
            if r.status_code == 200:
                return r.json().get("peers", [])
        except Exception:
            pass
        return []

    def exchange_kem(self, peer: str, my_ek: bytes):
        """Exchange ML-KEM public keys with a peer."""
        try:
            r = requests.post(f"{peer}/kem", json={"ek": my_ek.hex(), "url": self.self_url}, timeout=5)
            if r.status_code == 200:
                their_ek = bytes.fromhex(r.json().get("ek", ""))
                if their_ek:
                    self.peer_kem[peer] = their_ek
                    self._save()
                    print(f"    ⇄ KEM keys exchanged with {peer}")
        except Exception:
            pass

class NodeHTTPHandler(BaseHTTPRequestHandler):
    chain: VexloreChain
    peers: PeerManager
    kem_ek: bytes
    kem_dk: bytes

    def log_message(self, fmt, *args):
        print(f"  [HTTP] {self.address_string()} {fmt % args}")

    def _json(self, code: int, obj):
        body = json.dumps(obj).encode()
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

    def _explorer_page(self) -> str:
        c = self.chain
        blocks_rows = []
        for b in reversed(c.chain[-25:]):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(b.timestamp)) if b.timestamp else "?"
            miner = (b.miner or "")[:12]
            blocks_rows.append(
                "<tr><td>%d</td><td class='mono'>%s…</td><td>%d</td><td>%d</td>"
                "<td class='mono'>%s…</td><td>%s</td></tr>"
                % (b.index, b.hash[:14], len(b.transactions), b.difficulty, miner, ts)
            )
        bals = sorted(c.balances.items(), key=lambda x: -x[1])[:15]
        bals_rows = "".join(
            "<tr><td class='mono'>%s</td><td class='num'>%.4f</td></tr>" % (a, bal) for a, bal in bals
        ) or "<tr><td colspan=2>no accounts yet</td></tr>"
        contracts = list(c.contracts.values())[-10:]
        c_rows = "".join(
            "<tr><td class='mono'>%s</td><td>%s</td><td>%s</td><td class='num'>%.2f</td></tr>"
            % (x.contract_id, x.type, x.status, x.amount)
            for x in contracts
        ) or "<tr><td colspan=4>no contracts yet</td></tr>"
        return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vexlore Explorer</title>
<style>
:root {{ --bg:#0b0f14; --card:#12181f; --border:#1e2a36; --text:#e8eef4; --muted:#8b9aab;
         --accent:#5b9fd4; --green:#3ecf8e; --purple:#a78bfa; }}
* {{ box-sizing:border-box }}
body {{ margin:0; font-family:ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
header {{ display:flex; align-items:center; gap:1rem; padding:1rem 1.5rem; border-bottom:1px solid var(--border); flex-wrap:wrap; }}
.logo {{ width:42px; height:42px; border-radius:10px; background:linear-gradient(135deg,#5b9fd4,#a78bfa);
         display:flex; align-items:center; justify-content:center; font-weight:800; font-size:1.2rem; color:#0b0f14; }}
h1 {{ margin:0; font-size:1.2rem }} h1 span {{ color:var(--purple) }}
.badge {{ font-size:.72rem; border:1px solid var(--border); background:var(--card); padding:.2rem .55rem; border-radius:999px; color:var(--muted) }}
a {{ color:var(--accent); text-decoration:none }} a:hover {{ text-decoration:underline }}
main {{ max-width:1100px; margin:0 auto; padding:1.25rem }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:.75rem; margin-bottom:1.25rem }}
.stat {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:.9rem }}
.stat .lbl {{ color:var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.05em }}
.stat .val {{ font-size:1.3rem; font-weight:600; color:var(--accent); margin-top:.2rem }}
section {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:1rem; margin-bottom:1rem }}
section h2 {{ margin:0 0 .7rem; font-size:.95rem; color:var(--muted) }}
table {{ width:100%; border-collapse:collapse; font-size:.85rem }}
th,td {{ text-align:left; padding:.4rem; border-bottom:1px solid var(--border) }}
th {{ color:var(--muted); font-size:.72rem; text-transform:uppercase }}
.mono {{ font-family:ui-monospace,monospace; font-size:.78rem }}
.num {{ color:var(--green); font-variant-numeric:tabular-nums }}
footer {{ text-align:center; color:var(--muted); font-size:.75rem; padding:1.5rem }}
</style></head><body>
<header>
  <div class="logo">V</div>
  <div>
    <h1>Vexlore <span>Explorer</span></h1>
    <div style="margin-top:.25rem">
      <span class="badge">{VERSION}</span>
      <span class="badge">ML-KEM · Hybrid PQ</span>
      <a class="badge" href="https://t.me/VexloreBOT" target="_blank" rel="noopener">VexloreBot ↗</a>
    </div>
  </div>
</header>
<main>
  <div class="grid">
    <div class="stat"><div class="lbl">Blocks</div><div class="val">{len(c.chain)}</div></div>
    <div class="stat"><div class="lbl">Difficulty</div><div class="val">{c.current_difficulty}</div></div>
    <div class="stat"><div class="lbl">Mempool</div><div class="val">{len(c.pending)}</div></div>
    <div class="stat"><div class="lbl">Accounts</div><div class="val">{len(c.balances)}</div></div>
    <div class="stat"><div class="lbl">Contracts</div><div class="val">{len(c.contracts)}</div></div>
    <div class="stat"><div class="lbl">Peers</div><div class="val">{len(self.peers.peers)}</div></div>
  </div>
  <section><h2>Recent blocks</h2>
    <table><thead><tr><th>#</th><th>Hash</th><th>Txs</th><th>Diff</th><th>Miner</th><th>Time</th></tr></thead>
    <tbody>{''.join(blocks_rows) or '<tr><td colspan=6>empty</td></tr>'}</tbody></table>
  </section>
  <section><h2>Top balances</h2>
    <table><thead><tr><th>Address</th><th>VEX</th></tr></thead>
    <tbody>{bals_rows}</tbody></table>
  </section>
  <section><h2>Contracts</h2>
    <table><thead><tr><th>ID</th><th>Type</th><th>Status</th><th>Amount</th></tr></thead>
    <tbody>{c_rows}</tbody></table>
  </section>
</main>
<footer>
  Educational only ·
  <a href="/">API</a> ·
  <a href="/status">Status</a> ·
  <a href="https://t.me/VexloreBOT" target="_blank" rel="noopener">VexloreBot</a>
</footer>
</body></html>"""

    def _read(self) -> Optional[Dict]:
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return None
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return None

    def _maybe_decrypt(self, data: dict) -> Optional[dict]:
        """If payload is ML-KEM encrypted, decapsulate and decrypt."""
        if not data or data.get("vexlore_enc") != "mlkem512-fernet":
            return data
        try:
            ct = base64.b64decode(data["kem_ct"])
            shared = ML_KEM_512.decaps(self.kem_dk, ct)
            f = shared_secret_to_fernet(shared)
            plain = f.decrypt(base64.b64decode(data["ciphertext"]))
            return json.loads(plain.decode())
        except Exception as e:
            print(f"  [!] KEM decrypt failed: {e}")
            return None

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self._json(200, {"name": CHAIN_NAME, "version": VERSION, "blocks": len(self.chain.chain),
                             "difficulty": self.chain.current_difficulty, "mempool": len(self.chain.pending),
                             "peers": len(self.peers.peers), "contracts": len(self.chain.contracts),
                             "kem": "ML-KEM-512",
                             "explorer": "/explorer", "vexlorebot": "https://t.me/VexloreBOT"})
        elif path in ("/explorer", "/ui"):
            self._html(200, self._explorer_page())
        elif path == "/chain":
            self._json(200, {"length": len(self.chain.chain), "chain": [b.to_dict() for b in self.chain.chain]})
        elif path == "/status":
            self._json(200, {"version": VERSION, "blocks": len(self.chain.chain),
                             "difficulty": self.chain.current_difficulty, "last_hash": self.chain.last_block.hash,
                             "mempool": len(self.chain.pending), "peers": self.peers.list(),
                             "kem_ek": self.kem_ek.hex()[:32] + "..."})
        elif path == "/peers":
            self._json(200, {"peers": self.peers.list()})
        elif path in ("/pending", "/mempool"):
            self._json(200, {"count": len(self.chain.pending), "pending": [t.to_dict() for t in self.chain.pending]})
        elif path == "/kem":
            self._json(200, {"ek": self.kem_ek.hex(), "algo": "ML-KEM-512"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        data = self._read()
        if path == "/block":
            data = self._maybe_decrypt(data or {})
            if not data:
                self._json(400, {"error": "bad body"})
                return
            try:
                block = Block.from_dict(data)
            except Exception:
                self._json(400, {"error": "invalid block"})
                return
            ok = self.chain.add_block_from_peer(block)
            if ok:
                self.peers.broadcast_block(block)
            self._json(200 if ok else 409, {"status": "accepted" if ok else "rejected"})
        elif path == "/transaction":
            data = self._maybe_decrypt(data or {})
            if not data:
                self._json(400, {"error": "bad body"})
                return
            try:
                tx = Transaction.from_dict(data)
            except Exception:
                self._json(400, {"error": "invalid tx"})
                return
            ok = self.chain.add_transaction(tx)
            self._json(200 if ok else 409, {"status": "ok" if ok else "rejected"})
        elif path == "/peers":
            url = (data or {}).get("url", "")
            if url:
                self.peers.add(url)
                self._json(200, {"status": "added", "peers": self.peers.list()})
            else:
                self._json(400, {"error": "url required"})
        elif path == "/kem":
            # peer is sending us their ek; reply with ours
            their_ek_hex = (data or {}).get("ek", "")
            their_url = (data or {}).get("url", "")
            if their_ek_hex and their_url:
                self.peers.peer_kem[their_url.rstrip("/")] = bytes.fromhex(their_ek_hex)
                self.peers.add(their_url)
                self.peers._save()
            self._json(200, {"ek": self.kem_ek.hex(), "algo": "ML-KEM-512"})
        else:
            self._json(404, {"error": "not found"})

class NodeServer:
    def __init__(self, chain: VexloreChain, port: int = DEFAULT_PORT, host: str = "0.0.0.0"):
        self.chain = chain
        self.port = port
        self.host = host
        # generate long-lived ML-KEM keypair for this node
        self.kem_ek, self.kem_dk = ML_KEM_512.keygen()
        local_ip = self._guess_ip()
        self.self_url = f"http://{local_ip}:{port}"
        self.peers = PeerManager(self.self_url, self.kem_ek)
        self._server = None
        self._stop = threading.Event()

    @staticmethod
    def _guess_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def start(self):
        handler = type("H", (NodeHTTPHandler,), {
            "chain": self.chain, "peers": self.peers,
            "kem_ek": self.kem_ek, "kem_dk": self.kem_dk,
        })
        self._server = HTTPServer((self.host, self.port), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        print(f"[+] Node on http://{self.host}:{self.port}")
        print(f"    Self URL  : {self.self_url}")
        print(f"    Explorer  : {self.self_url}/explorer")
        print(f"    VexloreBot: https://t.me/VexloreBOT")
        print(f"    KEM       : ML-KEM-512 (ek {len(self.kem_ek)} bytes)")
        threading.Thread(target=self._sync_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._server:
            self._server.shutdown()

    def _sync_loop(self):
        while not self._stop.is_set():
            self.sync_with_peers()
            self._stop.wait(SYNC_INTERVAL)

    def sync_with_peers(self):
        if not self.peers.peers:
            return
        best, best_len = None, len(self.chain.chain)
        for peer in list(self.peers.peers):
            remote = self.peers.fetch_chain(peer)
            if remote and len(remote) > best_len and self.chain.is_valid(remote):
                best, best_len = remote, len(remote)
            for p in self.peers.fetch_peers(peer):
                self.peers.add(p)
            try:
                requests.post(f"{peer}/peers", json={"url": self.self_url}, timeout=4)
            except Exception:
                pass
            # exchange KEM keys if we don't have theirs yet
            if peer not in self.peers.peer_kem:
                self.peers.exchange_kem(peer, self.kem_ek)
        if best:
            self.chain.replace_chain(best)

    def add_peer(self, url: str):
        if self.peers.add(url):
            try:
                requests.post(f"{url.rstrip('/')}/peers", json={"url": self.self_url}, timeout=5)
            except Exception as e:
                print(f"    (handshake: {e})")
            self.peers.exchange_kem(url.rstrip("/"), self.kem_ek)
            self.sync_with_peers()

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def print_banner():
    print(r"""
 __     __        _                 
 \ \   / /____  _| | ___  _ __ ___  
  \ \ / / _ \ \/ / |/ _ \| '__/ _ \ 
   \ V /  __/>  <| | (_) | | |  __/ 
    \_/ \___/_/\_\_|\___/|_|  \___| 
                                    
  Quantumproof Chain  v0.9  — CONTRACTS + EXPLORER
  Multi-sig • Time-locks • Send rules • Vexlore Explorer • VexloreBot
""")

def main():
    print_banner()
    chain = VexloreChain()
    wallet = None
    if (WALLETS_DIR / "alice.json").exists():
        print("[*] Found wallet 'alice'")
        import getpass
        pw = getpass.getpass("  Password (Enter to skip): ")
        if pw:
            wallet = Wallet("alice", password=pw)
            if not wallet._unlocked:
                wallet = None
    if not wallet:
        print("[*] Use option 1 to create a wallet")

    node = None
    try:
        node = NodeServer(chain)
        node.start()
    except OSError as e:
        print(f"[!] Port {DEFAULT_PORT} busy: {e}")
        node = None

    while True:
        n_addr = len(wallet.list_addresses()) if wallet and wallet._unlocked else 0
        print(f"""
Commands:
  1) New / Restore wallet     2) Unlock wallet
  3) Show balance             4) Faucet
  5) Send transaction         6) Mine block
  7) Show chain               8) Validate chain
  9) List addresses           10) New address
  11) History                 12) Rotate key
  13) Lock wallet             14) Quit

Network:
  15) List peers              16) Add peer
  17) Remove peer             18) Sync now
  19) Node status             20) Start node (custom port)

Contracts & Explorer (v0.9):
  21) Multi-sig vault         22) Sign multi-sig
  23) Time-lock               24) Claim time-lock
  25) List contracts          26) Open explorer
  27) Send rules

{len(chain.chain)} blocks | diff {chain.current_difficulty} | mempool {len(chain.pending)} | contracts {len(chain.contracts)} | addrs {n_addr}
""")
        c = input("Vexlore> ").strip()
        if c == "1":
            name = input("Name [alice]: ").strip() or "alice"
            mode = input("(n)ew / (r)estore [n]: ").strip().lower() or "n"
            import getpass
            if mode.startswith("r"):
                mn = input("12-word seed: ").strip()
                pw = getpass.getpass("New password: ")
                try:
                    wallet = Wallet.restore(name, mn, pw)
                except ValueError as e:
                    print(f"[-] {e}")
            else:
                pw = getpass.getpass("Password: ")
                wallet = Wallet(name, password=pw)
        elif c == "2":
            name = input("Name [alice]: ").strip() or "alice"
            import getpass
            wallet = Wallet(name, password=getpass.getpass("Password: "))
        elif c == "3":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            for a in wallet.addresses:
                flag = " (rotated)" if a.get("rotated") else ""
                print(f"  #{a['index']} v{a.get('version',0)}  {a['address']}  {chain.get_balance(a['address']):.2f} VEX{flag}")
            total = sum(chain.get_balance(a["address"]) for a in wallet.addresses)
            print(f"  Total: {total:.2f} VEX")
        elif c == "4":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            amt = float(input("Amount [100]: ") or 100)
            chain.faucet(wallet.address, amt)
            print("Mine (6) to receive")
        elif c == "5":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            to = input("To: ").strip()
            amt = float(input("Amount: "))
            memo = input("Memo: ").strip()
            frm = input(f"From [{wallet.address}]: ").strip() or wallet.address
            try:
                tx = wallet.create_transaction(to, amt, memo, frm)
                if chain.add_transaction(tx):
                    wallet.record_history(tx, "out")
                    if node:
                        node.peers.broadcast_tx(tx)
            except Exception as e:
                print(f"[-] {e}")
        elif c == "6":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            block = chain.mine_pending(wallet.address)
            if block:
                for tx in block.transactions:
                    if tx.recipient in wallet.list_addresses() and tx.sender != "VEXLORE_NETWORK":
                        wallet.record_history(tx, "in")
                print(f"Balance: {chain.get_balance(wallet.address)} VEX")
                if node:
                    node.peers.broadcast_block(block)
        elif c == "7":
            print(f"\n=== {CHAIN_NAME} ({len(chain.chain)} blocks) ===")
            for b in chain.chain:
                print(f"\n#{b.index}  {b.hash[:18]}...  diff={b.difficulty}  miner={b.miner[:12]}")
                for t in b.transactions:
                    print(f"  {t.amount} VEX  {t.sender[:12]} → {t.recipient[:12]}")
        elif c == "8":
            t0 = time.time()
            print(f"Valid: {chain.is_valid()}  ({time.time()-t0:.3f}s)")
        elif c == "9":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            for a in wallet.addresses:
                flag = " [rotated]" if a.get("rotated") else ""
                print(f"  #{a['index']} v{a.get('version',0)}  {a['address']}{flag}")
        elif c == "10":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            wallet.new_address()
        elif c == "11":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            wallet.show_history()
        elif c == "12":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            addr = input(f"Address to rotate [{wallet.address}]: ").strip() or wallet.address
            try:
                wallet.rotate_key(addr)
            except Exception as e:
                print(f"[-] {e}")
        elif c == "13":
            if wallet and wallet._unlocked:
                wallet.lock(); wallet = None
            else:
                print("[-] Nothing to lock")
        elif c in ("14", "q", "quit", "exit"):
            if node:
                node.stop()
            print("Bye from Vexlore v0.9")
            break
        elif c == "15":
            if not node:
                print("[-] No node"); continue
            for p in node.peers.list():
                kem = "KEM✓" if p in node.peers.peer_kem else "plain"
                print(f"  • {p}  [{kem}]")
        elif c == "16":
            if not node:
                print("[-] Start node first"); continue
            url = input("Peer URL: ").strip()
            if url:
                node.add_peer(url)
        elif c == "17":
            if not node:
                print("[-] No node"); continue
            node.peers.remove(input("URL: ").strip())
        elif c == "18":
            if not node:
                print("[-] No node"); continue
            node.sync_with_peers()
            print(f"[+] Chain length {len(chain.chain)}")
        elif c == "19":
            if not node:
                print("[-] No node"); continue
            print(f"Self     : {node.self_url}")
            print(f"Blocks   : {len(chain.chain)}")
            print(f"Diff     : {chain.current_difficulty}")
            print(f"Mempool  : {len(chain.pending)}")
            print(f"Peers    : {len(node.peers.peers)}")
            print(f"KEM peers: {len(node.peers.peer_kem)}")
            print(f"Version  : {VERSION}")
        elif c == "20":
            if node:
                print(f"[!] Already on {node.port}"); continue
            try:
                port = int(input(f"Port [{DEFAULT_PORT}]: ") or DEFAULT_PORT)
                node = NodeServer(chain, port=port)
                node.start()
            except Exception as e:
                print(f"[-] {e}"); node = None
        elif c == "21":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            print("--- Multi-sig vault ---")
            raw = input("Other participants (comma VEXQ addrs, or empty): ").strip()
            others = [a.strip() for a in raw.split(",") if a.strip()]
            try:
                threshold = int(input("Threshold M: ").strip())
                amount = float(input("Amount to lock: ").strip())
            except ValueError:
                print("[-] Bad number"); continue
            release_to = input(f"Release to [{wallet.address}]: ").strip() or wallet.address
            memo = input("Memo: ").strip()
            chain.create_multisig(wallet.address, others, threshold, amount, release_to, memo)
        elif c == "22":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            cid = input("Contract id (MS-...): ").strip()
            cobj = chain.contracts.get(cid)
            if not cobj or cobj.type != "multisig":
                print("[-] Not multisig"); continue
            print(f"  {cobj.threshold}-of-{len(cobj.participants)} locked={cobj.amount} sigs={cobj.sig_count()}/{cobj.threshold}")
            msg = f"RELEASE:{cid}:{cobj.amount}:{cobj.release_to}".encode()
            # sign with hybrid keys via wallet get_keys
            try:
                mldsa_pk, mldsa_sk, ed_priv, ed_pk_hex, ver = wallet.get_keys(wallet.address)
                from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed
                # simple sig: hybrid of release message
                sig = hybrid_sign(ed_priv, mldsa_sk, msg)
                chain.sign_multisig(cid, wallet.address, sig)
            except Exception as e:
                print(f"[-] {e}")
        elif c == "23":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            print("--- Time-lock ---")
            beneficiary = input(f"Beneficiary [{wallet.address}]: ").strip() or wallet.address
            try:
                amount = float(input("Amount: ").strip())
            except ValueError:
                print("[-] Bad amount"); continue
            mode = input("Unlock by (h)eight or (s)econds? [s]: ").strip().lower() or "s"
            uh, us = 0, 0.0
            if mode.startswith("h"):
                try:
                    uh = int(input(f"Height (now {len(chain.chain)-1}): ").strip())
                except ValueError:
                    print("[-] Bad"); continue
            else:
                try:
                    us = float(input("Seconds: ").strip())
                except ValueError:
                    print("[-] Bad"); continue
            memo = input("Memo: ").strip()
            chain.create_timelock(wallet.address, beneficiary, amount, uh, us, memo)
        elif c == "24":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock first"); continue
            chain.claim_timelock(input("Contract id (TL-...): ").strip(), wallet.address)
        elif c == "25":
            contracts = chain.list_contracts()
            if not contracts:
                print("No contracts")
            else:
                for x in contracts:
                    if x.type == "multisig":
                        info = f"{x.threshold}-of-{len(x.participants)} sigs={x.sig_count()}"
                    else:
                        parts = []
                        if x.unlock_height:
                            parts.append(f"h≥{x.unlock_height}")
                        if x.unlock_time:
                            left = int(x.unlock_time - time.time())
                            parts.append("ready" if left <= 0 else f"{left}s")
                        info = " ".join(parts)
                    print(f"  {x.contract_id}  {x.type:8} {x.status:10} {x.amount:8.2f}  {info}")
        elif c == "26":
            if not node:
                print("[-] Node not running")
            else:
                url = f"{node.self_url}/explorer"
                print(f"[+] Explorer → {url}")
                print("    VexloreBot → https://t.me/VexloreBOT")
                try:
                    import webbrowser
                    webbrowser.open(url)
                except Exception:
                    pass
        elif c == "27":
            print(f"""
  Send rules
  ──────────
  MIN_SEND_AMOUNT : {MIN_SEND_AMOUNT} VEX
  MAX_MEMO_LEN    : {MAX_MEMO_LEN}
  ALLOW_SELF_SEND : {ALLOW_SELF_SEND}
  Address prefix  : {ADDR_PREFIX}…

  Explorer : option 26  or  http://127.0.0.1:5000/explorer
  Bot      : https://t.me/VexloreBOT
""")
        else:
            print("Unknown")

if __name__ == "__main__":
    main()
