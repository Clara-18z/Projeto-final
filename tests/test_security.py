import os
import re
import tempfile
import unittest

from app import create_app
from database import db
from database.models import Usuario
from werkzeug.security import check_password_hash, generate_password_hash


class SecurityConfigurationTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, "security.db").replace("\\", "/")
        self.app = create_app(
            {
                "TESTING": True,
                "APP_ENV": "test",
                "SECRET_KEY": "isolated-test-secret",
                "ADMIN_INITIAL_PASSWORD": "Isolated-Initial-Password-123!",
                "WTF_CSRF_ENABLED": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _login_csrf_token(self):
        response = self.client.get("/login")
        match = re.search(
            r'name="csrf_token"\s+value="([^"]+)"',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def test_login_page_starts_empty_and_disables_browser_autofill(self):
        body = self.client.get("/login").get_data(as_text=True)
        self.assertIn("<span>Financeiro</span>", body)
        self.assertIn('autocomplete="off"', body)
        self.assertIn('data-clear-fields="true"', body)
        self.assertIn("window.addEventListener(\"pageshow\", clearLoginFields)", body)
        for field_id in ("identifier", "password"):
            field = re.search(rf'<input[^>]*id="{field_id}"[^>]*>', body)
            self.assertIsNotNone(field)
            self.assertIn("readonly", field.group(0))
            self.assertNotIn("value=", field.group(0))
        self.assertNotIn("Isolated-Initial-Password-123!", body)

    def test_login_requires_csrf_and_rejects_external_next_url(self):
        response = self.client.post(
            "/login",
            data={
                "identifier": "admin",
                "password": "Isolated-Initial-Password-123!",
            },
        )
        self.assertEqual(response.status_code, 400)

        csrf_token = self._login_csrf_token()
        response = self.client.post(
            "/login?next=https://attacker.example",
            data={
                "identifier": "admin",
                "password": "Isolated-Initial-Password-123!",
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")

    def test_invalid_or_inactive_login_redirects_to_empty_login_form(self):
        with self.app.app_context():
            admin = Usuario.query.filter_by(username="admin").one()
            admin.ativo = False
            db.session.commit()

        attempts = (
            ("unknown-user-to-clear", "Invalid-Password-123!"),
            ("admin", "Isolated-Initial-Password-123!"),
        )
        for identifier, password in attempts:
            with self.subTest(identifier=identifier):
                response = self.client.post(
                    "/login",
                    data={
                        "identifier": identifier,
                        "password": password,
                        "csrf_token": self._login_csrf_token(),
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/login?clear=1")

                page = self.client.get(response.headers["Location"])
                body = page.get_data(as_text=True)
                self.assertIn("Credenciais inválidas ou usuário inativo.", body)
                self.assertNotIn(f'value="{identifier}"', body)
                self.assertNotIn(password, body)
                self.assertIn('data-clear-fields="true"', body)
                self.assertGreaterEqual(body.count('autocomplete="off"'), 3)
                identifier_input = re.search(r'<input[^>]*id="identifier"[^>]*>', body)
                password_input = re.search(r'<input[^>]*id="password"[^>]*>', body)
                self.assertIsNotNone(identifier_input)
                self.assertIsNotNone(password_input)
                self.assertIn("readonly", identifier_input.group(0))
                self.assertIn("readonly", password_input.group(0))
                self.assertNotIn("value=", identifier_input.group(0))
                self.assertNotIn("value=", password_input.group(0))

    def test_login_does_not_create_persistent_remember_cookie(self):
        csrf_token = self._login_csrf_token()
        response = self.client.post(
            "/login",
            data={
                "identifier": "admin",
                "password": "Isolated-Initial-Password-123!",
                "csrf_token": csrf_token,
            },
        )
        cookies = response.headers.getlist("Set-Cookie")
        remember_cookies = [
            cookie for cookie in cookies if cookie.startswith("remember_token=")
        ]
        self.assertTrue(
            all("Max-Age=0" in cookie for cookie in remember_cookies)
        )

    def test_debug_permission_endpoint_is_not_exposed(self):
        csrf_token = self._login_csrf_token()
        self.client.post(
            "/login",
            data={
                "identifier": "admin",
                "password": "Isolated-Initial-Password-123!",
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(self.client.get("/teste-permissoes").status_code, 404)

    def test_logout_requires_post_and_csrf(self):
        csrf_token = self._login_csrf_token()
        login = self.client.post(
            "/login",
            data={
                "identifier": "admin",
                "password": "Isolated-Initial-Password-123!",
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(login.status_code, 302)
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout").status_code, 400)

        dashboard = self.client.get("/dashboard")
        match = re.search(
            r'name="csrf_token"\s+value="([^"]+)"',
            dashboard.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        logout = self.client.post(
            "/logout",
            data={"csrf_token": match.group(1)},
            follow_redirects=False,
        )
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(logout.headers["Location"], "/login")

    def test_security_response_headers_are_set(self):
        response = self.client.get("/health")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_homepage_uses_working_routes_and_no_mock_metrics(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('href="/login"', body)
        self.assertIn('href="/painel"', body)
        self.assertNotIn('href="#"', body)
        self.assertNotIn("1.248", body)
        self.assertNotIn("Etapas previstas", body)
        self.assertNotIn("fonts.googleapis.com", body)

    def test_readiness_endpoint_checks_database(self):
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ready"})

    def test_production_requires_secret_and_initial_admin_password(self):
        with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
            create_app(
                {
                    "APP_ENV": "production",
                    "SECRET_KEY": None,
                    "ADMIN_INITIAL_PASSWORD": "production-admin-password",
                    "SQLALCHEMY_DATABASE_URI": "sqlite://",
                }
            )
        with self.assertRaisesRegex(RuntimeError, "ADMIN_INITIAL_PASSWORD"):
            create_app(
                {
                    "APP_ENV": "production",
                    "SECRET_KEY": "production-secret",
                    "ADMIN_INITIAL_PASSWORD": None,
                    "SQLALCHEMY_DATABASE_URI": "sqlite://",
                }
            )

    def test_production_disables_debug_and_requires_secure_session_cookies(self):
        app = create_app(
            {
                "APP_ENV": "production",
                "DEBUG": True,
                "SECRET_KEY": "production-secret",
                "ADMIN_INITIAL_PASSWORD": "production-admin-password",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )
        def dispose_database():
            with app.app_context():
                db.engine.dispose()

        self.addCleanup(dispose_database)
        self.assertFalse(app.config["DEBUG"])
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        self.assertTrue(app.config["REMEMBER_COOKIE_SECURE"])

    def test_startup_does_not_reset_existing_admin_password(self):
        with self.app.app_context():
            admin = Usuario.query.filter_by(username="admin").one()
            admin.senha_hash = generate_password_hash("A user-selected password!")
            db.session.commit()

            from app import seed_default_admin_user

            seed_default_admin_user()
            db.session.refresh(admin)
            self.assertTrue(check_password_hash(admin.senha_hash, "A user-selected password!"))


if __name__ == "__main__":
    unittest.main()
