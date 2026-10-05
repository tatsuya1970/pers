"""
Pers Image SaaS - 2026-10 セキュリティ/整合性強化のテスト
対象:
  1. AI処理のスレッドプール実行（イベントループを塞がない）
  2. 月次更新 webhook の冪等化（invoice ID / 契約一致）
  3. 同一プラン変更ガード
  4. 解約（downgrade）の Stripe 失敗時の扱い
  6. 原子的なチケット控除・返却
  7. アップロード / 画素数 / blend パラメータ上限
実行: pytest tests/test_hardening.py -v
"""
import io
import json
import os
import threading
import pytest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
from PIL import Image

os.environ.setdefault("FIREBASE_SERVICE_ACCOUNT_JSON", json.dumps({
    "type": "service_account", "project_id": "test",
    "private_key_id": "id", "private_key": "-----BEGIN RSA PRIVATE KEY-----\nkey\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "test@test.iam.gserviceaccount.com", "client_id": "1",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}))
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")
os.environ["DATABASE_URL"] = "sqlite:///./test_hardening.db"

with patch("firebase_admin._apps", {"[DEFAULT]": MagicMock()}), \
     patch("firebase_admin.initialize_app"), \
     patch("firebase_admin.credentials.Certificate"):
    import main
    from main import app, _deduct_one_credit, _refund_one_credit
    from database import Base, engine, SessionLocal, User, ProcessedInvoice

from httpx import AsyncClient, ASGITransport

Base.metadata.create_all(bind=engine)


@pytest.fixture
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()

def make_png_bytes(w=100, h=100) -> bytes:
    img = Image.new("RGBA", (w, h), color=(100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def auth_headers(token="valid_token"):
    return {"Authorization": f"Bearer {token}"}

def mock_firebase(uid: str):
    return patch("firebase_admin.auth.verify_id_token", return_value={"uid": uid})

def mock_db(session):
    return patch("main.get_db", return_value=iter([session]))

def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

def renewal_event(invoice_id="in_001", sub_id="sub_001"):
    invoice = MagicMock()
    invoice.id = invoice_id
    invoice.subscription = sub_id
    invoice.billing_reason = "subscription_cycle"
    return {"type": "invoice.payment_succeeded", "data": {"object": invoice}}

async def post_webhook(event, db, uid="renewal_user"):
    sub = MagicMock()
    sub.metadata = {"firebase_uid": uid}
    with patch("stripe.Webhook.construct_event", return_value=event), \
         patch("stripe.Subscription.retrieve", return_value=sub), \
         mock_db(db):
        async with client() as c:
            return await c.post("/api/stripe-webhook", content=b"payload",
                                headers={"stripe-signature": "sig"})


# ══════════════════════════════════════════════════════
#  1. AI処理はイベントループ外（スレッドプール）で実行される
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestThreadpoolExecution:

    async def test_AI処理はメインスレッド以外で実行される(self, db):
        user = User(firebase_uid="tp_user", plan="lite", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        seen = {}

        def fake_ai(*args, **kwargs):
            seen["thread"] = threading.current_thread()
            return Image.new("RGBA", (10, 10))

        with mock_firebase("tp_user"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction", side_effect=fake_ai):
            async with client() as c:
                resp = await c.post("/api/instruction",
                                    files={"file": ("a.png", make_png_bytes(), "image/png")},
                                    data={"instruction": "x", "quality": "medium"},
                                    headers=auth_headers())
        assert resp.status_code == 200
        assert seen["thread"] is not threading.main_thread()


# ══════════════════════════════════════════════════════
#  2. 月次更新 webhook の冪等化
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestInvoiceIdempotency:

    async def test_同じinvoiceの再配送では残高がリセットされない(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=10,
                    stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)

        resp = await post_webhook(renewal_event("in_001", "sub_001"), db)
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30

        # 月途中で消費
        user.credits = 3
        db.commit()

        resp = await post_webhook(renewal_event("in_001", "sub_001"), db)
        assert resp.json()["status"] == "skipped - already processed"
        db.refresh(user)
        assert user.credits == 3  # 復活しない
        assert db.query(ProcessedInvoice).count() == 1

    async def test_別のinvoiceなら翌月もリセットされる(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=2,
                    stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        await post_webhook(renewal_event("in_001", "sub_001"), db)
        user.credits = 1; db.commit()
        resp = await post_webhook(renewal_event("in_002", "sub_001"), db)
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30

    async def test_契約IDが一致しないinvoiceは無視される(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=4,
                    stripe_subscription_id="sub_current")
        db.add(user); db.commit(); db.refresh(user)
        resp = await post_webhook(renewal_event("in_old", "sub_old"), db)
        assert resp.json()["status"] == "skipped - subscription mismatch"
        db.refresh(user)
        assert user.credits == 4
        assert db.query(ProcessedInvoice).count() == 0

    async def test_契約ID未保存のユーザーは処理してIDを補完する(self, db):
        user = User(firebase_uid="renewal_user", plan="plus", credits=4,
                    stripe_subscription_id=None)
        db.add(user); db.commit(); db.refresh(user)
        resp = await post_webhook(renewal_event("in_001", "sub_new"), db)
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 70
        assert user.stripe_subscription_id == "sub_new"

    async def test_invoice_IDが無い場合はスキップ(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=4,
                    stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        invoice = MagicMock()
        invoice.id = None
        invoice.subscription = "sub_001"
        invoice.billing_reason = "subscription_cycle"
        event = {"type": "invoice.payment_succeeded", "data": {"object": invoice}}
        resp = await post_webhook(event, db)
        assert resp.json()["status"] == "skipped - no invoice id"
        db.refresh(user)
        assert user.credits == 4


# ══════════════════════════════════════════════════════
#  3. 同一プラン変更ガード
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestSamePlanGuard:

    async def test_同一プランへの変更はStripeを呼ばず残高も変わらない(self, db):
        user = User(firebase_uid="same_plan_user", plan="lite", credits=3,
                    stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        with mock_firebase("same_plan_user"), mock_db(db), \
             patch("stripe.Subscription.retrieve") as retrieve, \
             patch("stripe.Subscription.modify") as modify:
            async with client() as c:
                resp = await c.post("/api/change-plan", json={"plan": "lite"}, headers=auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["changed"] is False
        retrieve.assert_not_called()
        modify.assert_not_called()
        db.refresh(user)
        assert user.credits == 3

    async def test_別プランへの変更は従来どおり残高リセット(self, db):
        user = User(firebase_uid="up_user", plan="lite", credits=3,
                    stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        sub = {"items": {"data": [{"id": "si_001"}]}}
        with mock_firebase("up_user"), mock_db(db), \
             patch("stripe.Subscription.retrieve", return_value=sub), \
             patch("stripe.Subscription.modify", return_value=MagicMock()):
            async with client() as c:
                resp = await c.post("/api/change-plan", json={"plan": "plus"}, headers=auth_headers())
        assert resp.json()["changed"] is True
        db.refresh(user)
        assert user.plan == "plus"
        assert user.credits == 70


# ══════════════════════════════════════════════════════
#  4. 解約（downgrade）の Stripe 失敗時
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestDowngradeStripeFailure:

    async def test_Stripe解約予約が失敗したらローカルも変更しない(self, db):
        user = User(firebase_uid="dg_user", plan="lite", credits=25,
                    stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        with mock_firebase("dg_user"), mock_db(db), \
             patch("stripe.Subscription.modify", side_effect=Exception("Stripe down")):
            async with client() as c:
                resp = await c.post("/api/user/downgrade", headers=auth_headers())
        assert resp.status_code == 502
        assert "error" in resp.json()
        db.refresh(user)
        assert user.plan == "lite"
        assert user.credits == 25

    async def test_Stripe側に契約が無い場合はローカルのみ無料に変更(self, db):
        user = User(firebase_uid="dg_user2", plan="lite", credits=25,
                    stripe_subscription_id="sub_gone")
        db.add(user); db.commit(); db.refresh(user)
        err = Exception("No such subscription")
        err.code = "resource_missing"
        with mock_firebase("dg_user2"), mock_db(db), \
             patch("stripe.Subscription.modify", side_effect=err):
            async with client() as c:
                resp = await c.post("/api/user/downgrade", headers=auth_headers())
        assert resp.status_code == 200
        db.refresh(user)
        assert user.plan == "free"
        assert user.credits == 10


# ══════════════════════════════════════════════════════
#  6. 原子的なチケット控除・返却
# ══════════════════════════════════════════════════════

class TestAtomicCredits:

    def test_creditsがあればcreditsから控除(self, db):
        user = User(firebase_uid="u1", credits=5, addon_credits=2)
        db.add(user); db.commit(); db.refresh(user)
        assert _deduct_one_credit(db, user) == ("credits", 4, 2)
        assert (user.credits, user.addon_credits) == (4, 2)

    def test_credits0ならaddonから控除(self, db):
        user = User(firebase_uid="u2", credits=0, addon_credits=2)
        db.add(user); db.commit(); db.refresh(user)
        assert _deduct_one_credit(db, user) == ("addon", 0, 1)
        assert (user.credits, user.addon_credits) == (0, 1)

    def test_両方0ならNoneで残高は変わらない(self, db):
        user = User(firebase_uid="u3", credits=0, addon_credits=0)
        db.add(user); db.commit(); db.refresh(user)
        assert _deduct_one_credit(db, user) == (None, 0, 0)
        assert (user.credits, user.addon_credits) == (0, 0)

    def test_addonがNULLでも安全(self, db):
        user = User(firebase_uid="u4", credits=0, addon_credits=None)
        db.add(user); db.commit(); db.refresh(user)
        assert _deduct_one_credit(db, user) == (None, 0, 0)
        _refund_one_credit(db, user, "addon")
        assert user.addon_credits == 1

    def test_返却は控除元に戻る(self, db):
        user = User(firebase_uid="u5", credits=1, addon_credits=1)
        db.add(user); db.commit(); db.refresh(user)
        _refund_one_credit(db, user, "credits")
        _refund_one_credit(db, user, "addon")
        assert (user.credits, user.addon_credits) == (2, 2)

    def test_並行控除でも残高が負にならない(self, db):
        """残高1のユーザーに対して8スレッドが同時に控除 → 成功は1回だけ"""
        user = User(firebase_uid="race", credits=1, addon_credits=0)
        db.add(user); db.commit(); db.refresh(user)
        uid = user.id

        def worker(_):
            s = SessionLocal()
            try:
                u = s.get(User, uid)
                return _deduct_one_credit(s, u)[0]
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(worker, range(8)))

        assert results.count("credits") == 1
        assert results.count(None) == 7
        db.refresh(user)
        assert user.credits == 0
        assert user.addon_credits == 0

    def test_ORM上の古い残高は控除の判断に使われない(self, db):
        """ORMオブジェクトが credits=5 を保持していても、DB上の実値で判定する"""
        user = User(firebase_uid="stale", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        other = SessionLocal()
        try:
            other.get(User, user.id).credits = 0
            other.commit()
        finally:
            other.close()
        assert user.credits == 5  # ORM上は古い
        assert _deduct_one_credit(db, user) == (None, 0, 0)
        assert user.credits == 0  # commit で期限切れ → 再読込で実値に同期


# ══════════════════════════════════════════════════════
#  7. アップロード / 画素数 / blend パラメータ上限
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestUploadLimits:

    async def test_不正な画像データは400でチケット消費なし(self, db):
        user = User(firebase_uid="bad_img", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        with mock_firebase("bad_img"), mock_db(db), \
             patch("main.ImageProcessor.sketch_to_realistic") as ai:
            async with client() as c:
                resp = await c.post("/api/sketch-to-real",
                                    files={"file": ("a.png", b"not an image at all", "image/png")},
                                    headers=auth_headers())
        assert resp.status_code == 400
        ai.assert_not_called()
        db.refresh(user)
        assert user.credits == 5

    async def test_画素数上限超過は413でチケット消費なし(self, db, monkeypatch):
        monkeypatch.setattr(main, "MAX_IMAGE_PIXELS", 50 * 50)
        user = User(firebase_uid="big_img", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        with mock_firebase("big_img"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction") as ai:
            async with client() as c:
                resp = await c.post("/api/instruction",
                                    files={"file": ("a.png", make_png_bytes(100, 100), "image/png")},
                                    data={"instruction": "x"},
                                    headers=auth_headers())
        assert resp.status_code == 413
        ai.assert_not_called()
        db.refresh(user)
        assert user.credits == 5

    async def test_ファイル上限超過は分割読み込み途中で413(self, db, monkeypatch):
        monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1024)
        user = User(firebase_uid="big_file", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        with mock_firebase("big_file"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction") as ai:
            async with client() as c:
                resp = await c.post("/api/instruction",
                                    files={"file": ("a.png", b"\x89PNG" + os.urandom(4096), "image/png")},
                                    data={"instruction": "x"},
                                    headers=auth_headers())
        assert resp.status_code == 413
        ai.assert_not_called()
        db.refresh(user)
        assert user.credits == 5

    async def test_ContentLength超過はmultipart解析前に413(self, db, monkeypatch):
        monkeypatch.setattr(main, "MAX_REQUEST_BYTES", 10)
        with mock_firebase("cl_user"), mock_db(db):
            async with client() as c:
                resp = await c.post("/api/instruction",
                                    files={"file": ("a.png", make_png_bytes(), "image/png")},
                                    data={"instruction": "x"},
                                    headers=auth_headers())
        assert resp.status_code == 413
        assert "error" in resp.json()

    async def test_GETやContentLength無しは影響を受けない(self, db, monkeypatch):
        monkeypatch.setattr(main, "MAX_REQUEST_BYTES", 10)
        async with client() as c:
            resp = await c.get("/api/pic-list")
        assert resp.status_code == 200

    @pytest.mark.parametrize("params", [
        {"width": "-1", "height": "100"},
        {"width": "100", "height": "0"},
        {"width": "nan", "height": "100"},
        {"width": "inf", "height": "100"},
        {"width": "100", "height": "100", "cx": "nan"},
    ])
    async def test_blendの不正な数値パラメータは400でチケット消費なし(self, db, params):
        user = User(firebase_uid="blend_bad", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        data = {"cx": "50", "cy": "50", "width": "100", "height": "100", "angle": "0"}
        data.update(params)
        with mock_firebase("blend_bad"), mock_db(db), \
             patch("main.ImageProcessor.blend_building") as ai:
            async with client() as c:
                resp = await c.post("/api/blend",
                                    files={"bg_file": ("bg.png", make_png_bytes(), "image/png"),
                                           "bld_file": ("bld.png", make_png_bytes(), "image/png")},
                                    data=data, headers=auth_headers())
        assert resp.status_code == 400, resp.text
        ai.assert_not_called()
        db.refresh(user)
        assert user.credits == 5

    async def test_blendの建物サイズは背景の2倍まで(self, db):
        user = User(firebase_uid="blend_huge", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        # 背景 100px → 上限 200px。width=201 は拒否
        data = {"cx": "50", "cy": "50", "width": "201", "height": "100", "angle": "0"}
        with mock_firebase("blend_huge"), mock_db(db), \
             patch("main.ImageProcessor.blend_building") as ai:
            async with client() as c:
                resp = await c.post("/api/blend",
                                    files={"bg_file": ("bg.png", make_png_bytes(), "image/png"),
                                           "bld_file": ("bld.png", make_png_bytes(), "image/png")},
                                    data=data, headers=auth_headers())
        assert resp.status_code == 400
        ai.assert_not_called()
        db.refresh(user)
        assert user.credits == 5

    async def test_blendの正常範囲は処理されチケット控除(self, db):
        user = User(firebase_uid="blend_ok", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        data = {"cx": "50", "cy": "50", "width": "200", "height": "150", "angle": "0"}
        with mock_firebase("blend_ok"), mock_db(db), \
             patch("main.ImageProcessor.blend_building", return_value=Image.new("RGBA", (10, 10))):
            async with client() as c:
                resp = await c.post("/api/blend",
                                    files={"bg_file": ("bg.png", make_png_bytes(), "image/png"),
                                           "bld_file": ("bld.png", make_png_bytes(), "image/png")},
                                    data=data, headers=auth_headers())
        assert resp.status_code == 200
        db.refresh(user)
        assert user.credits == 4


# ══════════════════════════════════════════════════════
#  第2回指摘 1: Stripe API バージョン差による Invoice 形式
# ══════════════════════════════════════════════════════

import stripe as stripe_lib

def basil_invoice(invoice_id="in_basil_001", sub_id="sub_001", billing_reason="subscription_cycle",
                  period_start=1_800_000_000):
    """2025-03-31.basil 以降の実際の JSON 形式（invoice.subscription は存在しない）"""
    return stripe_lib.Invoice.construct_from({
        "id": invoice_id,
        "object": "invoice",
        "billing_reason": billing_reason,
        "period_start": period_start,
        "period_end": period_start + 30 * 86400,
        "status": "paid",
        "parent": {
            "type": "subscription_details",
            "subscription_details": {"subscription": sub_id, "metadata": {}},
        },
        "lines": {"object": "list", "data": [{
            "id": "il_001", "object": "line_item",
            "parent": {"type": "subscription_item_details",
                       "subscription_item_details": {"subscription": sub_id, "subscription_item": "si_001"}},
        }]},
    }, "sk_test_dummy")

def legacy_invoice(invoice_id="in_legacy_001", sub_id="sub_001", billing_reason="subscription_cycle",
                   period_start=1_800_000_000):
    """basil より前の形式（invoice.subscription に文字列ID）"""
    return stripe_lib.Invoice.construct_from({
        "id": invoice_id, "object": "invoice", "billing_reason": billing_reason,
        "period_start": period_start, "subscription": sub_id,
    }, "sk_test_dummy")

def ev(invoice):
    return {"type": "invoice.payment_succeeded", "data": {"object": invoice}}


@pytest.mark.asyncio
class TestInvoiceFormats:

    async def test_basil形式のinvoiceでも契約IDを取り出して付与する(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=2, stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        resp = await post_webhook(ev(basil_invoice()), db)
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30
        assert user.last_renewal_period_start == 1_800_000_000

    async def test_旧形式のinvoiceも引き続き付与する(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=2, stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        resp = await post_webhook(ev(legacy_invoice()), db)
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30

    async def test_行アイテムにしか契約IDが無い形式(self, db):
        user = User(firebase_uid="renewal_user", plan="plus", credits=2, stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        inv = stripe_lib.Invoice.construct_from({
            "id": "in_lines_only", "object": "invoice", "billing_reason": "subscription_cycle",
            "period_start": 1_800_000_000,
            "lines": {"object": "list", "data": [{"id": "il_1", "object": "line_item",
                "parent": {"type": "subscription_item_details",
                           "subscription_item_details": {"subscription": "sub_001"}}}]},
        }, "sk_test_dummy")
        resp = await post_webhook(ev(inv), db)
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 70

    async def test_契約IDがどこにも無ければスキップ(self, db):
        inv = stripe_lib.Invoice.construct_from({"id": "in_nosub", "object": "invoice",
                                                 "billing_reason": "manual"}, "sk_test_dummy")
        resp = await post_webhook(ev(inv), db)
        assert resp.json()["status"] == "skipped - no subscription id"



class TestInvoiceSubscriptionHelper:

    def test_契約ID抽出ヘルパーは展開済みオブジェクトにも対応(self):
        inv = {"subscription": {"id": "sub_expanded", "object": "subscription"}}
        assert main._invoice_subscription_id(inv) == "sub_expanded"
        inv = {"parent": {"subscription_details": {"subscription": {"id": "sub_exp2"}}}}
        assert main._invoice_subscription_id(inv) == "sub_exp2"
        assert main._invoice_subscription_id({}) is None
        assert main._invoice_subscription_id(None) is None


# ══════════════════════════════════════════════════════
#  第2回指摘 3: 古い月次通知の遅延到着・定期更新以外の請求
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestStaleAndNonCycleInvoices:

    async def test_過去期間の別invoiceが遅れて届いても残高は復活しない(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=2, stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        # 新しい月次更新を先に処理
        resp = await post_webhook(ev(basil_invoice("in_new", period_start=2_000)), db)
        assert resp.json()["status"] == "success"
        user.credits = 3; db.commit()
        # 古い期間の未処理 invoice（別ID）が遅延到着
        resp = await post_webhook(ev(basil_invoice("in_old", period_start=1_000)), db)
        assert resp.json()["status"] == "skipped - stale period"
        db.refresh(user)
        assert user.credits == 3
        assert user.last_renewal_period_start == 2_000
        # 古い invoice も処理済みとして記録される（再配送されても再評価しない）
        assert db.query(ProcessedInvoice).filter_by(invoice_id="in_old").one().credits_reset is False

    async def test_同じ期間の再発行invoiceも復活しない(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=2, stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        await post_webhook(ev(basil_invoice("in_a", period_start=5_000)), db)
        user.credits = 1; db.commit()
        resp = await post_webhook(ev(basil_invoice("in_b", period_start=5_000)), db)
        assert resp.json()["status"] == "skipped - stale period"
        db.refresh(user)
        assert user.credits == 1

    async def test_翌期間のinvoiceは付与される(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=2, stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        await post_webhook(ev(basil_invoice("in_m1", period_start=1_000)), db)
        user.credits = 1; db.commit()
        resp = await post_webhook(ev(basil_invoice("in_m2", period_start=1_000 + 30 * 86400)), db)
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30

    async def test_プラン変更の日割り請求では満額に戻さない(self, db):
        user = User(firebase_uid="renewal_user", plan="plus", credits=12, stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        resp = await post_webhook(ev(basil_invoice("in_upd", billing_reason="subscription_update")), db)
        assert resp.json()["status"] == "skipped - billing_reason=subscription_update"
        db.refresh(user)
        assert user.credits == 12
        assert user.last_renewal_period_start is None

    async def test_period_startが無いinvoiceは従来どおり付与(self, db):
        user = User(firebase_uid="renewal_user", plan="lite", credits=2, stripe_subscription_id="sub_001")
        db.add(user); db.commit(); db.refresh(user)
        inv = stripe_lib.Invoice.construct_from({"id": "in_np", "object": "invoice",
            "billing_reason": "subscription_cycle", "subscription": "sub_001"}, "sk_test_dummy")
        resp = await post_webhook(ev(inv), db)
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30


# ══════════════════════════════════════════════════════
#  第2回指摘 2: AI処理中にDB接続を保持しない
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestNoConnectionDuringAI:

    # 注: エンドポイントは Depends(get_db) で独自の Session を作るため、
    # 接続の保持はエンジンのプール（checkedout 数）で観測する。
    # テスト側の Session は事前に commit して接続を返しておく。

    async def test_AI処理中はDB接続がプールに返っている(self, db):
        user = User(firebase_uid="conn_user", plan="lite", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        db.commit()
        seen = {}

        def fake_ai(*args, **kwargs):
            seen["checkedout"] = engine.pool.checkedout()
            return Image.new("RGBA", (10, 10))

        with mock_firebase("conn_user"), mock_db(db), \
             patch("main.ImageProcessor.sketch_to_realistic", side_effect=fake_ai):
            async with client() as c:
                resp = await c.post("/api/sketch-to-real",
                                    files={"file": ("a.png", make_png_bytes(), "image/png")},
                                    headers=auth_headers())
        assert resp.status_code == 200
        assert seen["checkedout"] == 0
        assert resp.json()["credits_remaining"] == 4
        db.refresh(user)
        assert user.credits == 4

    async def test_blendでもAI処理中はDB接続がプールに返っている(self, db):
        user = User(firebase_uid="conn_user2", plan="lite", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        db.commit()
        seen = {}

        def fake_ai(*args, **kwargs):
            seen["checkedout"] = engine.pool.checkedout()
            return Image.new("RGBA", (10, 10))

        data = {"cx": "50", "cy": "50", "width": "100", "height": "100", "angle": "0"}
        with mock_firebase("conn_user2"), mock_db(db), \
             patch("main.ImageProcessor.blend_building", side_effect=fake_ai):
            async with client() as c:
                resp = await c.post("/api/blend",
                                    files={"bg_file": ("bg.png", make_png_bytes(), "image/png"),
                                           "bld_file": ("bld.png", make_png_bytes(), "image/png")},
                                    data=data, headers=auth_headers())
        assert resp.status_code == 200
        assert seen["checkedout"] == 0


# ══════════════════════════════════════════════════════
#  第2回指摘 4: 生成後のエンコード失敗でも返却
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestRefundAfterEncodeFailure:

    @pytest.mark.parametrize("endpoint,ai_name,extra", [
        ("/api/sketch-to-real", "sketch_to_realistic", {}),
        ("/api/instruction", "edit_by_instruction", {"instruction": "x"}),
    ])
    async def test_エンコード失敗でもチケットが返却される(self, db, endpoint, ai_name, extra):
        user = User(firebase_uid="enc_user", plan="lite", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        with mock_firebase("enc_user"), mock_db(db), \
             patch(f"main.ImageProcessor.{ai_name}", return_value=Image.new("RGBA", (10, 10))), \
             patch("main.pil_to_base64", side_effect=RuntimeError("encode failed")), \
             patch("main.send_error_email_task"):
            async with client() as c:
                resp = await c.post(endpoint,
                                    files={"file": ("a.png", make_png_bytes(), "image/png")},
                                    data=extra, headers=auth_headers())
        assert resp.status_code == 500
        db.refresh(user)
        assert user.credits == 5

    async def test_blendのエンコード失敗でもチケットが返却される(self, db):
        user = User(firebase_uid="enc_user2", plan="lite", credits=5)
        db.add(user); db.commit(); db.refresh(user)
        data = {"cx": "50", "cy": "50", "width": "100", "height": "100", "angle": "0"}
        with mock_firebase("enc_user2"), mock_db(db), \
             patch("main.ImageProcessor.blend_building", return_value=Image.new("RGBA", (10, 10))), \
             patch("main.pil_to_base64", side_effect=RuntimeError("encode failed")), \
             patch("main.send_error_email_task"):
            async with client() as c:
                resp = await c.post("/api/blend",
                                    files={"bg_file": ("bg.png", make_png_bytes(), "image/png"),
                                           "bld_file": ("bld.png", make_png_bytes(), "image/png")},
                                    data=data, headers=auth_headers())
        assert resp.status_code == 500
        db.refresh(user)
        assert user.credits == 5


# ══════════════════════════════════════════════════════
#  第2回指摘 5: 月次更新をまたいだ返却は上限で頭打ち
# ══════════════════════════════════════════════════════

class TestRefundCap:

    def test_月次リセット後の返却は上限を超えない(self, db):
        user = User(firebase_uid="cap_user", plan="lite", credits=1)
        db.add(user); db.commit(); db.refresh(user)
        pool, _, _ = _deduct_one_credit(db, user)
        assert pool == "credits"
        # AI処理中に月次リセットが走った
        other = SessionLocal()
        try:
            other.get(User, user.id).credits = 30
            other.commit()
        finally:
            other.close()
        _refund_one_credit(db, user, pool)
        assert user.credits == 30  # 31 にならない

    def test_上限未満なら通常どおり返却(self, db):
        user = User(firebase_uid="cap_user2", plan="lite", credits=29)
        db.add(user); db.commit(); db.refresh(user)
        _refund_one_credit(db, user, "credits")
        assert user.credits == 30

    def test_addonは上限なしで返却(self, db):
        user = User(firebase_uid="cap_user3", plan="lite", credits=30, addon_credits=50)
        db.add(user); db.commit(); db.refresh(user)
        _refund_one_credit(db, user, "addon")
        assert user.addon_credits == 51

    def test_未知のプランは上限なしで返却(self, db):
        user = User(firebase_uid="cap_user4", plan="legacy", credits=999)
        db.add(user); db.commit(); db.refresh(user)
        _refund_one_credit(db, user, "credits")
        assert user.credits == 1000
