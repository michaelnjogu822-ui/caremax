import unittest

from caremax_test_support import ADMIN_PASSWORD, STAFF_PASSWORD, CareMaxServer


class StaffRoleTests(unittest.TestCase):
    def setUp(self):
        self.api = CareMaxServer().start()

    def tearDown(self):
        self.api.close()

    def test_cashier_can_sell_but_not_manage_inventory_or_reports(self):
        cookie = self.api.staff_session("cashier1", "cashier")
        product = self.api.create_product("CASH-1", price=100, stock=5)

        catalog = self.api.request("GET", "/api/products", cookie=cookie)
        self.assertEqual(catalog.status, 200)
        self.assertNotIn("costPrice", catalog.data[0])

        sale = self.api.sell(product["id"], 1, cookie=cookie)
        self.assertEqual(sale.status, 201)

        self.assertEqual(self.api.request("GET", "/api/reports", cookie=cookie).status, 403)
        self.assertEqual(self.api.request("GET", "/api/patients", cookie=cookie).status, 403)
        self.assertEqual(self.api.request("GET", "/api/users", cookie=cookie).status, 403)
        self.assertEqual(
            self.api.request("POST", "/api/products", {"name": "X", "sku": "NOPE", "price": 1, "stock": 1}, cookie=cookie).status,
            403,
        )
        self.assertEqual(
            self.api.request("PUT", f"/api/products/{product['id']}/stock", {"quantity": 1, "unitCost": 1}, cookie=cookie).status,
            403,
        )

    def test_viewer_reads_reports_but_cannot_sell(self):
        cookie = self.api.staff_session("viewer1", "viewer")
        product = self.api.create_product("VIEW-1")
        self.assertEqual(self.api.request("GET", "/api/reports", cookie=cookie).status, 200)
        self.assertEqual(self.api.request("GET", "/api/sales", cookie=cookie).status, 200)
        self.assertEqual(self.api.sell(product["id"], 1, cookie=cookie).status, 403)

    def test_pharmacist_can_manage_inventory_and_records(self):
        cookie = self.api.staff_session("pharmacist1", "pharmacist")
        product = self.api.request(
            "POST",
            "/api/products",
            {"name": "Pharmacist item", "sku": "PHARM-1", "price": 50, "stock": 4, "costPrice": 20},
            cookie=cookie,
        )
        self.assertEqual(product.status, 201)
        patient = self.api.request("POST", "/api/patients", {"name": "Jane Doe"}, cookie=cookie)
        self.assertEqual(patient.status, 201)
        self.assertEqual(self.api.request("GET", "/api/reports", cookie=cookie).status, 200)


class SalesMathTests(unittest.TestCase):
    def setUp(self):
        self.api = CareMaxServer().start()

    def tearDown(self):
        self.api.close()

    def test_totals_are_tax_free_and_profit_uses_the_discount(self):
        product = self.api.create_product("TAX-1", price=100, stock=10, cost_price=40)
        before = self.api.request("GET", "/api/reports", cookie=self.api.admin_cookie).data

        sale = self.api.sell(product["id"], 2, discount=10)
        self.assertEqual(sale.status, 201)
        self.assertEqual(sale.data["total"], 180)

        invoices = self.api.request("GET", "/api/invoices", cookie=self.api.admin_cookie).data
        self.assertEqual(invoices[0]["total"], 180)
        self.assertEqual(invoices[0]["paymentMethod"], "Cash")

        after = self.api.request("GET", "/api/reports", cookie=self.api.admin_cookie).data
        self.assertEqual(after["revenue"] - before["revenue"], 180)
        self.assertAlmostEqual(after["grossProfit"] - before["grossProfit"], (90 - 40) * 2, places=2)

        stock = self.api.request("GET", "/api/products").data
        remaining = next(item for item in stock if item["sku"] == "TAX-1")
        self.assertEqual(remaining["stock"], 8)

    def test_expired_stock_is_blocked(self):
        product = self.api.create_product("EXPIRED-1", expiry="2020-01-31")
        sale = self.api.sell(product["id"])
        self.assertEqual(sale.status, 400)
        self.assertIn("expired", sale.data["error"])

    def test_unavailable_stock_is_blocked(self):
        product = self.api.create_product("LOW-1", stock=1)
        sale = self.api.sell(product["id"], 3)
        self.assertEqual(sale.status, 400)

    def test_mpesa_sales_must_use_the_stk_push_flow(self):
        product = self.api.create_product("MPESA-1")
        sale = self.api.sell(product["id"], paymentMethod="M-Pesa")
        self.assertEqual(sale.status, 400)

    def test_stk_push_reports_the_node_deployment_requirement(self):
        reply = self.api.request(
            "POST",
            "/api/payments/mpesa/stkpush",
            {"items": [{"productId": 1, "quantity": 1}], "phone": "0712345678"},
            cookie=self.api.admin_cookie,
        )
        self.assertEqual(reply.status, 503)
        self.assertIn("Node deployment", reply.data["error"])


class PrescriptionTests(unittest.TestCase):
    def setUp(self):
        self.api = CareMaxServer().start()

    def tearDown(self):
        self.api.close()

    def test_prescription_sale_needs_verification_and_a_pharmacist(self):
        product = self.api.create_product("RX-1", prescription=1)
        self.assertEqual(self.api.sell(product["id"]).status, 400)

        cashier = self.api.staff_session("cashier-rx", "cashier")
        blocked = self.api.sell(product["id"], cookie=cashier, prescriptionVerified=True)
        self.assertEqual(blocked.status, 403)

        pharmacist = self.api.staff_session("pharmacist-rx", "pharmacist")
        allowed = self.api.sell(product["id"], cookie=pharmacist, prescriptionVerified=True)
        self.assertEqual(allowed.status, 201)

    def test_non_prescription_sale_needs_no_verification(self):
        product = self.api.create_product("OTC-1", prescription=0)
        self.assertEqual(self.api.sell(product["id"]).status, 201)


class StockReceiptTests(unittest.TestCase):
    def setUp(self):
        self.api = CareMaxServer().start()

    def tearDown(self):
        self.api.close()

    def test_receiving_stock_averages_the_supplier_cost(self):
        product = self.api.create_product("STOCK-1", price=100, stock=10, cost_price=40)
        reply = self.api.request(
            "PUT", f"/api/products/{product['id']}/stock", {"quantity": 10, "unitCost": 60}, cookie=self.api.admin_cookie
        )
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.data["stock"], 20)
        self.assertAlmostEqual(reply.data["costPrice"], 50, places=4)

    def test_receiving_stock_rejects_invalid_quantities(self):
        product = self.api.create_product("STOCK-2")
        for quantity, unit_cost in ((0, 10), (-2, 10), (2, -1), (1.5, 10)):
            with self.subTest(quantity=quantity, unit_cost=unit_cost):
                reply = self.api.request(
                    "PUT",
                    f"/api/products/{product['id']}/stock",
                    {"quantity": quantity, "unitCost": unit_cost},
                    cookie=self.api.admin_cookie,
                )
                self.assertEqual(reply.status, 400)


class UserManagementTests(unittest.TestCase):
    def setUp(self):
        self.api = CareMaxServer().start()

    def tearDown(self):
        self.api.close()

    def test_user_list_hides_credentials(self):
        self.api.create_staff("listed", "viewer")
        users = self.api.request("GET", "/api/users", cookie=self.api.admin_cookie)
        self.assertEqual(users.status, 200)
        self.assertEqual(len(users.data), 2)
        for user in users.data:
            self.assertNotIn("password_hash", user)
            self.assertNotIn("password_salt", user)
            self.assertIn("created_at", user)
            self.assertIn("active", user)

    def test_new_users_cannot_be_administrators(self):
        reply = self.api.request(
            "POST", "/api/users", {"username": "wannabe", "password": STAFF_PASSWORD, "role": "admin"}, cookie=self.api.admin_cookie
        )
        self.assertEqual(reply.status, 400)

    def test_invalid_role_is_rejected(self):
        reply = self.api.request(
            "POST", "/api/users", {"username": "weird", "password": STAFF_PASSWORD, "role": "owner"}, cookie=self.api.admin_cookie
        )
        self.assertEqual(reply.status, 400)

    def test_short_passwords_are_rejected(self):
        reply = self.api.request(
            "POST", "/api/users", {"username": "shorty", "password": "short", "role": "cashier"}, cookie=self.api.admin_cookie
        )
        self.assertEqual(reply.status, 400)

    def test_duplicate_usernames_are_rejected(self):
        self.api.create_staff("duplicate", "cashier")
        reply = self.api.request(
            "POST", "/api/users", {"username": "duplicate", "password": STAFF_PASSWORD, "role": "viewer"}, cookie=self.api.admin_cookie
        )
        self.assertEqual(reply.status, 409)

    def test_administrator_cannot_demote_their_own_account(self):
        me = self.api.request("GET", "/api/users", cookie=self.api.admin_cookie).data[0]
        reply = self.api.request("PATCH", f"/api/users/{me['id']}", {"role": "cashier"}, cookie=self.api.admin_cookie)
        self.assertEqual(reply.status, 400)
        reply = self.api.request("PATCH", f"/api/users/{me['id']}", {"active": False}, cookie=self.api.admin_cookie)
        self.assertEqual(reply.status, 400)

    def test_disabling_a_user_revokes_their_session(self):
        created = self.api.create_staff("temp-staff", "cashier")
        reply, cookie = self.api.sign_in("temp-staff")
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.api.request("GET", "/api/products", cookie=cookie).status, 200)

        disabled = self.api.request(
            "PATCH", f"/api/users/{created['id']}", {"active": False}, cookie=self.api.admin_cookie
        )
        self.assertEqual(disabled.status, 200)
        self.assertEqual(disabled.data["active"], 0)

        self.assertEqual(self.api.request("GET", "/api/products", cookie=cookie).status, 200)
        self.assertEqual(self.api.request("POST", "/api/sales", {"items": [{"productId": 1, "quantity": 1}]}, cookie=cookie).status, 401)

    def test_roles_can_be_changed(self):
        created = self.api.create_staff("promoted", "cashier")
        reply = self.api.request("PATCH", f"/api/users/{created['id']}", {"role": "pharmacist"}, cookie=self.api.admin_cookie)
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.data["role"], "pharmacist")
        self.assertEqual(self.api.request("PATCH", f"/api/users/{created['id']}", {"role": "nope"}, cookie=self.api.admin_cookie).status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
