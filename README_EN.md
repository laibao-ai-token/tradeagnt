# tradeagnt

Standalone terminal trading assistant — monolith package `src/tradecat` (CLI name `tradecat`), focused on crypto + US equity demo loop: TUI, signals, paper trading, on-demand quotes.

> Repository: [laibao-ai-token/tradeagnt](https://github.com/laibao-ai-token/tradeagnt)  
> Not the full TradeCat microservices platform. Legacy upstream README: [`docs/archive/README_EN_legacy_tradecat_upstream.md`](docs/archive/README_EN_legacy_tradecat_upstream.md).

[简体中文](README.md)

---

## Quick start

```bash
git clone https://github.com/laibao-ai-token/tradeagnt.git
cd tradeagnt
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp config/.env.example config/.env && chmod 600 config/.env

export TRADECAT_PIPELINE_PROFILE=tui_dual
tradecat tui
```

Freeze gate: `./scripts/freeze_verify.sh`

---

## Docs

| Doc | Topic |
|:---|:---|
| [docs/STANDALONE.md](docs/STANDALONE.md) | Product scope |
| [docs/FREEZE_SCOPE.md](docs/FREEZE_SCOPE.md) | v0.8 freeze |
| [docs/MIGRATE_v0.8_to_v1.0.md](docs/MIGRATE_v0.8_to_v1.0.md) | Migration |

License: MIT.
