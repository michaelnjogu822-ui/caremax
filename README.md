# CareMax

Pharmacy POS with inventory tracking, billing, sales reports, and a navigation assistant.

## Run locally with SQLite

1. Install Python 3.9 or later.
2. Start the app with `python server.py`.
3. Open `http://127.0.0.1:5000`.

The Python service uses the standard library and the existing `caremax.db` SQLite database. Set `CAREMAX_DB_PATH` to use a different database file. Product cost must be entered when adding or receiving stock for gross-profit reporting; existing stock without a recorded cost remains excluded from profit until that inventory is replaced. The chat assistant uses built-in navigation and workflow guidance and does not require an external AI service.

The starter catalog adds 25 common medicine entries with sample KSh prices and costs. These are editable reference estimates, not live supplier quotes; verify prices and prescription classifications with the pharmacy's suppliers and qualified staff before use. The POS flags prescription-classified items for pharmacist verification and blocks products whose recorded expiry date has passed.

The Node/Vercel deployment uses PostgreSQL. The Python SQLite server remains a local development option and is separate from the Vercel deployment.


## Owner access

On first run in the deployed Node app, create the administrator account from the Staff Login dialog. Use a unique username and a password of at least 12 characters. Passwords are salted PBKDF2 hashes; session tokens are stored as hashes and issued in HttpOnly cookies. No default credentials are configured.

## Roles

- **Admin:** full access, creates users, assigns roles, and disables accounts.
- **Pharmacist:** manages products and stock, handles patients and appointments, completes sales, and views reports.
- **Cashier:** completes sales and sees the product catalog, without patient records or inventory cost data.
- **Viewer:** reads reports and sales records.

The API enforces each role. Hiding a page in the browser is not used as the access control.

## Deploy to Vercel

1. Create a managed PostgreSQL database with a provider such as Neon or Supabase. Copy its TLS-enabled connection string.
2. Import this repository into Vercel. The included `vercel.json` deploys the Node API as a Vercel Function and only publishes the app HTML, CSS, and JavaScript.
3. In Vercel Project Settings → Environment Variables, add `DATABASE_URL` with that PostgreSQL connection string. Set it for Production and Preview. The schema is initialized automatically when the function starts.
4. Deploy, open the deployment URL, and create the first administrator through the Staff Login dialog. Visit `/api/health` to confirm the database connection.

`npm start` runs the Node app locally and also requires `DATABASE_URL`; `npm run start:python` starts the local SQLite version. Never commit database URLs or production credentials. Vercel cannot use the bundled SQLite file as durable storage.
