"""Shared fixture for CareMax Python server tests.

Each test gets an isolated SQLite database and an HTTP server on a random port.
Temporary directories are created under the project instead of the system temp
directory, because the workspace sandbox can deny writes to directories that
were created with restrictive permissions.
"""

import http.client
import importlib.util
import json
import os
import secrets
import shutil
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSWORD = "correct-horse-battery-staple"
STAFF_PASSWORD = "staff-password-123"


def _temp_dir():
    base = ROOT / ".test-tmp"
    base.mkdir(exist_ok=True)
    path = base / f"run-{secrets.token_hex(4)}"
    path.mkdir()
    return path


def load_server_module():
    spec = importlib.util.spec_from_file_location(
        f"caremax_server_under_test_{secrets.token_hex(4)}", ROOT / "server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Reply:
    def __init__(self, status, data, set_cookie):
        self.status = status
        self.data = data
        self.set_cookie = set_cookie

    @property
    def cookie(self):
        if not self.set_cookie:
            return None
        return self.set_cookie.split(";", 1)[0]

    def __repr__(self):
        return f"Reply(status={self.status}, data={self.data!r})"


class CareMaxServer:
    def __init__(self, admin_password=ADMIN_PASSWORD):
        self.directory = _temp_dir()
        self._env_backup = {
            name: os.environ.pop(name)
            for name in ("ADMIN_EMAIL", "CAREMAX_ADMIN_EMAIL")
            if name in os.environ
        }
        self.module = load_server_module()
        self.module.DB_PATH = self.directory / "test.db"
        # Keep the suite fast; production runs the full PBKDF2 work factor.
        self.module.PASSWORD_ITERATIONS = 1_000
        self.module.init_db()
        self.server = self.module.create_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.admin_password = admin_password
        self.admin_cookie = None

    def start(self, setup=True):
        if setup:
            reply = self.request("POST", "/api/auth/setup", {"password": self.admin_password})
            if reply.status != 201:
                raise AssertionError(f"Administrator setup failed: {reply!r}")
            self.admin_cookie = reply.cookie
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.directory, ignore_errors=True)
        os.environ.update(self._env_backup)

    def request(self, method, path, body=None, cookie=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        payload = json.dumps(body) if body is not None else None
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
            set_cookie = response.getheader("Set-Cookie")
        finally:
            connection.close()
        data = json.loads(raw.decode("utf-8")) if raw else None
        return Reply(status, data, set_cookie)

    def sign_in(self, username, password=STAFF_PASSWORD):
        reply = self.request("POST", "/api/auth/login", {"username": username, "password": password})
        return reply, reply.cookie

    def create_staff(self, username, role, password=STAFF_PASSWORD):
        reply = self.request(
            "POST",
            "/api/users",
            {"username": username, "password": password, "role": role},
            cookie=self.admin_cookie,
        )
        if reply.status != 201:
            raise AssertionError(f"Could not create {role} {username}: {reply!r}")
        return reply.data

    def staff_session(self, username, role, password=STAFF_PASSWORD):
        self.create_staff(username, role, password)
        reply, cookie = self.sign_in(username, password)
        if reply.status != 200:
            raise AssertionError(f"Could not sign in {username}: {reply!r}")
        return cookie

    def create_product(self, sku, price=100, stock=10, cost_price=40, expiry="", prescription=0, cookie=None):
        reply = self.request(
            "POST",
            "/api/products",
            {
                "name": f"Test product {sku}",
                "sku": sku,
                "category": "Testing",
                "price": price,
                "stock": stock,
                "costPrice": cost_price,
                "expiry": expiry,
                "prescriptionRequired": prescription,
            },
            cookie=cookie or self.admin_cookie,
        )
        if reply.status != 201:
            raise AssertionError(f"Could not create product {sku}: {reply!r}")
        return reply.data

    def sell(self, product_id, quantity=1, cookie=None, discount=0, **extra):
        body = {
            "items": [{"productId": product_id, "quantity": quantity}],
            "paymentMethod": "Cash",
            "discount": discount,
        }
        body.update(extra)
        return self.request("POST", "/api/sales", body, cookie=cookie or self.admin_cookie)
