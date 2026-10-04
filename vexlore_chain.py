#!/usr/bin/env python3
"""
Vexlore Quantumproof Chain  v0.4 — WALLET UPGRADES
A free educational post-quantum blockchain prototype.

Uses ML-DSA (FIPS 204 / Dilithium) for quantum-resistant signatures.
v0.4: seed phrase backup, encrypted wallet files, multiple addresses,
       transaction history, fast balance checks.

Not production-ready — for learning and experimentation only.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, urlsplit, urlunsplit

try:
    import requests
except ImportError:
    print("[-] 'requests' package required:  pip install requests")
    sys.exit(1)

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
except ImportError:
    print("[-] 'cryptography' package required:  pip install cryptography")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent / "dilithium_src"))
try:
    from dilithium_py.ml_dsa import ML_DSA_44  # type: ignore
except ImportError:
    print("[-] ML-DSA dependency not found.")
    print("    Install project dependencies with: python -m pip install -r requirements.txt")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants  (v0.4)
# ---------------------------------------------------------------------------
CHAIN_NAME = "Vexlore Quantumproof Chain"
VERSION = "0.4.0-wallet-upgrades"

INITIAL_DIFFICULTY = 3
TARGET_BLOCK_TIME = 20
DIFFICULTY_ADJUST_EVERY = 5
MIN_DIFFICULTY = 2
MAX_DIFFICULTY = 6
MAX_TX_PER_BLOCK = 50
BLOCK_REWARD = 10.0
GENESIS_TIMESTAMP = 0.0
DEFAULT_PORT = 5000
SYNC_INTERVAL = 15
MNEMONIC_WORDS = 12
PBKDF2_ITERATIONS = 100_000

DATA_DIR = Path(__file__).parent / "data"
CHAIN_FILE = DATA_DIR / "vexlore_chain.json"
PEERS_FILE = DATA_DIR / "peers.json"
WALLETS_DIR = Path(__file__).parent / "wallet"
DATA_DIR.mkdir(exist_ok=True)
WALLETS_DIR.mkdir(exist_ok=True)

# BIP-39 English wordlist (2048 words)
BIP39_WORDLIST = """
abandon ability able about above absent absorb abstract absurd abuse access
accident account accuse achieve acid acoustic acquire across act action actor
actress actual adapt add addict address adjust admit adult advance advice
aerobic affair afford afraid again age agent agree ahead aim air airport
aisle alarm album alcohol alert alien all alley allow almost alone alpha
already also alter always amateur amazing among amount amused analyst anchor
ancient anger angle angry animal ankle announce annual another answer antenna
antique anxiety any apart apology appear apple approve april arch arctic
area arena argue arm armed armor army around arrange arrest arrive arrow
art artefact artist artwork ask aspect assault asset assist assume asthma
athlete atom attack attend attitude attract auction audit august aunt author
auto autumn average avocado avoid awake aware away awesome awful awkward
axis baby bachelor bacon badge bag balance balcony ball bamboo banana banner
bar barely bargain barrel base basic basket battle beach bean beauty because
become beef before begin behave behind believe below belt bench benefit best
betray better between beyond bicycle bid bike bind biology bird birth bitter
black blade blame blanket blast bleak bless blind blood blossom blouse blue
blur blush board boat body boil bomb bone bonus book boost border boring
borrow boss bottom bounce box boy bracket brain brand brass brave bread
breeze brick bridge brief bright bring brisk broccoli broken bronze broom
brother brown brush bubble buddy budget buffalo build bulb bulk bullet bundle
bunker burden burger burst bus business busy butter buyer buzz cabbage cabin
cable cactus cage cake call calm camera camp can canal cancel candy cannon
canoe canvas canyon capable capital captain car carbon card cargo carpet carry
cart case cash casino castle casual cat catalog catch category cattle caught
cause caution cave ceiling celery cement census century cereal certain chair
chalk champion change chaos chapter charge chase chat cheap check cheese chef
cherry chest chicken chief child chimney choice choose chronic chuckle chunk
churn cigar cinnamon circle citizen city civil claim clap clarify claw clay
clean clerk clever click client cliff climb clinic clip clock clog close
cloth cloud clown club clump cluster clutch coach coast coconut code coffee
coil coin collect color column combine come comfort comic common company
concert conduct confirm congress connect consider control convince cook cool
copper copy coral core corn correct cost cotton couch country couple course
cousin cover coyote crack cradle craft cram crane crash crater crawl crazy
cream credit creek crew cricket crime crisp critic crop cross crouch crowd
crucial cruel cruise crumble crunch crush cry crystal cube culture cup cupboard
curious current curtain curve cushion custom cute cycle dad damage damp dance
danger daring dash daughter dawn day deal debate debris decade december decide
decline decorate decrease deer defense define defy degree delay deliver demand
demise denial dentist deny depart depend deposit depth deputy derive describe
desert design desk despair destroy detail detect develop device devote diagram
dial diamond diary dice diesel diet differ digital dignity dilemma dinner
dinosaur direct dirt disagree discover disease dish dismiss disorder display
distance divert divide divorce dizzy doctor document dog doll dolphin domain
donate donkey donor door dose double dove draft dragon drama drastic draw
dream dress drift drill drink drip drive drop drum dry duck dumb dune during
dust dutch duty dwarf dynamic eager eagle early earn earth easily east easy
echo ecology economy edge edit educate effort egg eight either elbow elder
electric elegant element elephant elevator elite else embark embody embrace
emerge emotion employ empower empty enable enact end endless endorse enemy
energy enforce engage engine enhance enjoy enlist enough enrich enroll ensure
enter entire entry envelope episode equal equip era erase erode erosion error
erupt escape essay essence estate eternal ethics evidence evil evoke evolve
exact example excess exchange excite exclude excuse execute exercise exhaust
exhibit exile exist exit exotic expand expect expire explain expose express
extend extra eye eyebrow fabric face faculty fade faint faith fall false
fame family famous fan fancy fantasy farm fashion fat fatal father fatigue
fault favorite feature february federal fee feed feel female fence festival
fetch fever few fiber fiction field figure file film filter final find fine
finger finish fire firm first fiscal fish fit fitness fix flag flame flash
flat flavor flee flight flip float flock floor flower fluid flush fly foam
focus fog foil fold follow food foot force forest forget fork fortune forum
forward fossil foster found fox fragile frame frequent fresh friend fringe
frog front frost frown frozen fruit fuel fun funny furnace fury future gadget
gain galaxy gallery game gap garage garbage garden garlic garment gas gasp
gate gather gauge gaze general genius genre gentle genuine gesture ghost giant
gift giggle ginger giraffe girl give glad glance glare glass glide glimpse
globe gloom glory glove glow glue goat goddess gold good goose gorilla gospel
gossip govern gown grab grace grain grant grape grass gravity great green
grid grief grit grocery group grow grunt guard guess guide guilt guitar gun
gym habit hair half hammer hamster hand happy harbor hard harsh harvest hat
have hawk hazard head health heart heavy hedgehog height hello helmet help
hen hero hidden high hill hint hip hire history hobby hockey hold hole holiday
hollow home honey hood hope horn horror horse hospital host hotel hour hover
hub huge human humble humor hundred hungry hunt hurdle hurry hurt husband
hybrid ice icon idea identify idle ignore ill illegal illness image imitate
immense immune impact impose improve impulse inch include income increase
index indicate indoor industry infant inflict inform inhale inherit initial
inject injury inmate inner innocent input inquiry insane insect inside inspire
install intact interest into invest invite involve iron island isolate issue
item ivory jacket jaguar jar jazz jealous jeans jelly jewel job join joke
journey joy judge juice jump jungle junior junk just kangaroo keen keep ketchup
key kick kid kidney kind kingdom kiss kit kitchen kite kitten kiwi knee knife
knock know lab label labor ladder lady lake lamp language laptop large later
latin laugh laundry lava law lawn lawsuit layer lazy leader leaf learn leave
lecture left leg legal legend leisure lemon lend length lens leopard lesson
letter level liar liberty library license life lift light like limb limit
link lion liquid list little live lizard load loan lobster local lock logic
lonely long loop lottery loud lounge love loyal lucky luggage lumber lunar
lunch luxury lyrics machine mad magic magnet maid mail main major make mammal
man manage mandate mango mansion manual maple marble march margin marine market
marriage mask mass master match material math matrix matter maximum maze
meadow mean measure meat mechanic medal media melody melt member memory mention
menu mercy merge merit merry mesh message metal method middle midnight milk
million mimic mind minimum minor minute miracle mirror misery miss mistake
mix mixed mixture mobile model modify mom moment monitor monkey monster month
moon moral more morning mosquito mother motion motor mountain mouse move movie
much muffin mule multiply muscle museum mushroom music must mutual myself mystery
myth naive name napkin narrow nasty nation nature near neck need negative
neglect neither nephew nerve nest net network neutral never news next nice
night noble noise nominee noodle normal north nose notable note nothing notice
novel now nuclear number nurse nut oak obey object oblige obscure observe
obtain obvious occur ocean october odor off offer office often oil okay old
olive olympic omit once one onion online only open opera opinion oppose option
orange orbit orchard order ordinary organ orient original orphan ostrich other
outdoor outer output outside oval oven over own owner oxygen oyster ozone
pact paddle page pair palace palm panda panel panic panther paper parade
parent park parrot party pass patch path patient patrol pattern pause pave
payment peace peanut pear peasant pelican pen penalty pencil people pepper
perfect permit person pet phone photo phrase physical piano picnic picture
piece pig pigeon pill pilot pink pioneer pipe pistol pitch pizza place planet
plastic plate play please pledge pluck plug plunge poem poet point polar pole
police pond pony pool popular portion position possible post potato pottery
poverty powder power practice praise predict prefer prepare present pretty
prevent price pride primary print priority prison private prize problem process
produce profit program project promote proof property prosper protect proud
provide public pudding pull pulp pulse pumpkin punch pupil puppy purchase purity
purpose purse push put puzzle pyramid quality quantum quarter question quick
quit quiz quote rabbit raccoon race rack radar radio rail rain raise rally
ramp ranch random range rapid rare rate rather raven raw razor ready real
reason rebel rebuild recall receive recipe record recycle reduce reflect reform
refuse region regret regular reject relax release relief rely remain remember
remind remove render renew rent reopen repair repeat replace report require
rescue resemble resist resource response result retire retreat return reunion
reveal review reward rhythm rib ribbon rice rich ride ridge rifle right rigid
ring riot ripple risk ritual rival river road roast robot robust rocket romance
roof rookie room rose rotate rough round route royal rubber rude rug rule
run runway rural sad saddle sadness safe sail salad salmon salon salt salute
same sample sand satisfy satoshi sauce sausage save say scale scan scare scatter
scene scheme school science scissors scorpion scream screen screw script scrub
sea search season seat second secret section security seed seek segment select
sell seminar senior sense sentence series service session settle setup seven
shadow shaft shallow share shed shell sheriff shield shift shine ship shiver
shock shoe shoot shop shore short shoulder shove shrimp shrug shuffle shy
sibling sick side siege sight sign silent silk silly silver similar simple
since sing siren sister situate six size skate sketch ski skill skin skirt
skull slab slam sleep slender slice slide slight slim slogan slot slow slush
small smart smile smoke smooth snack snake snap sniff snow soap soccer social
sock soda soft solar soldier solid solution solve someone song soon sorry
sort soul sound soup source south space spare spatial spawn speak special
speed spell spend sphere spice spider spike spin spirit split spoil sponsor
spoon sport spot spray spread spring spy square squeeze squirrel stable stadium
staff stage stairs stamp stand start state stay steak steel stem step stereo
stick still sting stock stomach stone stool story stove strategy street strike
strong struggle student stuff stumble style subject submit subway success such
sudden suffer sugar suggest suit summer sun sunny sunset super supply supreme
sure surface surge surprise surround survey suspect sustain swallow swamp swap
swarm swear sweet swift swim swing switch sword symbol symptom syrup system
table tackle tag tail talent talk tank tape target task taste tattoo taxi
teach team tell ten tenant tennis tent term test text thank that the their
them then theory there they thing this thought three thrive throw thumb thunder
ticket tide tiger tilt timber time tiny tip tired tissue title toast tobacco
today toddler toe together toilet token tomato tomorrow tone tongue tonight
tool tooth top topic topple torch tornado tortoise toss total tourist toward
tower town toy track trade traffic tragic train transfer trap trash travel
tray treat tree trend trial tribe trick trigger trim trip trophy trouble truck
true truly trumpet trust truth try tube tuition tumble tuna tunnel turkey
turn turtle twelve twenty twice twin twist two type typical ugly umbrella
unable unaware uncle uncover under undo unfair unfold unhappy unique unit
universe unknown unlock until unusual unveil update upgrade uphold upon upper
upset urban urge usage use used useful useless usual utility vacant vacuum
vague valid valley valve van vanish vapor various vast vault vehicle velvet
vendor venture venue verb verify version very vessel veteran viable vibrant
vicious victory video view village vintage violin virtual virus visa visit
visual vital vivid vocal voice void volcano volume vote voyage wage wagon
wait walk wall walnut want warfare warm warrior wash wasp waste water wave
way wealth weapon wear weasel weather web wedding weekend weird welcome west
wet whale what wheat wheel when where whip whisper wide width wife wild will
win window wine wing wink winner winter wire wisdom wise wish witness wolf
woman wonder wood wool word work world worry worth wrap wreck wrestle wrist
write wrong yard year yellow you young youth zebra zero zone zoo
""".split()

def pq_keygen():
    return ML_DSA_44.keygen()

def pq_keygen_from_seed(zeta: bytes):
    if len(zeta) != 32:
        zeta = hashlib.sha256(zeta).digest()
    return ML_DSA_44._keygen_internal(zeta)

def pq_sign(secret_key: bytes, message: bytes) -> bytes:
    return ML_DSA_44.sign(secret_key, message)

def pq_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    return ML_DSA_44.verify(public_key, message, signature)

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def address_from_pubkey(pubkey: bytes) -> str:
    return "VEX" + sha256(pubkey)[:20]

def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))

def encrypt_blob(data: bytes, password: str) -> dict:
    salt = secrets.token_bytes(16)
    f = Fernet(_derive_fernet_key(password, salt))
    ct = f.encrypt(data)
    return {"salt": base64.b64encode(salt).decode(), "ciphertext": base64.b64encode(ct).decode(),
            "kdf": "pbkdf2-sha256", "iterations": PBKDF2_ITERATIONS}

def decrypt_blob(enc: dict, password: str) -> bytes:
    salt = base64.b64decode(enc["salt"])
    ct = base64.b64decode(enc["ciphertext"])
    f = Fernet(_derive_fernet_key(password, salt))
    return f.decrypt(ct)

def generate_mnemonic(strength_bits: int = 128) -> str:
    entropy = secrets.token_bytes(16)
    h = hashlib.sha256(entropy).digest()
    checksum_bits = bin(h[0])[2:].zfill(8)[:4]
    entropy_bits = "".join(bin(b)[2:].zfill(8) for b in entropy)
    bits = entropy_bits + checksum_bits
    words = [BIP39_WORDLIST[int(bits[i:i+11], 2)] for i in range(0, 132, 11)]
    return " ".join(words)

def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    mnemonic_norm = " ".join(mnemonic.strip().lower().split())
    salt = ("mnemonic" + passphrase).encode("utf-8")
    seed = hashlib.pbkdf2_hmac("sha512", mnemonic_norm.encode("utf-8"), salt, 2048, dklen=64)
    return seed[:32]

def validate_mnemonic(mnemonic: str) -> bool:
    words = mnemonic.strip().lower().split()
    if len(words) != MNEMONIC_WORDS or not all(w in BIP39_WORDLIST for w in words):
        return False
    bits = "".join(bin(BIP39_WORDLIST.index(w))[2:].zfill(11) for w in words)
    entropy = int(bits[:128], 2).to_bytes(16, "big")
    expected = bin(hashlib.sha256(entropy).digest()[0])[2:].zfill(8)[:4]
    return bits[128:] == expected

@dataclass
class Transaction:
    tx_id: str
    sender: str
    recipient: str
    amount: float
    timestamp: float
    public_key: str
    signature: str
    memo: str = ""

    def message_to_sign(self) -> bytes:
        payload = {"tx_id": self.tx_id, "sender": self.sender, "recipient": self.recipient,
                   "amount": self.amount, "timestamp": self.timestamp, "memo": self.memo}
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Transaction":
        return cls(**d)

    def verify(self) -> bool:
        try:
            public_key = bytes.fromhex(self.public_key)
            if address_from_pubkey(public_key) != self.sender:
                return False
            return pq_verify(public_key, self.message_to_sign(), bytes.fromhex(self.signature))
        except Exception:
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
        block_string = json.dumps({"index": self.index, "timestamp": self.timestamp,
            "transactions": tx_data, "previous_hash": self.previous_hash,
            "difficulty": self.difficulty, "nonce": self.nonce, "miner": self.miner},
            sort_keys=True, separators=(",", ":"))
        return sha256(block_string.encode())

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


def canonical_genesis_block() -> Block:
    transaction = Transaction(
        tx_id="genesis",
        sender="VEXLORE_NETWORK",
        recipient="VEXLORE_NETWORK",
        amount=0.0,
        timestamp=GENESIS_TIMESTAMP,
        public_key="",
        signature="",
        memo="Genesis of Vexlore – Quantumproof by design",
    )
    block = Block(
        index=0,
        timestamp=GENESIS_TIMESTAMP,
        transactions=[transaction],
        previous_hash="0" * 64,
        difficulty=INITIAL_DIFFICULTY,
        miner="genesis",
    )
    block.hash = block.compute_hash()
    return block


class Wallet:
    def __init__(self, name: str = "default", password: Optional[str] = None):
        self.name = name
        self.path = WALLETS_DIR / f"{name}.json"
        self.master_seed: bytes = b""
        self.mnemonic: str = ""
        self.addresses: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self._password: Optional[str] = password
        self._unlocked = False
        if self.path.exists():
            if password is None:
                print(f"[!] Wallet '{name}' is encrypted. Call unlock(password) first.")
                return
            self.unlock(password)
        else:
            if password is None:
                password = self._ask_password(create=True)
            self._create_new(password)

    def _create_new(self, password: str) -> None:
        print(f"[*] Creating new quantum-resistant wallet '{self.name}' ...")
        self.mnemonic = generate_mnemonic()
        self.master_seed = mnemonic_to_seed(self.mnemonic)
        self._password = password
        self._derive_address(0)
        self._unlocked = True
        self._save()
        print(f"[+] Wallet ready")
        print(f"    Primary address : {self.address}")
        print(f"    Addresses       : {len(self.addresses)}")
        print()
        print("  ╔══════════════════════════════════════════════════════════╗")
        print("  ║  WRITE DOWN YOUR SEED PHRASE AND KEEP IT SAFE!           ║")
        print("  ║  Anyone with these words can spend your coins.             ║")
        print("  ╚══════════════════════════════════════════════════════════╝")
        print(f"\n  {self.mnemonic}\n")
        print("  (This phrase will NOT be shown again. Store it offline.)\n")

    @classmethod
    def restore(cls, name: str, mnemonic: str, password: str) -> "Wallet":
        mnemonic = " ".join(mnemonic.strip().lower().split())
        if not validate_mnemonic(mnemonic):
            raise ValueError("Invalid mnemonic (checksum failed or unknown words)")
        w = cls.__new__(cls)
        w.name = name
        w.path = WALLETS_DIR / f"{name}.json"
        w.mnemonic = mnemonic
        w.master_seed = mnemonic_to_seed(mnemonic)
        w.addresses = []
        w.history = []
        w._password = password
        w._unlocked = True
        w._derive_address(0)
        w._save()
        print(f"[+] Wallet '{name}' restored from seed phrase")
        print(f"    Primary address : {w.address}")
        return w

    def unlock(self, password: str) -> bool:
        if not self.path.exists():
            print("[-] Wallet file not found")
            return False
        try:
            raw = json.loads(self.path.read_text())
            plain = decrypt_blob(raw["encrypted"], password)
            data = json.loads(plain.decode())
            self.master_seed = bytes.fromhex(data["master_seed"])
            self.addresses = data.get("addresses", [])
            self.history = data.get("history", [])
            self._password = password
            self._unlocked = True
            if not self.addresses:
                self._derive_address(0)
                self._save()
            print(f"[+] Unlocked wallet '{self.name}' → {self.address}")
            return True
        except (InvalidToken, KeyError, ValueError, json.JSONDecodeError) as e:
            print(f"[-] Wrong password or corrupted wallet: {e}")
            self._unlocked = False
            return False

    def _save(self) -> None:
        if not self._unlocked or self._password is None:
            raise RuntimeError("Wallet is locked – cannot save")
        data = {"master_seed": self.master_seed.hex(), "addresses": self.addresses,
                "history": self.history[-500:], "version": VERSION, "algo": "ML-DSA-44", "created": time.time()}
        blob = json.dumps(data).encode()
        enc = encrypt_blob(blob, self._password)
        out = {"name": self.name, "encrypted": enc, "address_count": len(self.addresses),
               "primary_address": self.address if self.addresses else "", "version": VERSION}
        self.path.write_text(json.dumps(out, indent=2))

    def lock(self) -> None:
        self.master_seed = b""
        self.addresses = []
        self.history = []
        self._password = None
        self._unlocked = False
        print(f"[+] Wallet '{self.name}' locked")

    def _derive_address(self, index: int) -> Dict[str, Any]:
        material = self.master_seed + index.to_bytes(4, "big")
        zeta = hashlib.sha256(material).digest()
        pk, sk = pq_keygen_from_seed(zeta)
        addr = address_from_pubkey(pk)
        entry = {"index": index, "address": addr, "public_key": pk.hex(), "secret_key": sk.hex()}
        for i, a in enumerate(self.addresses):
            if a["index"] == index:
                self.addresses[i] = entry
                return entry
        self.addresses.append(entry)
        self.addresses.sort(key=lambda x: x["index"])
        return entry

    def new_address(self) -> str:
        self._require_unlocked()
        next_idx = max((a["index"] for a in self.addresses), default=-1) + 1
        entry = self._derive_address(next_idx)
        self._save()
        print(f"[+] New address #{next_idx}: {entry['address']}")
        return entry["address"]

    def list_addresses(self) -> List[str]:
        self._require_unlocked()
        return [a["address"] for a in self.addresses]

    @property
    def address(self) -> str:
        return self.addresses[0]["address"] if self.addresses else ""

    def get_keypair(self, address: Optional[str] = None) -> Tuple[bytes, bytes]:
        self._require_unlocked()
        target = address or self.address
        for a in self.addresses:
            if a["address"] == target:
                return bytes.fromhex(a["public_key"]), bytes.fromhex(a["secret_key"])
        raise ValueError(f"Address {target} not found in this wallet")

    def create_transaction(self, recipient: str, amount: float, memo: str = "",
                           from_address: Optional[str] = None) -> Transaction:
        self._require_unlocked()
        sender = from_address or self.address
        pk, sk = self.get_keypair(sender)
        tx = Transaction(tx_id=str(uuid.uuid4()), sender=sender, recipient=recipient,
                         amount=amount, timestamp=time.time(), public_key=pk.hex(),
                         signature="", memo=memo)
        tx.signature = pq_sign(sk, tx.message_to_sign()).hex()
        return tx

    def record_history(self, tx: Transaction, direction: str = "out") -> None:
        self._require_unlocked()
        entry = {"tx_id": tx.tx_id, "direction": direction,
                 "counterparty": tx.recipient if direction == "out" else tx.sender,
                 "amount": tx.amount, "memo": tx.memo, "timestamp": tx.timestamp,
                 "address": tx.sender if direction == "out" else tx.recipient}
        self.history.append(entry)
        self._save()

    def show_history(self, limit: int = 20) -> None:
        self._require_unlocked()
        if not self.history:
            print("  (no transactions recorded yet)")
            return
        print(f"\n  Last {min(limit, len(self.history))} transactions:")
        for h in reversed(self.history[-limit:]):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["timestamp"]))
            arrow = "→" if h["direction"] == "out" else "←"
            print(f"  {ts}  {arrow}  {h['amount']:>8.2f} VEX  {h['counterparty'][:14]}...  {h.get('memo','')[:20]}")

    def _require_unlocked(self) -> None:
        if not self._unlocked:
            raise RuntimeError("Wallet is locked. Call unlock(password) first.")

    @staticmethod
    def _ask_password(create: bool = False) -> str:
        import getpass
        while True:
            p1 = getpass.getpass("  Password for wallet: ")
            if len(p1) < 4:
                print("  Password too short (min 4 chars)")
                continue
            if create:
                p2 = getpass.getpass("  Confirm password: ")
                if p1 != p2:
                    print("  Passwords do not match")
                    continue
            return p1

class VexloreChain:
    def __init__(self):
        self.chain: List[Block] = []
        self.pending: List[Transaction] = []
        self.balances: Dict[str, float] = {}
        self.current_difficulty = INITIAL_DIFFICULTY
        self._load_or_create()

    def _load_or_create(self) -> None:
        if CHAIN_FILE.exists():
            try:
                raw = json.loads(CHAIN_FILE.read_text())
                self.chain = [Block.from_dict(b) for b in raw["chain"]]
                if not self.is_valid():
                    raise ValueError("stored chain fails current consensus validation")
                self.balances = {}
                known_ids = {
                    tx.tx_id
                    for tx in self.chain[0].transactions
                    if isinstance(tx, Transaction) and isinstance(tx.tx_id, str)
                }
                for block in self.chain[1:]:
                    balances = self._replay_block(
                        block, self.chain[:block.index], self.balances, known_ids
                    )
                    if balances is None:
                        raise ValueError("stored chain fails transaction validation")
                    self.balances = balances
                    known_ids.update(tx.tx_id for tx in block.transactions)
                self.current_difficulty = self.chain[-1].difficulty
                print(f"[+] Loaded chain with {len(self.chain)} blocks (diff={self.current_difficulty})")
            except Exception as e:
                print(f"[!] Failed to load chain: {e}")
                if CHAIN_FILE.exists():
                    backup = CHAIN_FILE.with_name(
                        f"{CHAIN_FILE.name}.invalid-{time.time_ns()}"
                    )
                    shutil.copy2(CHAIN_FILE, backup)
                    print(f"[!] Preserved rejected chain at {backup}")
                self._create_genesis()
        else:
            self._create_genesis()

    def _create_genesis(self) -> None:
        print("[*] Creating Genesis block of Vexlore Quantumproof Chain ...")
        self.chain = []
        self.pending = []
        self.balances = {}
        block = canonical_genesis_block()
        self.chain.append(block)
        self.current_difficulty = INITIAL_DIFFICULTY
        self._save()
        print(f"[+] Genesis block created: {block.hash[:16]}...")

    def _atomic_save(self, data: dict) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, CHAIN_FILE)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def _save(self) -> None:
        data = {"name": CHAIN_NAME, "version": VERSION, "algo": "ML-DSA-44 (FIPS 204)",
                "difficulty": self.current_difficulty, "chain": [b.to_dict() for b in self.chain],
                "balances": self.balances}
        self._atomic_save(data)

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    @staticmethod
    def _next_difficulty(blocks: List[Block]) -> int:
        difficulty = blocks[-1].difficulty
        if len(blocks) < DIFFICULTY_ADJUST_EVERY + 1:
            return difficulty
        recent = blocks[-DIFFICULTY_ADJUST_EVERY:]
        time_taken = recent[-1].timestamp - recent[0].timestamp
        expected = TARGET_BLOCK_TIME * (DIFFICULTY_ADJUST_EVERY - 1)
        if time_taken < expected * 0.7:
            return min(MAX_DIFFICULTY, difficulty + 1)
        if time_taken > expected * 1.4:
            return max(MIN_DIFFICULTY, difficulty - 1)
        return difficulty

    def _adjust_difficulty(self) -> int:
        difficulty = self._next_difficulty(self.chain)
        if difficulty != self.current_difficulty:
            print(f"[*] Difficulty adjusted: {self.current_difficulty} → {difficulty}")
        return difficulty

    @staticmethod
    def _finite_number(value: Any) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False

    @classmethod
    def _valid_amount(cls, amount: Any) -> bool:
        return cls._finite_number(amount) and amount > 0

    def _apply_user_transaction(
        self, tx: Transaction, balances: Dict[str, float], known_ids: Set[str]
    ) -> Optional[Dict[str, float]]:
        if not isinstance(tx, Transaction) or not isinstance(tx.tx_id, str):
            return None
        if (
            tx.sender == "VEXLORE_NETWORK"
            or not tx.tx_id
            or not isinstance(tx.sender, str)
            or not isinstance(tx.recipient, str)
            or not tx.sender
            or not tx.recipient
            or tx.tx_id in known_ids
            or not self._finite_number(tx.timestamp)
            or not self._valid_amount(tx.amount)
            or not tx.verify()
            or balances.get(tx.sender, 0.0) < tx.amount
        ):
            return None
        updated = balances.copy()
        updated[tx.sender] = updated.get(tx.sender, 0.0) - tx.amount
        updated[tx.recipient] = updated.get(tx.recipient, 0.0) + tx.amount
        return updated

    def _replay_block(
        self, block: Block, previous_blocks: List[Block],
        balances: Dict[str, float], known_ids: Set[str]
    ) -> Optional[Dict[str, float]]:
        if (
            not isinstance(block.difficulty, int)
            or isinstance(block.difficulty, bool)
            or not MIN_DIFFICULTY <= block.difficulty <= MAX_DIFFICULTY
            or block.difficulty != self._next_difficulty(previous_blocks)
            or not isinstance(block.nonce, int)
            or isinstance(block.nonce, bool)
            or block.nonce < 0
            or not isinstance(block.miner, str)
            or not block.miner
            or not self._finite_number(block.timestamp)
            or block.timestamp < previous_blocks[-1].timestamp
            or not isinstance(block.hash, str)
            or not isinstance(block.transactions, list)
            or not 1 <= len(block.transactions) <= MAX_TX_PER_BLOCK + 1
            or block.hash != block.compute_hash()
            or not block.hash.startswith("0" * block.difficulty)
        ):
            return None

        updated = balances.copy()
        block_ids: Set[str] = set()
        rewards = 0
        for index, tx in enumerate(block.transactions):
            if (
                not isinstance(tx, Transaction)
                or not isinstance(tx.tx_id, str)
                or not tx.tx_id
                or tx.tx_id in known_ids
                or tx.tx_id in block_ids
            ):
                return None
            if tx.sender == "VEXLORE_NETWORK":
                if (
                    index != len(block.transactions) - 1
                    or tx.amount != BLOCK_REWARD
                    or tx.recipient != block.miner
                    or tx.memo != "Block reward"
                    or not self._finite_number(tx.timestamp)
                    or tx.public_key
                    or tx.signature
                ):
                    return None
                rewards += 1
                updated[tx.recipient] = updated.get(tx.recipient, 0.0) + BLOCK_REWARD
            else:
                next_balances = self._apply_user_transaction(tx, updated, known_ids | block_ids)
                if next_balances is None:
                    return None
                updated = next_balances
            block_ids.add(tx.tx_id)
        return updated if rewards == 1 else None

    def add_transaction(self, tx: Transaction) -> bool:
        known_ids = {
            item.tx_id
            for block in self.chain
            for item in block.transactions
            if isinstance(item.tx_id, str)
        }
        pending_balances = self.balances.copy()
        pending_ids = set(known_ids)
        for pending in self.pending:
            next_balances = self._apply_user_transaction(pending, pending_balances, pending_ids)
            if next_balances is not None:
                pending_balances = next_balances
                pending_ids.add(pending.tx_id)
        if self._apply_user_transaction(tx, pending_balances, pending_ids) is None:
            print("[-] Invalid or unfunded transaction – rejected")
            return False
        if len(self.pending) >= MAX_TX_PER_BLOCK * 3:
            print("[-] Mempool full – try mining first")
            return False
        self.pending.append(tx)
        print(f"[+] Pending tx {tx.tx_id[:8]}... {tx.amount} VEX → {tx.recipient[:12]}...  (mempool: {len(self.pending)})")
        return True

    def mine_pending(self, miner_address: str) -> Optional[Block]:
        if not isinstance(miner_address, str) or not miner_address:
            raise ValueError("miner address must be a non-empty string")
        known_ids = {
            item.tx_id
            for block in self.chain
            for item in block.transactions
            if isinstance(item.tx_id, str)
        }
        balances = self.balances.copy()
        included: List[Transaction] = []
        remaining: List[Transaction] = []
        for tx in self.pending:
            next_balances = self._apply_user_transaction(tx, balances, known_ids)
            if next_balances is None:
                continue
            if len(included) >= MAX_TX_PER_BLOCK:
                remaining.append(tx)
                continue
            included.append(tx)
            balances = next_balances
            known_ids.add(tx.tx_id)

        reward = Transaction(
            tx_id=str(uuid.uuid4()), sender="VEXLORE_NETWORK", recipient=miner_address,
            amount=BLOCK_REWARD, timestamp=time.time(), public_key="", signature="",
            memo="Block reward",
        )
        txs = included + [reward]
        self.current_difficulty = self._adjust_difficulty()
        block = Block(
            index=len(self.chain), timestamp=time.time(), transactions=txs,
            previous_hash=self.last_block.hash, difficulty=self.current_difficulty,
            miner=miner_address,
        )
        print(f"[*] Mining block #{block.index} (difficulty {block.difficulty}, {len(included)} txs) ...")
        start = time.time()
        block.mine()
        print(f"[+] Block mined in {time.time()-start:.2f}s  hash={block.hash}")
        for tx in txs:
            if tx.sender != "VEXLORE_NETWORK":
                self.balances[tx.sender] = self.balances.get(tx.sender, 0.0) - tx.amount
            self.balances[tx.recipient] = self.balances.get(tx.recipient, 0.0) + tx.amount
        self.chain.append(block)
        self.pending = remaining
        self._save()
        return block

    def get_balance(self, address: str) -> float:
        return self.balances.get(address, 0.0)

    def is_valid(self, chain: Optional[List[Block]] = None) -> bool:
        blocks = chain if chain is not None else self.chain
        if not blocks:
            return False
        genesis = blocks[0]
        if (
            not isinstance(genesis, Block)
            or not isinstance(genesis.index, int)
            or isinstance(genesis.index, bool)
            or genesis.index != 0
            or genesis.previous_hash != "0" * 64
            or genesis.difficulty != INITIAL_DIFFICULTY
            or not self._finite_number(genesis.timestamp)
            or not isinstance(genesis.transactions, list)
            or not isinstance(genesis.hash, str)
            or genesis.to_dict() != canonical_genesis_block().to_dict()
        ):
            return False
        balances: Dict[str, float] = {}
        known_ids = {
            tx.tx_id
            for tx in genesis.transactions
            if isinstance(tx, Transaction) and isinstance(tx.tx_id, str)
        }
        for i in range(1, len(blocks)):
            current, previous = blocks[i], blocks[i - 1]
            if (
                not isinstance(current, Block)
                or not isinstance(current.index, int)
                or isinstance(current.index, bool)
                or current.index != previous.index + 1
                or current.previous_hash != previous.hash
            ):
                return False
            updated = self._replay_block(current, blocks[:i], balances, known_ids)
            if updated is None:
                return False
            balances = updated
            known_ids.update(tx.tx_id for tx in current.transactions)
        return True

    def replace_chain(self, new_blocks: List[Block]) -> bool:
        if len(new_blocks) <= len(self.chain) or not self.is_valid(new_blocks):
            if len(new_blocks) > len(self.chain):
                print("[-] Received chain failed validation – ignored")
            return False
        print(f"[+] Adopting longer chain ({len(self.chain)} → {len(new_blocks)} blocks)")
        balances: Dict[str, float] = {}
        known_ids = {
            tx.tx_id
            for tx in new_blocks[0].transactions
            if isinstance(tx, Transaction) and isinstance(tx.tx_id, str)
        }
        for block in new_blocks[1:]:
            updated = self._replay_block(block, new_blocks[:block.index], balances, known_ids)
            if updated is None:
                return False
            balances = updated
            known_ids.update(tx.tx_id for tx in block.transactions)
        self.chain = new_blocks
        self.balances = balances
        self.pending = []
        self.current_difficulty = self.chain[-1].difficulty
        self._save()
        return True

    def add_block_from_peer(self, block: Block) -> bool:
        if (
            not isinstance(block, Block)
            or not isinstance(block.index, int)
            or isinstance(block.index, bool)
            or block.index != len(self.chain)
            or block.previous_hash != self.last_block.hash
        ):
            return False
        known_ids = {
            tx.tx_id
            for previous_block in self.chain
            for tx in previous_block.transactions
            if isinstance(tx.tx_id, str)
        }
        balances = self._replay_block(block, self.chain, self.balances, known_ids)
        if balances is None:
            return False
        self.balances = balances
        confirmed_ids = {t.tx_id for t in block.transactions}
        self.pending = [t for t in self.pending if t.tx_id not in confirmed_ids]
        self.chain.append(block)
        self.current_difficulty = block.difficulty
        self._save()
        print(f"[+] Accepted block #{block.index} from peer  hash={block.hash[:16]}...")
        return True

    def scan_history_for(self, addresses: Set[str]) -> List[Dict[str, Any]]:
        found = []
        for block in self.chain:
            for tx in block.transactions:
                if tx.sender in addresses or tx.recipient in addresses:
                    found.append({"block": block.index, "tx_id": tx.tx_id, "sender": tx.sender,
                                  "recipient": tx.recipient, "amount": tx.amount, "memo": tx.memo,
                                  "timestamp": tx.timestamp})
        return found

class PeerManager:
    def __init__(self, self_url: str = ""):
        self.self_url = self_url.rstrip("/")
        self.peers: Set[str] = set()
        self._load()

    def _load(self) -> None:
        if PEERS_FILE.exists():
            try:
                candidates = json.loads(PEERS_FILE.read_text()).get("peers", [])
                if not isinstance(candidates, list):
                    raise ValueError("peer list must be a list")
                self.peers = {
                    normalized
                    for peer in candidates
                    if isinstance(peer, str)
                    for normalized in [self._normalize_url(peer)]
                    if normalized and normalized != self.self_url
                }
            except Exception:
                self.peers = set()

    def _save(self) -> None:
        PEERS_FILE.write_text(json.dumps({"peers": sorted(self.peers), "updated": time.time()}, indent=2))

    @staticmethod
    def _normalize_url(url: str) -> Optional[str]:
        if not isinstance(url, str) or not url or len(url) > 2048 or any(c.isspace() for c in url):
            return None
        candidate = url if "://" in url else f"http://{url}"
        try:
            parsed = urlsplit(candidate)
            if (
                parsed.scheme.lower() not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                return None
            hostname = parsed.hostname.rstrip(".")
            port = parsed.port
            if port is None:
                port = 443 if parsed.scheme.lower() == "https" else 80
            if port < 1:
                return None
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                return None
            if not address.is_global:
                return None
            authority_host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
            default_port = 443 if parsed.scheme.lower() == "https" else 80
            authority = authority_host if port == default_port else f"{authority_host}:{port}"
            return urlunsplit((parsed.scheme.lower(), authority, "", "", ""))
        except (OSError, ValueError):
            return None

    def request(self, method: str, peer: str, endpoint: str, **kwargs: Any):
        normalized = self._normalize_url(peer)
        if normalized is None:
            raise ValueError("peer URL must use a globally routable IP address")
        return requests.request(
            method,
            f"{normalized}{endpoint}",
            allow_redirects=False,
            **kwargs,
        )

    def add(self, url: str) -> bool:
        normalized = self._normalize_url(url)
        if normalized is None:
            return False
        if normalized == self.self_url or normalized in self.peers:
            return False
        self.peers.add(normalized)
        self._save()
        print(f"[+] Peer added: {normalized}")
        return True

    def remove(self, url: str) -> bool:
        normalized = self._normalize_url(url)
        if normalized in self.peers:
            self.peers.discard(normalized)
            self._save()
            print(f"[+] Peer removed: {normalized}")
            return True
        return False

    def list(self) -> List[str]:
        return sorted(self.peers)

    def broadcast_block(self, block: Block) -> None:
        payload = block.to_dict()
        for peer in list(self.peers):
            try:
                r = self.request("post", peer, "/block", json=payload, timeout=5)
                print(f"    → block sent to {peer}" if r.status_code == 200 else f"    → {peer} rejected block ({r.status_code})")
            except Exception as e:
                print(f"    → {peer} unreachable ({e.__class__.__name__})")

    def broadcast_tx(self, tx: Transaction) -> None:
        payload = tx.to_dict()
        for peer in list(self.peers):
            try:
                self.request("post", peer, "/transaction", json=payload, timeout=5)
            except Exception:
                pass

    def fetch_chain(self, peer: str) -> Optional[List[Block]]:
        try:
            r = self.request("get", peer, "/chain", timeout=8)
            if r.status_code != 200:
                return None
            return [Block.from_dict(b) for b in r.json().get("chain", [])]
        except Exception:
            return None

    def fetch_peers(self, peer: str) -> List[str]:
        try:
            r = self.request("get", peer, "/peers", timeout=5)
            if r.status_code == 200:
                return r.json().get("peers", [])
        except Exception:
            pass
        return []

class NodeHTTPHandler(BaseHTTPRequestHandler):
    chain: VexloreChain
    peers: PeerManager

    def log_message(self, fmt: str, *args) -> None:
        print(f"  [HTTP] {self.address_string()} {fmt % args}")

    def _json_response(self, code: int, obj: Any) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Optional[Dict]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return None

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self._json_response(200, {"name": CHAIN_NAME, "version": VERSION, "blocks": len(self.chain.chain),
                                      "difficulty": self.chain.current_difficulty, "mempool": len(self.chain.pending),
                                      "peers": len(self.peers.peers)})
        elif path == "/chain":
            self._json_response(200, {"length": len(self.chain.chain), "chain": [b.to_dict() for b in self.chain.chain]})
        elif path == "/status":
            self._json_response(200, {"version": VERSION, "blocks": len(self.chain.chain),
                                      "difficulty": self.chain.current_difficulty, "last_hash": self.chain.last_block.hash,
                                      "mempool": len(self.chain.pending), "peers": self.peers.list()})
        elif path == "/peers":
            self._json_response(200, {"peers": self.peers.list()})
        elif path in ("/pending", "/mempool"):
            self._json_response(200, {"count": len(self.chain.pending), "pending": [t.to_dict() for t in self.chain.pending]})
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        data = self._read_json()
        if path == "/block":
            if not data:
                self._json_response(400, {"error": "no body"})
                return
            try:
                block = Block.from_dict(data)
            except Exception:
                self._json_response(400, {"error": "invalid block"})
                return
            ok = self.chain.add_block_from_peer(block)
            if ok:
                self.peers.broadcast_block(block)
                self._json_response(200, {"status": "accepted"})
            else:
                self._json_response(409, {"status": "rejected"})
        elif path == "/transaction":
            if not data:
                self._json_response(400, {"error": "no body"})
                return
            try:
                tx = Transaction.from_dict(data)
            except Exception:
                self._json_response(400, {"error": "invalid tx"})
                return
            ok = self.chain.add_transaction(tx)
            self._json_response(200 if ok else 409, {"status": "ok" if ok else "rejected"})
        elif path == "/peers":
            if not isinstance(data, dict):
                self._json_response(400, {"error": "JSON object required"})
                return
            url = data.get("url", "")
            if url:
                if self.peers.add(url):
                    self._json_response(200, {"status": "added", "peers": self.peers.list()})
                else:
                    self._json_response(400, {"error": "peer URL is invalid, unsafe, or already known"})
            else:
                self._json_response(400, {"error": "url required"})
        else:
            self._json_response(404, {"error": "not found"})

class NodeServer:
    def __init__(self, chain: VexloreChain, port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
        self.chain = chain
        self.port = port
        self.host = host
        advertised_host = self._guess_local_ip() if host in ("0.0.0.0", "::") else host
        self.self_url = f"http://{advertised_host}:{port}"
        self.peers = PeerManager(self.self_url)
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._sync_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @staticmethod
    def _guess_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def start(self) -> None:
        handler = type("Handler", (NodeHTTPHandler,), {"chain": self.chain, "peers": self.peers})
        self._server = HTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[+] Node listening on http://{self.host}:{self.port}")
        print(f"    Self URL : {self.self_url}")
        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()
        print(f"[+] Background sync every {SYNC_INTERVAL}s")

    def stop(self) -> None:
        self._stop.set()
        if self._server:
            self._server.shutdown()

    def _sync_loop(self) -> None:
        while not self._stop.is_set():
            self.sync_with_peers()
            self._stop.wait(SYNC_INTERVAL)

    def sync_with_peers(self) -> None:
        if not self.peers.peers:
            return
        best_chain, best_len = None, len(self.chain.chain)
        for peer in list(self.peers.peers):
            remote = self.peers.fetch_chain(peer)
            if remote and len(remote) > best_len and self.chain.is_valid(remote):
                best_chain, best_len = remote, len(remote)
            try:
                self.peers.request("post", peer, "/peers", json={"url": self.self_url}, timeout=4)
            except Exception:
                pass
        if best_chain:
            self.chain.replace_chain(best_chain)

    def add_peer(self, url: str) -> bool:
        if not self.peers.add(url):
            return False
        try:
            self.peers.request("post", url, "/peers", json={"url": self.self_url}, timeout=5)
        except Exception as e:
            print(f"    (handshake failed: {e})")
        self.sync_with_peers()
        return True

def print_banner():
    print(r"""
 __     __        _                 
 \ \   / /____  _| | ___  _ __ ___  
  \ \ / / _ \ \/ / |/ _ \| '__/ _ \ 
   \ V /  __/>  <| | (_) | | |  __/ 
    \_/ \___/_/\_\_|\___/|_|  \___| 
                                    
  Quantumproof Chain  v0.4  — WALLET UPGRADES
  Seed phrases • Encrypted wallets • Multi-address • History
  Post-quantum signatures: ML-DSA-44 (FIPS 204)
""")

def main():
    print_banner()
    chain = VexloreChain()
    wallet: Optional[Wallet] = None
    default_path = WALLETS_DIR / "alice.json"
    if default_path.exists():
        print("[*] Found existing wallet 'alice'")
        import getpass
        pw = getpass.getpass("  Password to unlock (or Enter to skip): ")
        if pw:
            wallet = Wallet("alice", password=pw)
            if not wallet._unlocked:
                wallet = None
    if wallet is None:
        print("[*] No unlocked wallet yet. Use option 1 to create one.")
    node: Optional[NodeServer] = None
    try:
        host = input("Node bind address [127.0.0.1]: ").strip() or "127.0.0.1"
        node = NodeServer(chain, port=DEFAULT_PORT, host=host)
        node.start()
    except OSError as e:
        print(f"[!] Could not bind port {DEFAULT_PORT}: {e}")
        print("    Network features disabled until you free the port or change it.")
        node = None

    while True:
        addrs = len(wallet.addresses) if wallet and wallet._unlocked else 0
        print(f"""
Commands:
  1) New / Restore wallet     2) Unlock wallet
  3) Show balance (fast)      4) Mine 10 VEX reward
  5) Send transaction         6) Mine block
  7) Show chain               8) Validate chain
  9) List my addresses        10) New address
  11) Transaction history     12) Lock wallet
  13) Quit

Network:
  14) List peers              15) Add peer
  16) Remove peer             17) Sync now
  18) Node status             19) Start node (custom port)

Current: {len(chain.chain)} blocks | difficulty {chain.current_difficulty} | mempool {len(chain.pending)} | addresses {addrs}
""")
        choice = input("Vexlore> ").strip()
        if choice == "1":
            name = input("Wallet name [alice]: ").strip() or "alice"
            mode = input("  (n)ew or (r)estore from seed? [n]: ").strip().lower() or "n"
            import getpass
            if mode.startswith("r"):
                print("Enter your 12-word seed phrase:")
                mn = input("  > ").strip()
                pw = getpass.getpass("  New password to encrypt this wallet: ")
                try:
                    wallet = Wallet.restore(name, mn, pw)
                except ValueError as e:
                    print(f"[-] {e}")
            else:
                pw = getpass.getpass("  Password to encrypt the new wallet: ")
                wallet = Wallet(name, password=pw)
        elif choice == "2":
            name = input("Wallet name [alice]: ").strip() or "alice"
            import getpass
            pw = getpass.getpass("  Password: ")
            wallet = Wallet(name, password=pw)
        elif choice == "3":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock a wallet first")
                continue
            print("\n  Balances (fast O(1) lookup):")
            for a in wallet.addresses:
                bal = chain.get_balance(a["address"])
                print(f"    #{a['index']:2d}  {a['address']}  →  {bal:.2f} VEX")
            total = sum(chain.get_balance(a["address"]) for a in wallet.addresses)
            print(f"  ─────────────────────────────\n  Total: {total:.2f} VEX")
        elif choice == "4":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock a wallet first")
                continue
            block = chain.mine_pending(wallet.address)
            print(f"Fixed block reward credited: {chain.get_balance(wallet.address):.2f} VEX")
            if node and block:
                node.peers.broadcast_block(block)
        elif choice == "5":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock a wallet first")
                continue
            recipient = input("Recipient address: ").strip()
            amount = float(input("Amount: "))
            memo = input("Memo (optional): ").strip()
            from_addr = input(f"From address [{wallet.address}]: ").strip() or wallet.address
            try:
                tx = wallet.create_transaction(recipient, amount, memo, from_address=from_addr)
                if chain.add_transaction(tx):
                    wallet.record_history(tx, direction="out")
                    print("Transaction added to mempool. Mine a block to confirm.")
                    if node:
                        node.peers.broadcast_tx(tx)
            except Exception as e:
                print(f"[-] {e}")
        elif choice == "6":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock a wallet first")
                continue
            block = chain.mine_pending(wallet.address)
            if block:
                for tx in block.transactions:
                    if tx.recipient in wallet.list_addresses() and tx.sender != "VEXLORE_NETWORK":
                        wallet.record_history(tx, direction="in")
                print(f"New primary balance: {chain.get_balance(wallet.address)} VEX")
                if node:
                    print("[*] Broadcasting block to peers ...")
                    node.peers.broadcast_block(block)
        elif choice == "7":
            print(f"\n=== {CHAIN_NAME} ({len(chain.chain)} blocks) ===")
            for b in chain.chain:
                print(f"\nBlock #{b.index}  {b.hash[:20]}...  (diff={b.difficulty})")
                print(f"  Prev : {b.previous_hash[:20]}...\n  Nonce: {b.nonce}  Miner: {b.miner[:16]}...")
                for t in b.transactions:
                    print(f"    TX {t.tx_id[:8]}  {t.amount} VEX  {t.sender[:12]} → {t.recipient[:12]}")
        elif choice == "8":
            start = time.time()
            valid = chain.is_valid()
            print(f"Chain valid: {valid}  (checked in {time.time()-start:.3f}s)")
        elif choice == "9":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock a wallet first")
                continue
            print(f"\n  Addresses in wallet '{wallet.name}':")
            for a in wallet.addresses:
                bal = chain.get_balance(a["address"])
                print(f"    #{a['index']:2d}  {a['address']}  ({bal:.2f} VEX)")
        elif choice == "10":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock a wallet first")
                continue
            wallet.new_address()
        elif choice == "11":
            if not wallet or not wallet._unlocked:
                print("[-] Unlock a wallet first")
                continue
            wallet.show_history()
            more = input("  Scan whole chain for more history? [y/N]: ").strip().lower()
            if more == "y":
                addrs = set(wallet.list_addresses())
                found = chain.scan_history_for(addrs)
                print(f"\n  Found {len(found)} transactions on-chain:")
                for h in found[-30:]:
                    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["timestamp"]))
                    print(f"    blk#{h['block']}  {ts}  {h['amount']} VEX  {h['sender'][:10]} → {h['recipient'][:10]}")
        elif choice == "12":
            if wallet and wallet._unlocked:
                wallet.lock()
                wallet = None
            else:
                print("[-] No unlocked wallet")
        elif choice in ("13", "q", "quit", "exit"):
            if node:
                node.stop()
            print("Goodbye from Vexlore.")
            break
        elif choice == "14":
            if not node:
                print("[-] Node not running")
                continue
            peers = node.peers.list()
            print("No peers yet. Use option 15 to add one." if not peers else f"Known peers ({len(peers)}):")
            for p in peers:
                print(f"  • {p}")
        elif choice == "15":
            if not node:
                print("[-] Node not running – start it first (option 19)")
                continue
            url = input("Peer URL (HTTP(S) with a public IP address): ").strip()
            if url:
                if not node.add_peer(url):
                    print("Peer rejected: use an HTTP(S) URL with a globally routable IP address.")
        elif choice == "16":
            if not node:
                print("[-] Node not running")
                continue
            url = input("Peer URL to remove: ").strip()
            node.peers.remove(url)
        elif choice == "17":
            if not node:
                print("[-] Node not running")
                continue
            print("[*] Syncing with peers ...")
            node.sync_with_peers()
            print(f"[+] Local chain now has {len(chain.chain)} blocks")
        elif choice == "18":
            if not node:
                print("[-] Node not running")
                continue
            print(f"Self URL     : {node.self_url}\nBlocks       : {len(chain.chain)}\nDifficulty   : {chain.current_difficulty}")
            print(f"Last hash    : {chain.last_block.hash[:24]}...\nMempool      : {len(chain.pending)} txs")
            print(f"Peers        : {len(node.peers.peers)}\nVersion      : {VERSION}")
        elif choice == "19":
            if node:
                print(f"[!] Node already running on port {node.port}")
                continue
            try:
                port = int(input(f"Port [{DEFAULT_PORT}]: ").strip() or DEFAULT_PORT)
            except ValueError:
                print("Invalid port")
                continue
            try:
                host = input("Bind address [127.0.0.1]: ").strip() or "127.0.0.1"
                node = NodeServer(chain, port=port, host=host)
                node.start()
            except OSError as e:
                print(f"[-] Could not start: {e}")
                node = None
        else:
            print("Unknown command")

if __name__ == "__main__":
    main()
