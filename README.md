# garmin-sync

Garmin Connect → titkosított feed → Claude edzésnapló.

- `garmin_sync.py` – óránként fut (GitHub Actions): új tekerések letöltése (.fit), elemzése, alvásadatok
- `analyze.py` – a napló oszlopainak számítása (odaút, hazaút, görgő, hosszú, egyéb)
- `feedcrypt.py` – AES-256-GCM; a repóban minden adat titkosítva van
- `feed_read.py` – a feed olvasása (`FEED_KEY=... python3 feed_read.py`)

Secretek: `GARMINTOKENS`, `FEED_KEY`, `TOKEN_KEY`.
