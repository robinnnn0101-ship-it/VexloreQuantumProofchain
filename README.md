# Vexlore Quantumproof Chain

**Free educational post-quantum blockchain** named **Vexlore**.

Uses real **ML-DSA-44** (FIPS 204) + **ML-KEM-512** (FIPS 203) + hybrid Ed25519 signatures.

> Not production-ready. Clean, runnable prototype for learning. **Version 1.3 — more powerful upgrades.**

## Version History

| Version  | Focus                                                                    |
| -------- | ------------------------------------------------------------------------ |
| **v1.3** | Enhanced power: faster difficulty, better PQ notes, utils, 75+ contribs |
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
- Multi-node networking & gossip (improved efficiency in v1.3)
- Multi-sig vaults & time-locks
- Local explorer UI
- Seed phrase wallets
- Adaptive difficulty PoW (faster retarget in v1.3)
- Benchmark & stress utilities

## Contributing

PRs welcome. See CONTRIBUTING.md.

## Recent Upgrades (v1.3)

- Version 1.3.0 release — more powerful prototype
- Expanded feature documentation (feature_61 to feature_140+)
- New performance and benchmark utilities
- Enhanced adaptive difficulty and networking notes
- Contribution series (75+ new)
- Packaging and CI refinements

Over 75+ new contributions in the v1.3 upgrade series.
