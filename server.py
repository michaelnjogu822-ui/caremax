import json
import mimetypes
import os
import re
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
            details.append(f"{product['name']} ({product.get('sku') or 'no SKU'}): {availability}; price KSh {price:,.2f}; expiry {expiry}.")
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
        if filename not in {"index.html", "caremax_system_plan.html", "app.js", "styles.css"}:
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
            elif path in {"/index.html", "/caremax_system_plan.html", "/app.js", "/styles.css"}:
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
