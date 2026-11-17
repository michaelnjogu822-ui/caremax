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

Before first run in the deployed Node app, set `ADMIN_EMAIL` to the authorized administrator's email in Vercel. Initial setup accepts only that email as the first admin username. Complete setup through the Vercel-protected Production URL with a password of at least 12 characters. Passwords are salted PBKDF2 hashes; session tokens are stored as hashes and issued in HttpOnly cookies. No default credentials are configured.

## Roles

- **Admin:** full access, creates users, assigns roles, and disables accounts.
- **Pharmacist:** manages products and stock, handles patients and appointments, completes sales, and views reports.
- **Cashier:** completes sales and sees the product catalog, without patient records or inventory cost data.
- **Viewer:** reads reports and sales records.

The API enforces each role. Hiding a page in the browser is not used as the access control. Low-stock rows in the dashboard and inventory now link to the receive-stock form; a receipt requires quantity and supplier unit cost and is written to stock history.

## Deploy to Vercel

1. Create a managed PostgreSQL database with a provider such as Neon or Supabase. Copy its TLS-enabled connection string.
2. Import this repository into Vercel. The included `vercel.json` deploys the Node API as a Vercel Function and only publishes the app HTML, CSS, and JavaScript.
3. In Vercel Project Settings → Environment Variables, add `DATABASE_URL` and `ADMIN_EMAIL` for Production. The schema is initialized automatically when the function starts.
4. Deploy, open the deployment URL, and create the first administrator through the Staff Login dialog. Visit `/api/health` to confirm the database connection.

`npm start` runs the Node app locally and also requires `DATABASE_URL`; `npm run start:python` starts the local SQLite version. Never commit database URLs or production credentials. Vercel cannot use the bundled SQLite file as durable storage.

## Kenyan starter catalog

The PostgreSQL app seeds a broad Kenyan chemist starter catalog on first deployment. Seeded entries have zero stock and no expiry date; enter real supplier cost, received quantities, and batch expiry dates when stock is received. KSh prices are editable reference estimates, not live supplier quotes. Kenyan retail medicine prices vary by brand, pack size, county, and pharmacy; compare them with current supplier invoices and local retail prices before trading. Online examples include [ePharmacy Kenya](https://www.epharmacyke.com/shop/) and [AfyaCare Pharmacy](https://afyacare.mobkazi.com/pharmacy/category/medicines-treatments). A national sector report documents substantial price variation, so the starter values should not be treated as regulated prices. Enter the final customer price in each product's price field and include any applicable tax there; the checkout does not add a blanket tax percentage.

Prescription-marked items require a pharmacist or admin to complete the prescription check. The catalog intentionally excludes controlled drugs and cold-chain medicines that need additional regulatory and temperature-control workflows.

## Safaricom M-Pesa STK Push

Checkout sends the customer's Kenyan number to the server, which requests an M-Pesa Express/STK prompt through Safaricom Daraja. The customer enters their PIN on their phone. CareMax records the sale and invoice only after the callback confirms the receipt, amount, and payer number; stock is reserved while the prompt is pending and restored after a failed payment. The PIN never enters the app. See Safaricom's [Daraja developer portal](https://developer.safaricom.co.ke/apis/MpesaExpressSimulate).

Set these sensitive Production environment variables in Vercel after creating and approving a Daraja app: `MPESA_ENV` (`sandbox` until acceptance testing, then `production`), `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_SHORTCODE`, `MPESA_PASSKEY`, `MPESA_TRANSACTION_TYPE` (`CustomerPayBillOnline` for PayBill or `CustomerBuyGoodsOnline` for a supported Till), `MPESA_CALLBACK_BASE_URL` (the public HTTPS CareMax origin), and `MPESA_CALLBACK_TOKEN` (a random secret of at least 32 characters). Register the generated callback URL `/api/payments/mpesa/callback/<MPESA_CALLBACK_TOKEN>` with the Daraja app. Safaricom must accept the callback URL and provide production credentials before live collections can succeed. Never use sandbox credentials for customer payments.
