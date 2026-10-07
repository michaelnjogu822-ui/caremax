import json
import mimetypes
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CAREMAX_DB_PATH", ROOT / "caremax.db"))


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
                expiry TEXT
            );
            CREATE TABLE IF NOT EXISTS sales (
                id TEXT PRIMARY KEY,
                patientId INTEGER,
                amount REAL,
                paymentMethod TEXT,
                createdAt TEXT,
                status TEXT
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
    except (KeyError, TypeError, ValueError):
        return response_error("Enter valid price, stock, and unit cost values", 400)
    if not name or not sku or price < 0 or stock < 0 or (cost_price is not None and cost_price < 0):
        return response_error("Name and SKU are required; prices and stock cannot be negative", 400)
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO products (name, sku, category, price, stock, expiry, costPrice) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, sku, data.get("category", ""), price, stock, data.get("expiry", ""), cost_price),
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


def create_sale(data):
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return response_error("Cart is empty", 400)
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
    payment_method = data.get("paymentMethod") or "Cash"
    with database() as connection:
        products = {}
        for product_id, quantity in quantities.items():
            product = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if product is None:
                return response_error("A product in the cart no longer exists", 400)
            if (product["stock"] or 0) < quantity:
                return response_error(f"Not enough stock for {product['name']}", 400)
            products[product_id] = product

        subtotal = sum(products[product_id]["price"] * quantity for product_id, quantity in quantities.items())
        total = subtotal - subtotal * discount / 100 + subtotal * 0.08
        connection.execute(
            "INSERT INTO sales (id, patientId, amount, paymentMethod, createdAt, status) VALUES (?, ?, ?, ?, ?, ?)",
            (sale_id, data.get("patientId"), total, payment_method, created_at, "Paid"),
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


def chat_reply(message):
    message = message.lower()
    intents = [
        (("pos", "sale", "checkout", "sell"), "pos", "Opening the POS. Search for an item, add it to the cart, then complete the sale."),
        (("inventory", "stock", "receive", "supplier", "item"), "inventory", "Opening inventory. Add a product or record a stock receipt with its supplier unit cost."),
        (("report", "profit", "revenue", "sales total"), "reports", "Opening reports. Gross profit uses recorded sale prices and known unit costs; older sales without cost records are excluded."),
        (("bill", "invoice", "payment"), "billing", "Opening billing to review invoices and payment status."),
        (("dashboard", "home", "overview"), "dashboard", "Opening the dashboard for today's sales, inventory value, and low-stock alerts."),
    ]
    for keywords, section, reply in intents:
        if any(keyword in message for keyword in keywords):
            return {"reply": reply, "section": section}, 200
    return {
        "reply": "I can take you to Dashboard, POS, Inventory, Billing, or Reports. Try asking to open one of those, or ask how to receive stock or complete a sale.",
        "section": None,
    }, 200


class CareMaxHandler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
        if filename not in {"index.html", "app.js", "styles.css"}:
            self.send_json({"error": "File not found"}, 404)
            return
        file_path = ROOT / filename
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/":
                self.send_frontend_file("index.html")
            elif path in {"/index.html", "/app.js", "/styles.css"}:
                self.send_frontend_file(path.lstrip("/"))
            else:
                payload, status = get_data(path)
                self.send_json(payload, status)
        except Exception as exception:
            self.log_error("GET %s failed: %s", path, exception)
            self.send_json({"error": "Internal server error"}, 500)

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            data = self.read_json()
            if path == "/api/products":
                payload, status = add_product(data)
            elif path == "/api/sales":
                payload, status = create_sale(data)
            elif path == "/api/patients":
                payload, status = add_patient(data)
            elif path == "/api/appointments":
                payload, status = add_appointment(data)
            elif path == "/api/chat":
                message = str(data.get("message", "")).strip()
                if not message:
                    payload, status = response_error("Type a question to get help", 400)
                else:
                    payload, status = chat_reply(message)
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
            if path.startswith("/api/products/") and path.endswith("/stock"):
                product_id = int(path.split("/")[3])
                payload, status = receive_stock(product_id, data)
            elif path.startswith("/api/appointments/"):
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


def create_server(host="127.0.0.1", port=5000):
    return ThreadingHTTPServer((host, port), CareMaxHandler)


def main():
    init_db()
    port = int(os.environ.get("PORT", "5000"))
    server = create_server(port=port)
    print(f"CareMax Python server running at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCareMax server stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
