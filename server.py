import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CAREMAX_DB_PATH", ROOT / "caremax.db"))
SAMPLE_CATALOG = [
    ("Ibuprofen 400mg tablets (10s)", "IBU-400-10", "Pain Relief", 180, 85, 35, "2027-06-30", 0),
    ("Cetirizine 10mg tablets (10s)", "CET-10-10", "Allergy & Cold", 120, 55, 40, "2027-08-31", 0),
    ("Loratadine 10mg tablets (10s)", "LOR-10-10", "Allergy & Cold", 140, 65, 30, "2027-07-31", 0),
    ("Omeprazole 20mg capsules (14s)", "OME-20-14", "Digestive Health", 230, 105, 24, "2027-09-30", 0),
    ("Metformin 500mg tablets (30s)", "MET-500-30", "Diabetes", 250, 100, 50, "2027-10-31", 1),
    ("Amlodipine 5mg tablets (30s)", "AML-5-30", "Blood Pressure", 160, 65, 32, "2027-08-31", 1),
    ("Losartan 50mg tablets (30s)", "LOS-50-30", "Blood Pressure", 380, 170, 28, "2027-09-30", 1),
    ("Hydrochlorothiazide 25mg tablets (30s)", "HCT-25-30", "Blood Pressure", 150, 65, 26, "2027-07-31", 1),
    ("Atorvastatin 10mg tablets (30s)", "ATO-10-30", "Heart Health", 420, 200, 22, "2027-10-31", 1),
    ("Amoxicillin 500mg capsules (21s)", "AMX-500-21", "Antibiotic", 520, 240, 18, "2027-06-30", 1),
    ("Doxycycline 100mg capsules (10s)", "DOX-100-10", "Antibiotic", 260, 120, 20, "2027-08-31", 1),
    ("Fluconazole 150mg capsule (1s)", "FLU-150-1", "Antifungal", 120, 55, 16, "2027-07-31", 1),
    ("Loperamide 2mg capsules (10s)", "LOP-2-10", "Digestive Health", 150, 65, 25, "2027-09-30", 0),
    ("Zinc sulfate 20mg tablets (10s)", "ZIN-20-10", "Vitamins & Minerals", 110, 50, 32, "2027-10-31", 0),
    ("Folic acid 5mg tablets (30s)", "FOL-5-30", "Vitamins & Minerals", 90, 40, 30, "2027-08-31", 0),
    ("Ferrous sulfate 200mg tablets (30s)", "FER-200-30", "Vitamins & Minerals", 140, 65, 26, "2027-09-30", 0),
    ("Clotrimazole 1% cream (20g)", "CLO-1-20G", "Skin & Fungal", 220, 100, 18, "2027-07-31", 0),
    ("Hydrocortisone 1% cream (15g)", "HYD-1-15G", "Skin Care", 180, 75, 16, "2027-10-31", 0),
    ("Salbutamol 100mcg inhaler (200 doses)", "SAL-100-200", "Respiratory", 650, 320, 14, "2027-06-30", 1),
    ("Chloramphenicol 0.5% eye drops (10ml)", "CHL-05-10ML", "Eye Care", 180, 75, 12, "2027-08-31", 1),
    ("Paracetamol 120mg/5ml oral suspension (100ml)", "PAR-SYR-100", "Pain Relief", 240, 105, 20, "2027-07-31", 0),
    ("Antacid oral suspension (200ml)", "ANT-SUS-200", "Digestive Health", 260, 120, 18, "2027-09-30", 0),
    ("Diclofenac 50mg tablets (10s)", "DIC-50-10", "Pain Relief", 160, 75, 22, "2027-10-31", 1),
    ("Vitamin B complex tablets (30s)", "VBC-30", "Vitamins & Minerals", 240, 110, 20, "2027-08-31", 0),
    ("Multivitamin tablets (30s)", "MVT-30", "Vitamins & Minerals", 450, 210, 18, "2027-09-30", 0),
]


@contextmanager
def database():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                active INTEGER NOT NULL DEFAULT 1,
                createdAt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token_hash TEXT PRIMARY KEY,
                userId INTEGER NOT NULL,
                expiresAt INTEGER NOT NULL,
                FOREIGN KEY(userId) REFERENCES admin_users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                dob TEXT,
                gender TEXT,
                bloodGroup TEXT,
                allergies TEXT
            );
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patientId INTEGER,
                doctor TEXT,
                date TEXT,
                time TEXT,
                reason TEXT,
                status TEXT
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT UNIQUE,
                category TEXT,
                price REAL,
                stock INTEGER,
                expiry TEXT,
                costPrice REAL,
                prescriptionRequired INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sales (
                id TEXT PRIMARY KEY,
                patientId INTEGER,
                amount REAL,
                paymentMethod TEXT,
                createdAt TEXT,
                status TEXT,
                prescriptionVerified INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS invoices (
                id TEXT PRIMARY KEY,
                patientId INTEGER,
                total REAL,
                paymentMethod TEXT,
                status TEXT,
                createdAt TEXT
            );
            CREATE TABLE IF NOT EXISTS stock_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                productId INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unitCost REAL NOT NULL,
                receivedAt TEXT NOT NULL,
                FOREIGN KEY(productId) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                saleId TEXT NOT NULL,
                productId INTEGER NOT NULL,
                productName TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unitPrice REAL NOT NULL,
                unitCost REAL,
                lineProfit REAL,
                FOREIGN KEY(saleId) REFERENCES sales(id),
                FOREIGN KEY(productId) REFERENCES products(id)
            );
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(products)")}
        if "costPrice" not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN costPrice REAL")
        if "prescriptionRequired" not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN prescriptionRequired INTEGER NOT NULL DEFAULT 0")
        sale_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sales)")}
        if "prescriptionVerified" not in sale_columns:
            connection.execute("ALTER TABLE sales ADD COLUMN prescriptionVerified INTEGER NOT NULL DEFAULT 0")
        user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(admin_users)")}
        if "role" not in user_columns:
            connection.execute("ALTER TABLE admin_users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        if "active" not in user_columns:
            connection.execute("ALTER TABLE admin_users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        seed_sample_catalog(connection)


def seed_sample_catalog(connection):
    for product in SAMPLE_CATALOG:
        name, sku, category, price, unit_cost, stock, expiry, prescription_required = product
        cursor = connection.execute(
            "INSERT OR IGNORE INTO products (name, sku, category, price, stock, expiry, costPrice, prescriptionRequired) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, sku, category, price, stock, expiry, unit_cost, prescription_required),
        )
        if cursor.rowcount:
            product_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO stock_receipts (productId, quantity, unitCost, receivedAt) VALUES (?, ?, ?, ?)",
                (product_id, stock, unit_cost, now_iso()),
            )


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def as_dicts(rows):
    return [dict(row) for row in rows]


def response_error(message, status):
    return {"error": message}, status


def int_value(value):
    parsed = int(value)
    if float(value) != parsed:
        raise ValueError
    return parsed


SESSION_COOKIE = "caremax_admin_session"
SESSION_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 310_000
ROLES = ("admin", "pharmacist", "cashier", "viewer")
MANAGER_ROLES = ("admin", "pharmacist")
READ_ROLES = ("admin", "pharmacist", "viewer")
SELL_ROLES = ("admin", "pharmacist", "cashier")
LOGIN_WINDOW_SECONDS = 5 * 60
LOGIN_MAX_FAILURES = 5
DUMMY_SALT = "00" * 16

_login_failures = {}
_login_lock = threading.Lock()


def hash_password(password, salt=None):
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, PASSWORD_ITERATIONS)
    return digest.hex(), salt_bytes.hex()


def password_matches(password, salt, expected_hash):
    return hmac.compare_digest(hash_password(password, salt)[0], expected_hash)


def session_user(token):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with database() as connection:
        row = connection.execute(
            "SELECT u.id, u.username, u.role FROM admin_sessions s "
            "JOIN admin_users u ON u.id = s.userId "
            "WHERE s.token_hash = ? AND s.expiresAt > ? AND u.active = 1",
            (token_hash, int(time.time())),
        ).fetchone()
    return dict(row) if row else None


def issue_session(user_id):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with database() as connection:
        connection.execute("DELETE FROM admin_sessions WHERE expiresAt <= ?", (int(time.time()),))
        connection.execute(
            "INSERT INTO admin_sessions (token_hash, userId, expiresAt) VALUES (?, ?, ?)",
            (token_hash, user_id, int(time.time()) + SESSION_SECONDS),
        )
    return token


def revoke_sessions_for_user(user_id, keep_token=None):
    keep_hash = hashlib.sha256(keep_token.encode("utf-8")).hexdigest() if keep_token else None
    with database() as connection:
        if keep_hash:
            connection.execute(
                "DELETE FROM admin_sessions WHERE userId = ? AND token_hash != ?", (user_id, keep_hash)
            )
        else:
            connection.execute("DELETE FROM admin_sessions WHERE userId = ?", (user_id,))


def login_blocked(key):
    now = time.time()
    with _login_lock:
        failures = [stamp for stamp in _login_failures.get(key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
        if failures:
            _login_failures[key] = failures
        else:
            _login_failures.pop(key, None)
        return len(failures) >= LOGIN_MAX_FAILURES


def record_login_failure(key):
    now = time.time()
    with _login_lock:
        if len(_login_failures) > 5_000:
            for stale in [item for item, stamps in _login_failures.items() if not stamps or now - stamps[-1] > LOGIN_WINDOW_SECONDS]:
                _login_failures.pop(stale, None)
        _login_failures.setdefault(key, []).append(now)


def clear_login_failures(key):
    with _login_lock:
        _login_failures.pop(key, None)


def setup_username():
    return (os.environ.get("ADMIN_EMAIL") or os.environ.get("CAREMAX_ADMIN_EMAIL") or "").strip().lower() or None


def auth_status(user):
    with database() as connection:
        count = connection.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
    return {
        "setupRequired": count == 0,
        "setupUsername": (setup_username() or "admin") if count == 0 else None,
        "authenticated": user is not None,
        "username": user["username"] if user else None,
        "role": user["role"] if user else None,
    }, 200


def authorize(user, roles):
    if user is None:
        return response_error("Login required", 401)
    if user["role"] not in roles:
        return response_error("Insufficient permissions", 403)
    return None


STATIC_FILES = {"/index.html", "/caremax_system_plan.html", "/app.js", "/styles.css"}
READ_ROUTES = {
    "/api/sales": READ_ROLES,
    "/api/invoices": READ_ROLES,
    "/api/reports": READ_ROLES,
    "/api/patients": MANAGER_ROLES,
    "/api/appointments": MANAGER_ROLES,
    "/api/users": ("admin",),
}


def get_data(path):
    if path == "/api/health":
        return {"ok": True, "service": "caremax-python"}, 200
    with database() as connection:
        if path == "/api/products":
            rows = connection.execute("SELECT * FROM products ORDER BY id ASC").fetchall()
            return as_dicts(rows), 200
        if path == "/api/sales":
            rows = connection.execute("SELECT * FROM sales ORDER BY createdAt DESC").fetchall()
            return as_dicts(rows), 200
        if path == "/api/invoices":
            rows = connection.execute("SELECT * FROM invoices ORDER BY createdAt DESC").fetchall()
            return as_dicts(rows), 200
        if path == "/api/patients":
            rows = connection.execute("SELECT * FROM patients ORDER BY id DESC").fetchall()
            return as_dicts(rows), 200
        if path == "/api/appointments":
            rows = connection.execute("SELECT * FROM appointments ORDER BY date DESC, time DESC").fetchall()
            return as_dicts(rows), 200
        if path == "/api/users":
            rows = connection.execute(
                "SELECT id, username, role, active, createdAt AS created_at FROM admin_users ORDER BY id"
            ).fetchall()
            return as_dicts(rows), 200
        if path == "/api/reports":
            patients = connection.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
            appointments = connection.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
            products = as_dicts(connection.execute("SELECT * FROM products").fetchall())
            sales = connection.execute("SELECT amount FROM sales").fetchall()
            profit = connection.execute(
                "SELECT COALESCE(SUM(lineProfit), 0) AS total, COUNT(*) AS knownLines FROM sale_items WHERE lineProfit IS NOT NULL"
            ).fetchone()
            all_sale_lines = connection.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0]
            return {
                "patientCount": patients,
                "appointmentCount": appointments,
                "inventoryValue": sum((product["price"] or 0) * (product["stock"] or 0) for product in products),
                "revenue": sum(sale["amount"] or 0 for sale in sales),
                "grossProfit": profit["total"],
                "unknownCostLines": all_sale_lines - profit["knownLines"],
                "lowStock": [product for product in products if (product["stock"] or 0) < 10],
                "topProducts": products[:5],
            }, 200
    return response_error("Not found", 404)


def add_product(data):
    name = str(data.get("name", "")).strip()
    sku = str(data.get("sku", "")).strip()
    try:
        price = float(data.get("price"))
        stock = int_value(data.get("stock"))
        cost_price = float(data["costPrice"]) if data.get("costPrice") not in (None, "") else None
        prescription_required = int_value(data.get("prescriptionRequired", 0))
    except (KeyError, TypeError, ValueError):
        return response_error("Enter valid price, stock, and unit cost values", 400)
    if not name or not sku or price < 0 or stock < 0 or (cost_price is not None and cost_price < 0) or prescription_required not in (0, 1):
        return response_error("Name and SKU are required; prices and stock cannot be negative", 400)
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO products (name, sku, category, price, stock, expiry, costPrice, prescriptionRequired) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, sku, data.get("category", ""), price, stock, data.get("expiry", ""), cost_price, prescription_required),
            )
            product_id = cursor.lastrowid
            if stock and cost_price is not None:
                connection.execute(
                    "INSERT INTO stock_receipts (productId, quantity, unitCost, receivedAt) VALUES (?, ?, ?, ?)",
                    (product_id, stock, cost_price, now_iso()),
                )
            product = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    except sqlite3.IntegrityError:
        return response_error("That SKU already exists", 409)
    return dict(product), 201


def update_product(product_id, data):
    name = str(data.get("name", "")).strip()
    sku = str(data.get("sku", "")).strip()
    try:
        price = float(data.get("price"))
        prescription_required = int_value(data.get("prescriptionRequired", 0))
    except (TypeError, ValueError):
        return response_error("Enter a valid price and prescription classification", 400)
    if not name or not sku or price < 0 or prescription_required not in (0, 1):
        return response_error("Name and SKU are required; price cannot be negative", 400)
    try:
        with database() as connection:
            existing = connection.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
            if existing is None:
                return response_error("Product not found", 404)
            connection.execute(
                "UPDATE products SET name = ?, sku = ?, category = ?, price = ?, expiry = ?, prescriptionRequired = ? WHERE id = ?",
                (name, sku, data.get("category", ""), price, data.get("expiry", ""), prescription_required, product_id),
            )
            product = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    except sqlite3.IntegrityError:
        return response_error("That SKU already exists", 409)
    return dict(product), 200


def receive_stock(product_id, data):
    try:
        quantity = int_value(data.get("quantity"))
        unit_cost = float(data.get("unitCost"))
    except (TypeError, ValueError):
        return response_error("Enter a whole-number quantity and the supplier's unit cost", 400)
    if quantity <= 0 or unit_cost < 0:
        return response_error("Quantity must be positive and unit cost cannot be negative", 400)
    with database() as connection:
        product = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if product is None:
            return response_error("Product not found", 404)
        old_stock = product["stock"] or 0
        old_cost = product["costPrice"]
        if old_stock == 0 or old_cost is not None:
            new_cost = ((old_stock * (old_cost or 0)) + quantity * unit_cost) / (old_stock + quantity)
        else:
            new_cost = None
        connection.execute("UPDATE products SET stock = stock + ?, costPrice = ? WHERE id = ?", (quantity, new_cost, product_id))
        connection.execute(
            "INSERT INTO stock_receipts (productId, quantity, unitCost, receivedAt) VALUES (?, ?, ?, ?)",
            (product_id, quantity, unit_cost, now_iso()),
        )
        updated = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(updated), 200


def round_money(value):
    return int(math.floor(value + 0.5))


def create_sale(data, user):
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return response_error("Cart is empty", 400)
    payment_method = data.get("paymentMethod") or "Cash"
    if payment_method == "M-Pesa":
        return response_error("M-Pesa sales must be completed through the Safaricom STK Push flow", 400)
    if payment_method not in {"Cash", "Card", "Insurance"}:
        return response_error("Unsupported payment method", 400)
    try:
        discount = float(data.get("discount", 0))
        quantities = {}
        for item in items:
            product_id = int_value(item["productId"])
            quantity = int_value(item["quantity"])
            if quantity <= 0:
                raise ValueError
            quantities[product_id] = quantities.get(product_id, 0) + quantity
    except (KeyError, TypeError, ValueError):
        return response_error("Sale items must have a product and a positive whole-number quantity", 400)
    if not 0 <= discount <= 100:
        return response_error("Discount must be between 0 and 100", 400)

    stamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    sale_id = f"SALE-{stamp}-{secrets.token_hex(2)}"
    invoice_id = f"INV-{stamp}-{secrets.token_hex(2)}"
    created_at = now_iso()
    with database() as connection:
        products = {}
        for product_id, quantity in quantities.items():
            product = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if product is None:
                return response_error("A product in the cart no longer exists", 400)
            if (product["stock"] or 0) < quantity:
                return response_error(f"Not enough stock for {product['name']}", 400)
            if product["expiry"] and product["expiry"] < datetime.now().date().isoformat():
                return response_error(f"{product['name']} is expired and cannot be sold", 400)
            products[product_id] = product

        prescription_items = [product["name"] for product in products.values() if product["prescriptionRequired"]]
        if prescription_items and not data.get("prescriptionVerified"):
            return response_error("A pharmacist must verify the prescription before selling: " + ", ".join(prescription_items), 400)
        if prescription_items and user["role"] not in MANAGER_ROLES:
            return response_error(
                "A pharmacist or administrator must complete the prescription check for: " + ", ".join(prescription_items), 403
            )

        subtotal = sum(products[product_id]["price"] * quantity for product_id, quantity in quantities.items())
        total = round_money(subtotal * (1 - discount / 100))
        connection.execute(
            "INSERT INTO sales (id, patientId, amount, paymentMethod, createdAt, status, prescriptionVerified) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sale_id, data.get("patientId"), total, payment_method, created_at, "Paid", int(bool(prescription_items))),
        )
        connection.execute(
            "INSERT INTO invoices (id, patientId, total, paymentMethod, status, createdAt) VALUES (?, ?, ?, ?, ?, ?)",
            (invoice_id, data.get("patientId"), total, payment_method, "Paid", created_at),
        )
        for product_id, quantity in quantities.items():
            product = products[product_id]
            cost = product["costPrice"]
            line_profit = None if cost is None else (product["price"] * (1 - discount / 100) - cost) * quantity
            connection.execute(
                "INSERT INTO sale_items (saleId, productId, productName, quantity, unitPrice, unitCost, lineProfit) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sale_id, product_id, product["name"], quantity, product["price"], cost, line_profit),
            )
            connection.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id))
            if product["stock"] - quantity == 0:
                connection.execute("UPDATE products SET costPrice = NULL WHERE id = ?", (product_id,))
    return {"saleId": sale_id, "invoiceId": invoice_id, "total": total}, 201


def add_patient(data):
    name = str(data.get("name", "")).strip()
    if not name:
        return response_error("Patient name is required", 400)
    with database() as connection:
        cursor = connection.execute(
            "INSERT INTO patients (name, phone, dob, gender, bloodGroup, allergies) VALUES (?, ?, ?, ?, ?, ?)",
            (name, data.get("phone"), data.get("dob"), data.get("gender"), data.get("bloodGroup", ""), data.get("allergies", "")),
        )
        patient = connection.execute("SELECT * FROM patients WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(patient), 201


def add_appointment(data):
    with database() as connection:
        cursor = connection.execute(
            "INSERT INTO appointments (patientId, doctor, date, time, reason, status) VALUES (?, ?, ?, ?, ?, ?)",
            (data.get("patientId"), data.get("doctor"), data.get("date"), data.get("time"), data.get("reason"), data.get("status", "Scheduled")),
        )
        appointment = connection.execute("SELECT * FROM appointments WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(appointment), 201


def user_row(connection, user_id):
    return connection.execute(
        "SELECT id, username, role, active, createdAt AS created_at FROM admin_users WHERE id = ?", (user_id,)
    ).fetchone()


def create_user(data):
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    role = str(data.get("role", "")).strip()
    if role not in ROLES or role == "admin":
        return response_error(
            "New users can be assigned pharmacist, cashier, or viewer. Administrators must be promoted by an administrator.", 400
        )
    if not username or len(password) < 12:
        return response_error("Enter a username and a password of at least 12 characters", 400)
    digest, salt = hash_password(password)
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO admin_users (username, password_hash, password_salt, role, active, createdAt) VALUES (?, ?, ?, ?, 1, ?)",
                (username, digest, salt, role, now_iso()),
            )
            row = user_row(connection, cursor.lastrowid)
    except sqlite3.IntegrityError:
        return response_error("Username is already in use", 409)
    return dict(row), 201


def update_user(user_id, data, current_user, current_token):
    role = data.get("role")
    active = data.get("active")
    if role is not None and role not in ROLES:
        return response_error("Invalid role", 400)
    if active is not None and not isinstance(active, bool):
        return response_error("Active must be true or false", 400)
    if user_id == current_user["id"] and (active is False or (role is not None and role != "admin")):
        return response_error("You cannot disable or demote your own administrator account", 400)
    with database() as connection:
        existing = user_row(connection, user_id)
        if existing is None:
            return response_error("User not found", 404)
        connection.execute(
            "UPDATE admin_users SET role = COALESCE(?, role), active = COALESCE(?, active) WHERE id = ?",
            (role, None if active is None else int(active), user_id),
        )
        row = user_row(connection, user_id)
    if active is False:
        revoke_sessions_for_user(user_id, keep_token=current_token)
    return dict(row), 200


def chat_reply(message):
    text = " ".join(str(message).casefold().split())
    with database() as connection:
        products = as_dicts(connection.execute("SELECT * FROM products ORDER BY name").fetchall())
        sales = connection.execute("SELECT amount, createdAt FROM sales").fetchall()
        profit = connection.execute(
            "SELECT COALESCE(SUM(lineProfit), 0) AS total, COUNT(*) AS knownLines FROM sale_items WHERE lineProfit IS NOT NULL"
        ).fetchone()
        sale_lines = connection.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0]

    if not text:
        return {"reply": "Type a question about stock, sales, or how to use CareMax.", "section": None}, 200

    sections = [
        (("dashboard", "home", "overview"), "dashboard", "Opening the dashboard for sales, inventory value, and low-stock alerts."),
        (("pos", "checkout"), "pos", "Opening the POS. Search for an item, add it to the cart, adjust quantities, choose payment, and complete the sale."),
        (("inventory",), "inventory", "Opening inventory. Add new products here; receive existing stock from POS using Stock Push and enter the supplier unit cost."),
        (("billing", "invoice"), "billing", "Opening billing to review invoices, payment methods, and payment status."),
        (("reports",), "reports", "Opening reports for revenue, gross profit, and stock alerts."),
    ]
    if text.startswith(("open ", "go to ", "take me to ", "show me ")):
        for keywords, section, reply in sections:
            if any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords):
                return {"reply": reply, "section": section}, 200

    matched_products = []
    generic_words = {"available", "availability", "in", "item", "items", "low", "medicine", "medicines", "medication", "product", "products", "stock"}
    for product in products:
        name = (product.get("name") or "").casefold()
        sku = (product.get("sku") or "").casefold()
        category = (product.get("category") or "").casefold()
        name_words = [word for word in re.findall(r"[a-z0-9]+", f"{name} {category}") if len(word) >= 3 and word not in generic_words]
        if (sku and sku in text) or (name and name in text) or any(
            re.search(rf"\b{re.escape(word)}\b", text) for word in name_words
        ):
            matched_products.append(product)

    if matched_products:
        details = []
        for product in matched_products[:5]:
            stock = int(product.get("stock") or 0)
            availability = f"{stock} in stock" if stock else "out of stock"
            price = float(product.get("price") or 0)
            expiry = product.get("expiry") or "not recorded"
            prescription = "prescription required" if product.get("prescriptionRequired") else "no prescription flag"
            details.append(f"{product['name']} ({product.get('sku') or 'no SKU'}): {availability}; price KSh {price:,.2f}; expiry {expiry}; {prescription}.")
        return {"reply": "Current inventory: " + " ".join(details), "section": "pos"}, 200

    if any(term in text for term in ("profit", "gross margin")):
        unknown = sale_lines - profit["knownLines"]
        return {
            "reply": f"Recorded gross profit is KSh {profit['total']:,.2f}. {unknown} sale lines have no known unit cost, so they are excluded from this figure.",
            "section": "reports",
        }, 200

    if any(term in text for term in ("expire", "expiry", "expiring")):
        items = [f"{product['name']}: {product['expiry']}" for product in products if product.get("expiry")]
        reply = "Recorded expiry dates: " + "; ".join(items[:8]) if items else "No product expiry dates are recorded yet."
        return {"reply": reply, "section": "inventory"}, 200

    if any(term in text for term in ("low stock", "running low", "almost out", "reorder")):
        low_stock = [product for product in products if int(product.get("stock") or 0) < 10]
        reply = "Low-stock items: " + "; ".join(f"{p['name']} ({p.get('stock', 0)} left)" for p in low_stock) if low_stock else "There are no low-stock items right now."
        return {"reply": reply, "section": "pos"}, 200

    if "today" in text and any(term in text for term in ("sale", "revenue", "total")):
        today = datetime.now().astimezone().date()
        today_sales = []
        for sale in sales:
            try:
                created = datetime.fromisoformat(sale["createdAt"].replace("Z", "+00:00")).astimezone().date()
            except (AttributeError, ValueError):
                continue
            if created == today:
                today_sales.append(sale)
        amount = sum(float(sale["amount"] or 0) for sale in today_sales)
        return {"reply": f"Today's sales: {len(today_sales)} transactions totaling KSh {amount:,.2f}.", "section": "dashboard"}, 200

    if any(term in text for term in ("revenue", "sales total", "total sales", "all sales")):
        amount = sum(float(sale["amount"] or 0) for sale in sales)
        return {"reply": f"Recorded revenue is KSh {amount:,.2f} across {len(sales)} sales.", "section": "reports"}, 200

    if any(term in text for term in ("receive", "restock", "supplier", "delivery")):
        return {
            "reply": "To receive existing stock, open POS, choose the item in Stock Push, enter the delivered quantity and supplier unit cost, then push stock. To add a new item, use Inventory > Add Product. Entering the unit cost is important for profit reports.",
            "section": "pos",
        }, 200

    if any(term in text for term in ("sale", "sell", "checkout", "cart")):
        return {
            "reply": "To complete a sale, open POS, search and select each product, adjust quantities in the cart, choose the payment method, set any discount, and select Complete Sale. Stock is deducted when the sale is recorded.",
            "section": "pos",
        }, 200

    if any(term in text for term in ("payment", "mobile money", "cash", "card")):
        return {
            "reply": "POS payment methods include Cash, Card, Mobile Money, and Insurance. Mobile Money currently demonstrates the phone/PIN prompt; it is not connected to a payment provider.",
            "section": "pos",
        }, 200

    inventory_words = ("stock", "inventory", "medicine", "medicines", "medication", "products", "items", "available", "availability", "quantity")
    if any(re.search(rf"\b{re.escape(word)}\b", text) for word in inventory_words):
        available = [product for product in products if int(product.get("stock") or 0) > 0]
        total_units = sum(int(product.get("stock") or 0) for product in products)
        listing = "; ".join(f"{p['name']} ({p.get('stock', 0)})" for p in products[:8])
        more = f"; and {len(products) - 8} more" if len(products) > 8 else ""
        return {
            "reply": f"There are {len(available)} products available, with {total_units} units total. Stock by product: {listing}{more}.",
            "section": "pos",
        }, 200

    for keywords, section, reply in sections:
        if any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords):
            return {"reply": reply, "section": section}, 200

    return {
        "reply": "I can answer current stock and price questions, list low-stock items or expiry dates, summarize sales and recorded profit, and guide POS, stock receiving, billing, and reports. Ask about a medicine by name or SKU, or tell me what you want to do.",
        "section": None,
    }, 200


class CareMaxHandler(BaseHTTPRequestHandler):
    def cookies(self):
        raw = self.headers.get("Cookie", "")
        result = {}
        for part in raw.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator:
                result[key] = value
        return result

    def current_user(self):
        return session_user(self.cookies().get(SESSION_COOKIE))

    def set_session_cookie(self, token, clear=False):
        value = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict" + ("; Max-Age=0" if clear else f"; Max-Age={SESSION_SECONDS}")
        self._session_cookie = value

    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_security_headers()
        if getattr(self, "_session_cookie", None):
            self.send_header("Set-Cookie", self._session_cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def send_frontend_file(self, filename):
        if filename not in {"index.html", "caremax_system_plan.html", "app.js", "styles.css"}:
            self.send_json({"error": "File not found"}, 404)
            return
        file_path = ROOT / filename
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "application/octet-stream")
        self.send_security_headers()
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            user = self.current_user()
            if path == "/api/auth/status":
                self.send_json(*auth_status(user))
                return
            if path == "/":
                self.send_frontend_file("index.html")
                return
            if path in STATIC_FILES:
                self.send_frontend_file(path.lstrip("/"))
                return
            if path.startswith("/api/payments/mpesa/"):
                denied = authorize(user, SELL_ROLES)
                self.send_json(*(denied or response_error("M-Pesa payments are recorded only by the CareMax Node deployment", 404)))
                return
            required = READ_ROUTES.get(path)
            if required:
                denied = authorize(user, required)
                if denied:
                    self.send_json(*denied)
                    return
            payload, status = get_data(path)
            if path == "/api/products" and status == 200 and (user is None or user["role"] not in MANAGER_ROLES):
                for product in payload:
                    product.pop("costPrice", None)
            self.send_json(payload, status)
        except Exception as exception:
            self.log_error("GET %s failed: %s", path, exception)
            self.send_json({"error": "Internal server error"}, 500)

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            data = self.read_json()
            user = self.current_user()
            if path == "/api/auth/setup":
                designated = setup_username()
                username = str(data.get("username") or designated or "admin").strip().lower()
                password = str(data.get("password", ""))
                if designated and username != designated:
                    payload, status = response_error("Only the designated administrator can complete initial setup", 403)
                elif len(password) < 12:
                    payload, status = response_error("Choose a password with at least 12 characters", 400)
                else:
                    digest, salt = hash_password(password)
                    user_id = None
                    with database() as connection:
                        if connection.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
                            payload, status = response_error("Initial administrator is already configured", 409)
                        else:
                            try:
                                cursor = connection.execute(
                                    "INSERT INTO admin_users (username, password_hash, password_salt, role, active, createdAt) VALUES (?, ?, ?, 'admin', 1, ?)",
                                    (username, digest, salt, now_iso()),
                                )
                            except sqlite3.IntegrityError:
                                payload, status = response_error("Username is already in use", 409)
                            else:
                                user_id = cursor.lastrowid
                                payload, status = {"ok": True, "user": {"id": user_id, "username": username, "role": "admin"}}, 201
                    if user_id is not None:
                        self.set_session_cookie(issue_session(user_id))
            elif path == "/api/auth/login":
                username = str(data.get("username") or "admin").strip().lower()
                password = str(data.get("password", ""))
                throttle_key = (self.client_address[0], username)
                if login_blocked(throttle_key):
                    payload, status = response_error("Too many failed sign-in attempts. Try again in a few minutes.", 429)
                else:
                    with database() as connection:
                        row = connection.execute(
                            "SELECT * FROM admin_users WHERE username = ? AND active = 1", (username,)
                        ).fetchone()
                    if row is None:
                        hash_password(password, DUMMY_SALT)
                        record_login_failure(throttle_key)
                        payload, status = response_error("Invalid username or password", 401)
                    elif not password_matches(password, row["password_salt"], row["password_hash"]):
                        record_login_failure(throttle_key)
                        payload, status = response_error("Invalid username or password", 401)
                    else:
                        clear_login_failures(throttle_key)
                        self.set_session_cookie(issue_session(row["id"]))
                        payload, status = {
                            "ok": True,
                            "user": {"id": row["id"], "username": row["username"], "role": row["role"]},
                        }, 200
            elif path == "/api/auth/logout":
                token = self.cookies().get(SESSION_COOKIE)
                if token:
                    with database() as connection:
                        connection.execute(
                            "DELETE FROM admin_sessions WHERE token_hash = ?",
                            (hashlib.sha256(token.encode("utf-8")).hexdigest(),),
                        )
                self.set_session_cookie("", clear=True)
                payload, status = {"ok": True}, 200
            elif path == "/api/chat":
                message = str(data.get("message", "")).strip()
                if not message:
                    payload, status = response_error("Type a question to get help", 400)
                else:
                    payload, status = chat_reply(message)
            elif path == "/api/payments/mpesa/stkpush":
                denied = authorize(user, SELL_ROLES)
                payload, status = denied or response_error(
                    "M-Pesa STK Push requires the CareMax Node deployment. Use Cash, Card, or Insurance locally.", 503
                )
            elif path == "/api/products":
                denied = authorize(user, MANAGER_ROLES)
                payload, status = denied or add_product(data)
            elif path == "/api/sales":
                denied = authorize(user, SELL_ROLES)
                payload, status = denied or create_sale(data, user)
            elif path == "/api/patients":
                denied = authorize(user, MANAGER_ROLES)
                payload, status = denied or add_patient(data)
            elif path == "/api/appointments":
                denied = authorize(user, MANAGER_ROLES)
                payload, status = denied or add_appointment(data)
            elif path == "/api/users":
                denied = authorize(user, ("admin",))
                payload, status = denied or create_user(data)
            else:
                payload, status = response_error("Not found", 404)
            self.send_json(payload, status)
        except (json.JSONDecodeError, ValueError):
            self.send_json({"error": "Invalid JSON request"}, 400)
        except Exception as exception:
            self.log_error("POST %s failed: %s", path, exception)
            self.send_json({"error": "Internal server error"}, 500)

    def do_PUT(self):
        path = urlsplit(self.path).path
        try:
            data = self.read_json()
            user = self.current_user()
            if path.startswith("/api/products/"):
                denied = authorize(user, MANAGER_ROLES)
                if denied:
                    self.send_json(*denied)
                    return
                if path.endswith("/stock"):
                    payload, status = receive_stock(int(path.split("/")[3]), data)
                else:
                    payload, status = update_product(int(path.split("/")[3]), data)
            elif path.startswith("/api/appointments/"):
                denied = authorize(user, MANAGER_ROLES)
                if denied:
                    self.send_json(*denied)
                    return
                appointment_id = int(path.split("/")[3])
                with database() as connection:
                    connection.execute("UPDATE appointments SET status = 'Completed' WHERE id = ?", (appointment_id,))
                    row = connection.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
                payload, status = (dict(row), 200) if row else response_error("Appointment not found", 404)
            else:
                payload, status = response_error("Not found", 404)
            self.send_json(payload, status)
        except (ValueError, IndexError):
            self.send_json({"error": "Invalid request"}, 400)
        except Exception as exception:
            self.log_error("PUT %s failed: %s", path, exception)
            self.send_json({"error": "Internal server error"}, 500)

    def do_PATCH(self):
        path = urlsplit(self.path).path
        try:
            data = self.read_json()
            user = self.current_user()
            denied = authorize(user, ("admin",))
            if denied:
                self.send_json(*denied)
                return
            if path.startswith("/api/users/"):
                payload, status = update_user(int(path.split("/")[3]), data, user,
                                              self.cookies().get(SESSION_COOKIE))
                self.send_json(payload, status)
                return
            self.send_json({"error": "Not found"}, 404)
        except (ValueError, IndexError):
            self.send_json({"error": "Invalid request"}, 400)
        except Exception as exception:
            self.log_error("PATCH %s failed: %s", path, exception)
            self.send_json({"error": "Internal server error"}, 500)


def create_server(host="127.0.0.1", port=5000):
    return ThreadingHTTPServer((host, port), CareMaxHandler)


def main():
    init_db()
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    server = create_server(host=host, port=port)
    print(f"CareMax Python server listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCareMax server stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
