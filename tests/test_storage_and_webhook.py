"""Tests for the license store + Stripe webhook handler."""

from __future__ import annotations

import json
import tempfile

import pytest

from hvac_mcp import webhook
from hvac_mcp.storage import LICENSE_KEY_PREFIX, LicenseStore


@pytest.fixture
def tmp_store(monkeypatch) -> LicenseStore:
    """Isolated on-disk store per test. Uses HVAC_MCP_DATA_DIR so the
    webhook handler (which constructs its own LicenseStore) points at the
    same path."""
    d = tempfile.mkdtemp()
    monkeypatch.setenv("HVAC_MCP_DATA_DIR", d)
    yield LicenseStore()


# ─── Storage ────────────────────────────────────────────────────────────────


class TestStorage:
    def test_issue_creates_active_license(self, tmp_store) -> None:
        lic = tmp_store.issue(tier="starter", stripe_customer_id="cus_x", stripe_session_id="cs_1")
        assert lic.tier == "starter"
        assert lic.status == "active"
        assert lic.key.startswith(LICENSE_KEY_PREFIX)
        assert len(lic.key) >= 20

    def test_issue_is_idempotent_on_session_id(self, tmp_store) -> None:
        a = tmp_store.issue(tier="pro", stripe_customer_id="cus_x", stripe_session_id="cs_same")
        b = tmp_store.issue(tier="pro", stripe_customer_id="cus_x", stripe_session_id="cs_same")
        assert a.key == b.key  # same license returned, not a duplicate row

    def test_keys_are_unique_across_sessions(self, tmp_store) -> None:
        keys = {
            tmp_store.issue(
                tier="starter", stripe_customer_id="cus_x", stripe_session_id=f"cs_{i}"
            ).key
            for i in range(10)
        }
        assert len(keys) == 10  # no collisions

    def test_get_returns_license(self, tmp_store) -> None:
        lic = tmp_store.issue(tier="lifetime", stripe_customer_id="cus_y", stripe_session_id="cs_y")
        assert tmp_store.get(lic.key) == lic

    def test_get_missing_returns_none(self, tmp_store) -> None:
        assert tmp_store.get("hvac_does_not_exist") is None

    def test_is_active(self, tmp_store) -> None:
        lic = tmp_store.issue(tier="starter", stripe_customer_id="cus_z", stripe_session_id="cs_z")
        assert tmp_store.is_active(lic.key)
        tmp_store.set_status_for_customer("cus_z", "cancelled")
        assert not tmp_store.is_active(lic.key)

    def test_cancel_by_customer_updates_all_their_licenses(self, tmp_store) -> None:
        a = tmp_store.issue(
            tier="starter", stripe_customer_id="cus_multi", stripe_session_id="cs_a"
        )
        b = tmp_store.issue(tier="pro", stripe_customer_id="cus_multi", stripe_session_id="cs_b")
        n = tmp_store.set_status_for_customer("cus_multi", "cancelled")
        assert n == 2
        assert tmp_store.get(a.key).status == "cancelled"
        assert tmp_store.get(b.key).status == "cancelled"


# ─── Licensing integration ──────────────────────────────────────────────────


class TestLicensingAgainstStore:
    def test_licensed_when_store_has_active_key(self, tmp_store, monkeypatch) -> None:
        from hvac_mcp.licensing import is_licensed

        lic = tmp_store.issue(
            tier="pro", stripe_customer_id="cus_live", stripe_session_id="cs_live"
        )
        monkeypatch.setenv("HVAC_MCP_LICENSE_KEY", lic.key)
        assert is_licensed() is True

    def test_unlicensed_when_key_revoked(self, tmp_store, monkeypatch) -> None:
        from hvac_mcp.licensing import is_licensed

        lic = tmp_store.issue(tier="pro", stripe_customer_id="cus_cx", stripe_session_id="cs_cx")
        tmp_store.set_status_for_customer("cus_cx", "cancelled")
        monkeypatch.setenv("HVAC_MCP_LICENSE_KEY", lic.key)
        assert is_licensed() is False


# ─── Tier detection from session payload ────────────────────────────────────


class TestTierExtraction:
    def test_tier_from_price_metadata(self) -> None:
        session = {
            "line_items": {
                "data": [{"price": {"metadata": {"tier": "starter"}, "product": {"metadata": {}}}}]
            }
        }
        assert webhook._tier_from_session(session) == "starter"

    def test_tier_from_product_metadata(self) -> None:
        session = {
            "line_items": {
                "data": [{"price": {"metadata": {}, "product": {"metadata": {"tier": "pro"}}}}]
            }
        }
        assert webhook._tier_from_session(session) == "pro"

    def test_tier_from_amount_fallback(self) -> None:
        session = {"line_items": {"data": []}, "amount_total": 39900}
        assert webhook._tier_from_session(session) == "lifetime"

    def test_unknown_tier_returns_none(self) -> None:
        session = {"line_items": {"data": []}, "amount_total": 1234}
        assert webhook._tier_from_session(session) is None


# ─── Webhook signature verification ─────────────────────────────────────────


class TestSignatureVerification:
    def test_missing_secret_raises_runtime_error(self, monkeypatch) -> None:
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="not configured"):
            webhook._verify_and_parse(b"{}", "sig")

    def test_missing_header_raises_value_error(self, monkeypatch) -> None:
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
        with pytest.raises(ValueError, match="missing Stripe-Signature"):
            webhook._verify_and_parse(b"{}", None)

    def test_bad_signature_raises_value_error(self, monkeypatch) -> None:
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
        with pytest.raises(ValueError, match="signature verification failed"):
            webhook._verify_and_parse(b'{"id":"evt_x"}', "t=1,v1=definitely_bad")


# ─── End-to-end webhook handler ─────────────────────────────────────────────


def _fake_event(event_type: str, object_dict: dict) -> dict:
    return {"id": "evt_fake", "type": event_type, "data": {"object": object_dict}}


class TestWebhookHandler:
    """Bypass signature verification via monkeypatching and exercise the
    dispatch logic directly."""

    @pytest.fixture
    def handler_with_store(self, tmp_store, monkeypatch):
        async def _run(event: dict):
            from starlette.requests import Request

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            req = Request(
                scope={
                    "type": "http",
                    "method": "POST",
                    "path": "/stripe/webhook",
                    "headers": [],
                    "query_string": b"",
                },
                receive=receive,
            )
            # Patch signature check to return our fake event regardless.
            monkeypatch.setattr(webhook, "_verify_and_parse", lambda body, sig: event)
            return await webhook.stripe_webhook(req)

        return _run

    @pytest.mark.asyncio
    async def test_checkout_completed_issues_license(self, handler_with_store, tmp_store) -> None:
        event = _fake_event(
            "checkout.session.completed",
            {
                "id": "cs_test_e2e",
                "customer": "cus_e2e",
                "amount_total": 2900,
                "line_items": {"data": []},
            },
        )
        resp = await handler_with_store(event)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["issued"] is True
        assert body["key"].startswith(LICENSE_KEY_PREFIX)
        # Store actually persisted it
        assert tmp_store.get_by_session("cs_test_e2e") is not None

    @pytest.mark.asyncio
    async def test_subscription_deleted_cancels(self, handler_with_store, tmp_store) -> None:
        tmp_store.issue(tier="pro", stripe_customer_id="cus_sub", stripe_session_id="cs_sub")
        event = _fake_event("customer.subscription.deleted", {"customer": "cus_sub"})
        resp = await handler_with_store(event)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["cancelled"] == 1

    @pytest.mark.asyncio
    async def test_unknown_event_acknowledged(self, handler_with_store) -> None:
        event = _fake_event("some.random.event", {"id": "whatever"})
        resp = await handler_with_store(event)
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["received"] is True


# ─── Email delivery ─────────────────────────────────────────────────────────


class TestEmailExtraction:
    def test_pulls_from_customer_details(self) -> None:
        assert (
            webhook._extract_customer_email({"customer_details": {"email": "a@b.com"}}) == "a@b.com"
        )

    def test_pulls_from_customer_email_legacy(self) -> None:
        assert webhook._extract_customer_email({"customer_email": "x@y.com"}) == "x@y.com"

    def test_returns_none_when_missing(self) -> None:
        assert webhook._extract_customer_email({}) is None

    def test_returns_none_on_malformed(self) -> None:
        assert webhook._extract_customer_email({"customer_email": "not-an-email"}) is None


class TestEmailDelivery:
    """Exercise the Resend delivery path without hitting the real API."""

    @pytest.mark.asyncio
    async def test_skipped_when_no_address(self, tmp_store) -> None:
        lic = tmp_store.issue(tier="starter", stripe_customer_id="c", stripe_session_id="s")
        assert await webhook._email_license_key(None, lic) == "skipped_no_address"

    @pytest.mark.asyncio
    async def test_skipped_when_no_api_key(self, tmp_store, monkeypatch) -> None:
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        lic = tmp_store.issue(tier="starter", stripe_customer_id="c", stripe_session_id="s")
        assert await webhook._email_license_key("a@b.com", lic) == "skipped_no_provider"

    @pytest.mark.asyncio
    async def test_sent_on_success(self, tmp_store, monkeypatch) -> None:
        monkeypatch.setenv("RESEND_API_KEY", "re_test_xxx")
        lic = tmp_store.issue(tier="pro", stripe_customer_id="c", stripe_session_id="s")
        captured: dict = {}

        class _FakeResp:
            status_code = 200
            text = "ok"

        class _FakeClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def post(self, url, headers=None, json=None):
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                return _FakeResp()

        monkeypatch.setattr(webhook.httpx, "AsyncClient", _FakeClient)
        status = await webhook._email_license_key("tech@example.com", lic)
        assert status == "sent"
        assert captured["url"] == "https://api.resend.com/emails"
        assert captured["headers"]["Authorization"] == "Bearer re_test_xxx"
        assert captured["json"]["to"] == ["tech@example.com"]
        assert lic.key in captured["json"]["text"]
        assert lic.key in captured["json"]["html"]

    @pytest.mark.asyncio
    async def test_failure_does_not_raise(self, tmp_store, monkeypatch) -> None:
        monkeypatch.setenv("RESEND_API_KEY", "re_test_xxx")
        lic = tmp_store.issue(tier="starter", stripe_customer_id="c", stripe_session_id="s")

        class _FakeResp:
            status_code = 422
            text = '{"error":"invalid"}'

        class _FakeClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def post(self, *a, **kw):
                return _FakeResp()

        monkeypatch.setattr(webhook.httpx, "AsyncClient", _FakeClient)
        assert await webhook._email_license_key("a@b.com", lic) == "failed_422"
