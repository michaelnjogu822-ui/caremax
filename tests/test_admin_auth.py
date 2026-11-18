import os
import unittest

from caremax_test_support import ADMIN_PASSWORD, STAFF_PASSWORD, CareMaxServer


class AuthLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.api = CareMaxServer()

    def tearDown(self):
        self.api.close()

    def test_status_reports_setup_required_before_first_account(self):
        reply = self.api.request("GET", "/api/auth/status")
        self.assertEqual(reply.status, 200)
        self.assertTrue(reply.data["setupRequired"])
        self.assertFalse(reply.data["authenticated"])
        self.assertIsNone(reply.data["role"])

    def test_setup_enforces_password_policy_and_issues_strict_cookie(self):
        reply = self.api.request("POST", "/api/auth/setup", {"password": "short"})
        self.assertEqual(reply.status, 400)

        reply = self.api.request("POST", "/api/auth/setup", {"password": ADMIN_PASSWORD})
        self.assertEqual(reply.status, 201)
        self.assertEqual(reply.data["user"]["role"], "admin")
        self.assertIn("HttpOnly", reply.set_cookie)
        self.assertIn("SameSite=Strict", reply.set_cookie)

        status = self.api.request("GET", "/api/auth/status", cookie=reply.cookie)
        self.assertTrue(status.data["authenticated"])
        self.assertEqual(status.data["role"], "admin")
        self.assertFalse(status.data["setupRequired"])

    def test_initial_setup_can_only_run_once(self):
        self.api.start()
        reply = self.api.request("POST", "/api/auth/setup", {"password": ADMIN_PASSWORD})
        self.assertEqual(reply.status, 409)

    def test_designated_admin_email_restricts_first_setup(self):
        os.environ["ADMIN_EMAIL"] = "owner@caremax.test"
        try:
            status = self.api.request("GET", "/api/auth/status")
            self.assertEqual(status.data["setupUsername"], "owner@caremax.test")

            reply = self.api.request(
                "POST", "/api/auth/setup", {"username": "someone-else", "password": ADMIN_PASSWORD}
            )
            self.assertEqual(reply.status, 403)

            reply = self.api.request(
                "POST", "/api/auth/setup", {"username": "owner@caremax.test", "password": ADMIN_PASSWORD}
            )
            self.assertEqual(reply.status, 201)
            self.assertEqual(reply.data["user"]["username"], "owner@caremax.test")
        finally:
            os.environ.pop("ADMIN_EMAIL", None)


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.api = CareMaxServer().start()

    def tearDown(self):
        self.api.close()

    def test_public_catalog_and_chat_work_without_login(self):
        products = self.api.request("GET", "/api/products")
        self.assertEqual(products.status, 200)
        self.assertTrue(products.data)
        self.assertNotIn("costPrice", products.data[0])

        chat = self.api.request("POST", "/api/chat", {"message": "low stock"})
        self.assertEqual(chat.status, 200)
        self.assertIn("reply", chat.data)

    def test_records_require_login(self):
        for path in ("/api/sales", "/api/invoices", "/api/reports", "/api/patients", "/api/appointments", "/api/users"):
            with self.subTest(path=path):
                self.assertEqual(self.api.request("GET", path).status, 401)

    def test_writes_require_login(self):
        product = self.api.request("POST", "/api/products", {"name": "X", "sku": "X1", "price": 1, "stock": 1})
        self.assertEqual(product.status, 401)
        stock = self.api.request("PUT", "/api/products/1/stock", {"quantity": 1, "unitCost": 1})
        self.assertEqual(stock.status, 401)
        sale = self.api.request("POST", "/api/sales", {"items": [{"productId": 1, "quantity": 1}]})
        self.assertEqual(sale.status, 401)
        user = self.api.request("POST", "/api/users", {"username": "sneaky", "password": STAFF_PASSWORD, "role": "viewer"})
        self.assertEqual(user.status, 401)

    def test_invalid_credentials_are_rejected(self):
        reply, _ = self.api.sign_in("admin", "wrong-password-entirely")
        self.assertEqual(reply.status, 401)
        reply, _ = self.api.sign_in("nobody", STAFF_PASSWORD)
        self.assertEqual(reply.status, 401)

    def test_repeated_failures_are_throttled(self):
        for _ in range(5):
            self.api.sign_in("admin", "wrong-password-entirely")
        reply, _ = self.api.sign_in("admin", "wrong-password-entirely")
        self.assertEqual(reply.status, 429)

    def test_logout_revokes_the_session(self):
        reply = self.api.request("POST", "/api/auth/logout", {}, cookie=self.api.admin_cookie)
        self.assertEqual(reply.status, 200)
        self.assertIn("Max-Age=0", reply.set_cookie)
        self.assertEqual(self.api.request("GET", "/api/reports", cookie=self.api.admin_cookie).status, 401)


class OwnerAccessTests(unittest.TestCase):
    def setUp(self):
        self.api = CareMaxServer().start()

    def tearDown(self):
        self.api.close()

    def test_owner_can_manage_stock_and_read_profit(self):
        reports = self.api.request("GET", "/api/reports", cookie=self.api.admin_cookie)
        self.assertEqual(reports.status, 200)
        self.assertIn("grossProfit", reports.data)

        product = self.api.create_product("AUTH-TEST", price=10, stock=3, cost_price=4)
        self.assertEqual(product["costPrice"], 4)

        updated = self.api.request(
            "PUT", f"/api/products/{product['id']}", {"name": "Renamed", "sku": "AUTH-TEST", "price": 12}, cookie=self.api.admin_cookie
        )
        self.assertEqual(updated.status, 200)
        self.assertEqual(updated.data["name"], "Renamed")

    def test_costs_are_hidden_from_anonymous_visitors(self):
        self.api.create_product("COST-HIDDEN")
        products = self.api.request("GET", "/api/products")
        for product in products.data:
            self.assertNotIn("costPrice", product)


if __name__ == "__main__":
    unittest.main(verbosity=2)
