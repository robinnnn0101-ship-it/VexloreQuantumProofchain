# Vexlore Quantumproof Chain

**Free educational post-quantum blockchain** named **Vexlore**.

Uses real **ML-DSA-44** (FIPS 204) + **ML-KEM-512** (FIPS 203) + hybrid Ed25519 signatures.

> Not production-ready. Clean, runnable prototype for learning.

## Version History

| Version  | Focus                                                                    |
| -------- | ------------------------------------------------------------------------ |
| **v0.1** | Core chain, wallets, PoW, ML-DSA                                         |
| **v0.2** | NETWORK — multi-node, gossip, auto-sync                                  |
| **v0.3** | BETTER CHAIN — adaptive difficulty, bigger blocks, atomic saves          |
| **v0.4** | WALLET UPGRADES — seed phrase, encrypted wallets, multi-address, history |
| **v0.5** | POST-QUANTUM EXTRA — ML-KEM, hybrid sigs, VEXQ, key rotation             |
| **v0.6** | STATE & DATA — clean balances, Merkle trees, prune, export/import        |
| **v0.7** | API & TOOLS — JSON-RPC, block explorer, log viewer, better CLI           |
| **v0.8** | CONSENSUS — multiple miners, orphan blocks, chain reorg, block reward   |
| **v0.9** | CONTRACTS + EXPLORER — multi-sig, time-locks, send rules, Vexlore UI     |

## What's new in v0.9

- **Multi-sig vaults** — lock coins with **M-of-N** participants; when enough signatures are collected, funds auto-release (options **21** / **22**)
- **Time-lock transactions** — lock until a future **block height** or **seconds from now**; claim when ready (options **23** / **24**)
- **Send rules** — min amount, no self-send, max memo length, `VEXQ…` address check (option **27**)
- **Vexlore Explorer** — local web UI at `/explorer` with Vexlore mark + link to [VexloreBot](https://t.me/VexloreBOT) (option **26**)
- **Contract list** — see open / released / claimed locks (option **25**)

Still includes everything from earlier versions: hybrid PQ signatures, ML-KEM peer encryption, VEXQ addresses, key rotation, seed wallets, peers, and the simple numbered CLI.

## Quick Start

```bash
pip install requests cryptography
python3 vexlore_chain.py
```

You need both folders next to the script:

- `dilithium_src/`  (ML-DSA)
- `kyber_src/`      (ML-KEM)

### First run

1. Option **1** → create wallet → write down the 12 words  
2. Option **4** → faucet  
3. Option **6** → mine  
4. Option **3** → see balance  
5. Option **26** → open **Vexlore Explorer** in your browser  
6. Option **21–25** → try multi-sig / time-lock contracts  

### Explorer

```
http://127.0.0.1:5000/explorer
```

Opens a dark-themed local block explorer (blocks, balances, contracts) with a link to **VexloreBot**: https://t.me/VexloreBOT

## Menu map

| # | Action |
|---|--------|
| **1–14** | Wallet, send, mine, history, rotate key, quit (classic v0.5 flow) |
| **15–20** | Peers, sync, node status, custom port |
| **21** | Create multi-sig vault |
| **22** | Sign multi-sig release |
| **23** | Create time-lock |
| **24** | Claim time-lock |
| **25** | List contracts |
| **26** | Open Vexlore Explorer |
| **27** | Show send rules |

## Folder layout

```
vexlore/
├── vexlore_chain.py
├── README.md
├── dilithium_src/     ← ML-DSA-44
├── kyber_src/         ← ML-KEM-512
├── wallet/            ← encrypted wallets
└── data/              ← chain + peers + contracts
```

## HTTP endpoints (when node is running)

| Path | Description |
|------|-------------|
| `GET /` | Node info + explorer link |
| `GET /explorer` | **Vexlore Explorer** web UI |
| `GET /chain` | Full chain JSON |
| `GET /status` | Status snapshot |
| `GET /peers` | Peer list |
| `GET /mempool` | Pending transactions |
| `GET /kem` | ML-KEM encapsulation key |
| `POST /block` | Accept block (optional ML-KEM encryption) |
| `POST /transaction` | Accept tx |
| `POST /peers` | Register peer |
| `POST /kem` | Exchange KEM keys |

Educational only — do not put real money on it.
