# CareMax

Pharmacy POS with inventory tracking, billing, sales reports, and a navigation assistant.

## Run with Python

1. Install Python 3.9 or later.
2. Start the app with `python server.py` (or `npm start`).
3. Open `http://127.0.0.1:5000`.

The Python service uses the standard library and the existing `caremax.db` SQLite database. Set `CAREMAX_DB_PATH` to use a different database file. Product cost must be entered when adding or receiving stock for gross-profit reporting; existing stock without a recorded cost remains excluded from profit until that inventory is replaced. The chat assistant uses built-in navigation and workflow guidance and does not require an external AI service.

The original Node service remains available with `npm run start:node`.
