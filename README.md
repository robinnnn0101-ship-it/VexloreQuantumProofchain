# Vexlore Quantumproof Chain

**Free educational post-quantum blockchain** named **Vexlore**.

Uses real **ML-DSA-44** (FIPS 204) + **ML-KEM-512** (FIPS 203) + hybrid Ed25519 signatures.

> Not production-ready. Clean, runnable prototype for learning.

## Version History

| Version | Focus |
|---------|--------|
| **v0.1** | Core chain, wallets, PoW, ML-DSA |
| **v0.2** | NETWORK — multi-node, gossip, auto-sync |
| **v0.3** | BETTER CHAIN — adaptive difficulty, bigger blocks, atomic saves |
| **v0.4** | WALLET UPGRADES — seed phrase, encrypted wallets, multi-address, history |
| **v0.5** | POST-QUANTUM EXTRA — ML-KEM, hybrid sigs, VEXQ, key rotation |
| **v0.6** | STATE & DATA — clean balances, Merkle trees, prune, export/import |
| **v0.7** | API & TOOLS — JSON-RPC, block explorer, log viewer, better CLI |
| **v0.8** | CONSENSUS — multiple miners, orphan blocks, chain reorg, block reward |

## What's new in v0.8

- **Multiple miners** — several miners can race at the same time (demo with option 13)
- **Orphan block handling** — blocks that don’t connect to the tip are saved as orphans
- **Chain reorg rules** — if a longer valid chain appears, the node switches to it (longest chain wins)
- **Block reward** — every mined block gives the miner **50 VEX** (coinbase transaction)
- **Read File** — new menu option (14) to inspect any file (chain.json, wallet, logs, etc.)

## Quick Start

```bash
pip install requests cryptography
python3 vexlore_chain.py