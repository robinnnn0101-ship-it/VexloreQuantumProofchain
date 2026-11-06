# Vexlore Quantumproof Chain

**Free educational post-quantum blockchain** named **Vexlore**.

Uses real **ML-DSA-44** (FIPS 204) + **ML-KEM-512** (FIPS 203) + hybrid Ed25519 signatures.

> Not production-ready. Clean, runnable prototype for learning. Version 1.2 upgrades.

## Version History

| Version  | Focus                                                                    |
| -------- | ------------------------------------------------------------------------ |
| **v1.2** | More docs, utilities, packaging polish, contribution series (40+)       |
| **v1.1** | Packaging, CI, Docker, more docs & polish                                |
| **v1.0** | Docs, setup, tests, contribution polish                                  |
| **v0.9** | CONTRACTS + EXPLORER — multi-sig, time-locks, send rules, Vexlore UI     |
| **v0.1-0.8** | Core chain, network, PQ, wallets, consensus                          |

## Quick Start

```bash
pip install -r requirements.txt
python3 vexlore_chain.py
```

Or with Docker:

```bash
docker build -t vexlore .
docker run -p 5000:5000 vexlore
```

See docs/ for detailed guides: SETUP.md, WALLET.md, MINING.md, etc.

Educational only — do not put real money on it.  
Made by robin with love ❤️

## Features

- Hybrid post-quantum signatures (ML-DSA-44 + Ed25519)
- ML-KEM key encapsulation
- Multi-node networking & gossip
- Multi-sig vaults & time-locks
- Local explorer UI
- Seed phrase wallets
- Adaptive difficulty PoW

## Contributing

PRs welcome. See CONTRIBUTING.md.

## Recent Upgrades (v1.2)

- Version 1.2.0 release series
- Expanded feature documentation (feature_26 to feature_60+)
- Additional utility scripts
- Packaging and metadata improvements
- Contribution and polish pass

Over 40+ new contributions in the v1.2 upgrade series.
