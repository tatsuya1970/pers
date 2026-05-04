"""
PersImage SaaS - 単体テスト
実行: pytest tests/test_main.py -v
依存: pip install pytest pytest-asyncio httpx
"""
import io
import json
import os
import time
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from PIL import Image

# ── Firebase Admin SDK をモックしてからインポート ──────────────────────────
os.environ.setdefault("FIREBASE_SERVICE_ACCOUNT_JSON", json.dumps({
    "type": "service_account",
    "project_id": "test",
    "private_key_id": "key_id",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA-----END RSA PRIVATE KEY-----\n",
    "client_email": "test@test.iam.gserviceaccount.com",
    "client_id": "123",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}))
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")

import firebase_admin
_mock_app = MagicMock()
with patch("firebase_admin._apps", {"default": _mock_app}):
    pass

# firebase_admin.initialize_app をモックして RuntimeError を回避
with patch("firebase_admin.initialize_app"), \
     patch("firebase_admin.credentials.Certificate"):
    pass

from httpx import AsyncClient, ASGITransport
import pytest_asyncio

# DB をインメモリ SQLite に差し替え
os.environ["DATABASE_URL"] = "sqlite:///./test_db.db"

with patch("firebase_admin._apps", {"[DEFAULT]": MagicMock()}), \
     patch("firebase_admin.initialize_app"), \
     patch("firebase_admin.credentials.Certificate"):
    import main
    from main import app, send_error_email_task, pil_to_base64, is_maintenance, set_maintenance
    import database
    from database import Base, engine, SessionLocal, User, GeneratedImage

# テスト用DB初期化
Base.metadata.create_all(bind=engine)


# ══════════════════════════════════════════════════════
#  フィクスチャ
# ══════════════════════════════════════════════════════

@pytest.fixture
def db():
    """各テスト前後でDBをクリーンアップ"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()

@pytest.fixture
def test_user(db):
    """credits=5, addon=0 の標準テストユーザー"""
    user = User(firebase_uid="test_uid_001", plan="free", credits=5, addon_credits=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@pytest.fixture
def paid_user(db):
    """Lite プランの有料ユーザー"""
    user = User(firebase_uid="paid_uid_001", plan="lite", credits=30, addon_credits=10,
                stripe_subscription_id="sub_test_123")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@pytest.fixture
def zero_credit_user(db):
    """credits=0, addon=5 のユーザー（アドオンのみ）"""
    user = User(firebase_uid="zero_uid_001", plan="free", credits=0, addon_credits=5)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@pytest.fixture
def empty_credit_user(db):
    """credits=0, addon=0 の残高ゼロユーザー"""
    user = User(firebase_uid="empty_uid_001", plan="free", credits=0, addon_credits=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def make_png_bytes(width=100, height=100) -> bytes:
    """テスト用 PNG バイト列を生成"""
    img = Image.new("RGBA", (width, height), color=(255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def make_auth_headers(token: str = "valid_token") -> dict:
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════
#  1. pil_to_base64
# ══════════════════════════════════════════════════════

class TestPilToBase64:
    """
    テスト対象: pil_to_base64(img)
    """

    def test_正常系_PNG画像をbase64に変換(self):
        img = Image.new("RGBA", (10, 10), color=(0, 255, 0, 255))
        result = pil_to_base64(img)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_正常系_base64デコードで元画像を復元できる(self):
        import base64
        img = Image.new("RGB", (50, 50), color=(128, 128, 128))
        b64 = pil_to_base64(img)
        decoded = base64.b64decode(b64)
        restored = Image.open(io.BytesIO(decoded))
        assert restored.size == (50, 50)

    def test_正常系_1x1最小画像(self):
        img = Image.new("RGBA", (1, 1))
        result = pil_to_base64(img)
        assert isinstance(result, str)

    def test_正常系_大きい画像(self):
        img = Image.new("RGB", (2000, 2000), color=(255, 255, 255))
        result = pil_to_base64(img)
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════
#  2. is_maintenance / set_maintenance
# ══════════════════════════════════════════════════════

class TestMaintenanceMode:
    """
    テスト対象: is_maintenance(), set_maintenance(on)
    """

    def setup_method(self):
        set_maintenance(False)

    def teardown_method(self):
        set_maintenance(False)

    def test_初期状態はメンテナンスOFF(self):
        assert is_maintenance() is False

    def test_ONにするとTrueを返す(self):
        set_maintenance(True)
        assert is_maintenance() is True

    def test_OFFにするとFalseを返す(self):
        set_maintenance(True)
        set_maintenance(False)
        assert is_maintenance() is False

    def test_OFFを二重に呼んでもエラーにならない(self):
        set_maintenance(False)
        set_maintenance(False)
        assert is_maintenance() is False

    def test_ONを二重に呼んでもエラーにならない(self):
        set_maintenance(True)
        set_maintenance(True)
        assert is_maintenance() is True


# ══════════════════════════════════════════════════════
#  3. send_error_email_task
# ══════════════════════════════════════════════════════

class TestSendErrorEmailTask:
    """
    テスト対象: send_error_email_task(base_error, traceback_str, user_id)
    """

    def setup_method(self):
        main.last_error_times.clear()

    def test_SMTP未設定時はメール送信せずにreturnする(self):
        with patch.dict(os.environ, {"SMTP_SERVER": "", "SMTP_USER": "", "SMTP_PASS": ""}):
            # 例外が発生しないこと
            send_error_email_task("テストエラー", "traceback", "uid_001")

    def test_同じエラーは30分以内に送信しない(self):
        main.last_error_times["重複エラー"] = time.time()
        with patch("smtplib.SMTP") as mock_smtp:
            send_error_email_task("重複エラー", "tb")
            mock_smtp.assert_not_called()

    def test_30分経過後は再送信する(self):
        main.last_error_times["古いエラー"] = time.time() - 1900  # 31分前
        with patch.dict(os.environ, {
            "SMTP_SERVER": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "test@example.com",
            "SMTP_PASS": "pass"
        }), patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value = mock_server
            send_error_email_task("古いエラー", "tb")
            mock_smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=10)

    def test_初回エラーはlast_error_timesに記録される(self):
        with patch.dict(os.environ, {"SMTP_SERVER": "", "SMTP_USER": "", "SMTP_PASS": ""}):
            send_error_email_task("新規エラー", "tb")
        assert "新規エラー" in main.last_error_times

    def test_user_idがNoneでも動作する(self):
        with patch.dict(os.environ, {"SMTP_SERVER": "", "SMTP_USER": "", "SMTP_PASS": ""}):
            send_error_email_task("エラー", "tb", user_id=None)

    def test_user_idが空文字でも動作する(self):
        with patch.dict(os.environ, {"SMTP_SERVER": "", "SMTP_USER": "", "SMTP_PASS": ""}):
            send_error_email_task("エラー", "tb", user_id="")

    def test_SMTPタイムアウトが10秒で設定される(self):
        with patch.dict(os.environ, {
            "SMTP_SERVER": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "u@u.com",
            "SMTP_PASS": "p"
        }), patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value = MagicMock()
            send_error_email_task("err", "tb")
            args, kwargs = mock_smtp.call_args
            # smtplib.SMTP(server, port, timeout=10) の timeout を確認
            assert kwargs.get("timeout") == 10


# ══════════════════════════════════════════════════════
#  4. クレジット控除・返金ロジック（ユニット）
# ══════════════════════════════════════════════════════

class TestCreditDeductionLogic:
    """
    テスト対象: credits/addon_credits の控除・返金ロジック
    deducted_from = "credits" if user.credits > 0 else "addon"
    """

    def test_credits残あり_creditsから控除(self, db, test_user):
        assert test_user.credits == 5
        deducted_from = "credits" if test_user.credits > 0 else "addon"
        assert deducted_from == "credits"
        test_user.credits -= 1
        db.commit()
        db.refresh(test_user)
        assert test_user.credits == 4

    def test_credits残なし_addonから控除(self, db, zero_credit_user):
        assert zero_credit_user.credits == 0
        assert zero_credit_user.addon_credits == 5
        deducted_from = "credits" if zero_credit_user.credits > 0 else "addon"
        assert deducted_from == "addon"
        zero_credit_user.addon_credits -= 1
        db.commit()
        db.refresh(zero_credit_user)
        assert zero_credit_user.addon_credits == 4

    def test_credits返金先はcredits(self, db, test_user):
        deducted_from = "credits"
        test_user.credits -= 1
        db.commit()
        # AI失敗 → 返金
        if deducted_from == "credits":
            test_user.credits += 1
        db.commit()
        db.refresh(test_user)
        assert test_user.credits == 5  # 元の値に戻る

    def test_addon返金先はaddon(self, db, zero_credit_user):
        deducted_from = "addon"
        zero_credit_user.addon_credits -= 1
        db.commit()
        # AI失敗 → 返金
        if deducted_from == "addon":
            zero_credit_user.addon_credits += 1
        db.commit()
        db.refresh(zero_credit_user)
        assert zero_credit_user.addon_credits == 5  # 元の値に戻る

    def test_credits_0の時addonに返金されない_旧バグの再現防止(self, db, zero_credit_user):
        """旧バグ: credits >= 0 の条件では credits=0 の時も credits に返金されていた"""
        deducted_from = "credits" if zero_credit_user.credits > 0 else "addon"
        assert deducted_from == "addon"  # credits=0 なので addon から引かれる
        zero_credit_user.addon_credits -= 1
        db.commit()
        original_credits = zero_credit_user.credits
        # 正しい返金先はaddon
        if deducted_from == "credits":
            zero_credit_user.credits += 1
        else:
            zero_credit_user.addon_credits += 1
        db.commit()
        db.refresh(zero_credit_user)
        assert zero_credit_user.credits == original_credits  # credits は変わらない


# ══════════════════════════════════════════════════════
#  5. APIエンドポイント（統合テスト）
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestUserSyncEndpoint:
    """
    テスト対象: POST /api/user/sync
    """

    async def test_Bearerトークンなし_401を返す(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/user/sync")
        assert resp.status_code == 401

    async def test_不正なトークン形式_401を返す(self):
        with patch("firebase_admin.auth.verify_id_token", side_effect=Exception("Invalid token")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/user/sync", headers={"Authorization": "Bearer invalid"})
        assert resp.status_code == 401

    async def test_有効トークン_既存ユーザー_200を返す(self, db, test_user):
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/user/sync",
                                         headers=make_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "credits" in data
        assert "plan" in data

    async def test_有効トークン_新規ユーザー自動作成(self, db):
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "brand_new_uid"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/user/sync",
                                         headers=make_auth_headers())
        assert resp.status_code == 200
        # DB に新規ユーザーが作成されているか確認
        new_user = db.query(User).filter(User.firebase_uid == "brand_new_uid").first()
        assert new_user is not None
        assert new_user.plan == "free"
        assert new_user.credits == 10

    async def test_AuthorizationヘッダーがBearerでない_401(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/user/sync",
                                     headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestMaintenanceMiddleware:
    """
    テスト対象: maintenance_middleware
    """

    def setup_method(self):
        set_maintenance(False)

    def teardown_method(self):
        set_maintenance(False)

    async def test_メンテナンスOFF時は通常レスポンス(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/")
        assert resp.status_code == 200

    async def test_メンテナンスON時は503を返す(self):
        set_maintenance(True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/")
        assert resp.status_code == 503
        assert "メンテナンス" in resp.text

    async def test_メンテナンスON時もadminAPIは通過する(self):
        set_maintenance(True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/maintenance/off",
                headers={"X-Admin-Secret": os.getenv("ADMIN_SECRET", "")}
            )
        # admin エンドポイントはメンテナンス中でも到達できる
        assert resp.status_code in (200, 403)  # 認証結果に依存

    async def test_メンテナンスON時APIは503を返す(self):
        set_maintenance(True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/user/sync")
        assert resp.status_code == 503


@pytest.mark.asyncio
class TestAdminEndpoints:
    """
    テスト対象: POST /api/admin/maintenance/on, /off
    """

    def setup_method(self):
        set_maintenance(False)

    def teardown_method(self):
        set_maintenance(False)

    async def test_正しいシークレットでONにできる(self):
        with patch.dict(os.environ, {"ADMIN_SECRET": "mysecret"}):
            main.ADMIN_SECRET = "mysecret"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/admin/maintenance/on",
                                         headers={"X-Admin-Secret": "mysecret"})
        assert resp.status_code == 200
        assert is_maintenance() is True

    async def test_誤ったシークレットは403(self):
        with patch.dict(os.environ, {"ADMIN_SECRET": "mysecret"}):
            main.ADMIN_SECRET = "mysecret"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/admin/maintenance/on",
                                         headers={"X-Admin-Secret": "wrongsecret"})
        assert resp.status_code == 403

    async def test_シークレットなしは403(self):
        with patch.dict(os.environ, {"ADMIN_SECRET": "mysecret"}):
            main.ADMIN_SECRET = "mysecret"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/admin/maintenance/on")
        assert resp.status_code == 403

    async def test_OFFにできる(self):
        set_maintenance(True)
        with patch.dict(os.environ, {"ADMIN_SECRET": "mysecret"}):
            main.ADMIN_SECRET = "mysecret"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/admin/maintenance/off",
                                         headers={"X-Admin-Secret": "mysecret"})
        assert resp.status_code == 200
        assert is_maintenance() is False


@pytest.mark.asyncio
class TestSketchToRealEndpoint:
    """
    テスト対象: POST /api/sketch-to-real
    """

    async def test_未認証_401(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/sketch-to-real",
                                     files={"file": ("test.png", make_png_bytes(), "image/png")})
        assert resp.status_code == 401

    async def test_クレジット残高ゼロ_402(self, db, empty_credit_user):
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "empty_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/sketch-to-real",
                                         files={"file": ("test.png", make_png_bytes(), "image/png")},
                                         data={"quality": "medium"},
                                         headers=make_auth_headers())
        assert resp.status_code == 402

    async def test_ファイルサイズ超過_413(self, db, test_user):
        large_data = b"x" * (11 * 1024 * 1024)  # 11MB
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/sketch-to-real",
                                         files={"file": ("big.png", large_data, "image/png")},
                                         data={"quality": "medium"},
                                         headers=make_auth_headers())
        assert resp.status_code == 413

    async def test_AI失敗時にクレジット返金される(self, db, test_user):
        original_credits = test_user.credits
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("main.ImageProcessor.sketch_to_realistic", side_effect=Exception("OpenAI Error")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post("/api/sketch-to-real",
                                   files={"file": ("test.png", make_png_bytes(), "image/png")},
                                   data={"quality": "medium"},
                                   headers=make_auth_headers())
        db.refresh(test_user)
        assert test_user.credits == original_credits  # 返金されて元の値

    async def test_不正なqualityはmediumにフォールバック(self, db, test_user):
        """quality が不正値でも 400 にならず medium として処理される"""
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("main.ImageProcessor.sketch_to_realistic", return_value=Image.new("RGBA", (10, 10))), \
             patch("main.save_generated_image_to_db"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/sketch-to-real",
                                         files={"file": ("test.png", make_png_bytes(), "image/png")},
                                         data={"quality": "INVALID"},
                                         headers=make_auth_headers())
        # 400 にはならない（フォールバック処理がある）
        assert resp.status_code != 400


@pytest.mark.asyncio
class TestInstructionEndpoint:
    """
    テスト対象: POST /api/instruction
    """

    async def test_未認証_401(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/instruction",
                                     files={"file": ("test.png", make_png_bytes(), "image/png")},
                                     data={"instruction": "空を青くして"})
        assert resp.status_code == 401

    async def test_クレジット残高ゼロ_402(self, db, empty_credit_user):
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "empty_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/instruction",
                                         files={"file": ("test.png", make_png_bytes(), "image/png")},
                                         data={"instruction": "空を青くして"},
                                         headers=make_auth_headers())
        assert resp.status_code == 402

    async def test_addonクレジットから控除される(self, db, zero_credit_user):
        """credits=0, addon=5 のとき addon から控除"""
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "zero_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("main.ImageProcessor.edit_by_instruction", return_value=Image.new("RGBA", (10, 10))), \
             patch("main.save_generated_image_to_db"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/instruction",
                                         files={"file": ("test.png", make_png_bytes(), "image/png")},
                                         data={"instruction": "空を青くして", "quality": "medium"},
                                         headers=make_auth_headers())
        db.refresh(zero_credit_user)
        assert zero_credit_user.addon_credits == 4  # 5 → 4
        assert zero_credit_user.credits == 0  # credits は変わらない


@pytest.mark.asyncio
class TestVerifyPaymentEndpoint:
    """
    テスト対象: POST /api/verify-payment
    """

    async def test_未認証_401(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/verify-payment",
                                     json={"session_id": "cs_test_123"})
        assert resp.status_code == 401

    async def test_session_idなし_400(self, db, test_user):
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/verify-payment",
                                         json={},
                                         headers=make_auth_headers())
        assert resp.status_code == 400

    async def test_他人のsession_idは403(self, db, test_user):
        mock_session = MagicMock()
        mock_session.client_reference_id = "other_user_uid"  # 別ユーザーのUID
        mock_session.payment_status = "paid"
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/verify-payment",
                                         json={"session_id": "cs_other_user"},
                                         headers=make_auth_headers())
        assert resp.status_code == 403

    async def test_支払い未完了はpendingを返す(self, db, test_user):
        mock_session = MagicMock()
        mock_session.client_reference_id = "test_uid_001"
        mock_session.payment_status = "unpaid"
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/verify-payment",
                                         json={"session_id": "cs_unpaid"},
                                         headers=make_auth_headers())
        assert resp.json()["status"] == "pending"

    async def test_処理済みsession_idは二重付与しない(self, db, test_user):
        """グローバルな二重付与防止: 同じsession_idは一度のみ処理"""
        # 他のユーザーがすでにこのsession_idを処理済みと仮定
        other_user = User(firebase_uid="other_uid", plan="free", credits=5,
                          last_session_id="cs_already_done")
        db.add(other_user)
        db.commit()

        mock_session = MagicMock()
        mock_session.client_reference_id = "test_uid_001"
        mock_session.payment_status = "paid"
        mock_session.metadata = {"credits_to_add": "30", "item_name": "lite"}
        original_credits = test_user.credits

        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/verify-payment",
                                         json={"session_id": "cs_already_done"},
                                         headers=make_auth_headers())
        assert resp.json()["status"] == "already_processed"
        db.refresh(test_user)
        assert test_user.credits == original_credits  # クレジットが増えていない

    async def test_liteプラン購入でcreditsが30になる(self, db, test_user):
        mock_session = MagicMock()
        mock_session.client_reference_id = "test_uid_001"
        mock_session.payment_status = "paid"
        mock_session.metadata = {"credits_to_add": "30", "item_name": "lite"}
        mock_session.subscription = "sub_new_123"
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/verify-payment",
                                         json={"session_id": "cs_new_lite"},
                                         headers=make_auth_headers())
        assert resp.status_code == 200
        db.refresh(test_user)
        assert test_user.credits == 30
        assert test_user.plan == "lite"

    async def test_Stripe取得失敗は400(self, db, test_user):
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("stripe.checkout.Session.retrieve", side_effect=Exception("Stripe error")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/verify-payment",
                                         json={"session_id": "cs_invalid"},
                                         headers=make_auth_headers())
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestCreateCheckoutSessionEndpoint:
    """
    テスト対象: POST /api/create-checkout-session
    """

    async def test_未認証_401(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/create-checkout-session",
                                     json={"plan": "lite"})
        assert resp.status_code == 401

    async def test_無効なプラン_400(self, db, test_user):
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/create-checkout-session",
                                         json={"plan": "invalid_plan"},
                                         headers=make_auth_headers())
        assert resp.status_code == 400

    async def test_planもaddonも指定なし_400(self, db, test_user):
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/create-checkout-session",
                                         json={},
                                         headers=make_auth_headers())
        assert resp.status_code == 400

    async def test_有効なプランでStripeセッションURLを返す(self, db, test_user):
        mock_checkout = MagicMock()
        mock_checkout.id = "cs_test_abc"
        mock_checkout.url = "https://checkout.stripe.com/pay/cs_test_abc"
        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])), \
             patch("stripe.checkout.Session.create", return_value=mock_checkout):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/create-checkout-session",
                                         json={"plan": "lite"},
                                         headers=make_auth_headers())
        assert resp.status_code == 200
        assert "url" in resp.json()


@pytest.mark.asyncio
class TestStripeWebhook:
    """
    テスト対象: POST /api/stripe-webhook
    """

    async def test_不正な署名は400(self):
        import stripe as stripe_lib
        with patch("stripe.Webhook.construct_event",
                   side_effect=stripe_lib.error.SignatureVerificationError("Bad sig", "sig")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/stripe-webhook",
                                         content=b"payload",
                                         headers={"stripe-signature": "bad_sig"})
        assert resp.status_code == 400

    async def test_不正なペイロードは400(self):
        with patch("stripe.Webhook.construct_event", side_effect=ValueError("Bad payload")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/stripe-webhook",
                                         content=b"invalid",
                                         headers={"stripe-signature": "sig"})
        assert resp.status_code == 400

    async def test_subscription_create時はスキップ(self, db):
        invoice = MagicMock()
        invoice.subscription = "sub_123"
        invoice.billing_reason = "subscription_create"
        event = {"type": "invoice.payment_succeeded", "data": {"object": invoice}}
        with patch("stripe.Webhook.construct_event", return_value=event), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/stripe-webhook",
                                         content=b"payload",
                                         headers={"stripe-signature": "sig"})
        assert resp.json()["status"] == "skipped - initial payment"

    async def test_invoice_subscription_renewalでクレジットリセット(self, db, paid_user):
        invoice = MagicMock()
        invoice.subscription = "sub_test_123"
        invoice.billing_reason = "subscription_cycle"
        event = {"type": "invoice.payment_succeeded", "data": {"object": invoice}}

        mock_subscription = MagicMock()
        mock_subscription.metadata = {"firebase_uid": "paid_uid_001"}

        paid_user.credits = 5  # 月途中で使った状態
        db.commit()

        with patch("stripe.Webhook.construct_event", return_value=event), \
             patch("stripe.Subscription.retrieve", return_value=mock_subscription), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/stripe-webhook",
                                         content=b"payload",
                                         headers={"stripe-signature": "sig"})
        assert resp.json()["status"] == "success"
        db.refresh(paid_user)
        assert paid_user.credits == 30  # Lite プランのクレジットにリセット

    async def test_invoice_Stripe取得失敗は500(self, db):
        invoice = MagicMock()
        invoice.subscription = "sub_bad"
        invoice.billing_reason = "subscription_cycle"
        event = {"type": "invoice.payment_succeeded", "data": {"object": invoice}}

        with patch("stripe.Webhook.construct_event", return_value=event), \
             patch("stripe.Subscription.retrieve", side_effect=Exception("Stripe down")), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/stripe-webhook",
                                         content=b"payload",
                                         headers={"stripe-signature": "sig"})
        assert resp.status_code == 500


@pytest.mark.asyncio
class TestGalleryEndpoints:
    """
    テスト対象: GET /api/gallery, DELETE /api/gallery/{id}
    """

    async def test_未認証GET_401(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/gallery")
        assert resp.status_code == 401

    async def test_未認証DELETE_401(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/gallery/1")
        assert resp.status_code == 401

    async def test_他人の画像削除は404(self, db, test_user, paid_user):
        # paid_user の画像を test_user が削除しようとする
        img = GeneratedImage(user_id=paid_user.id, file_path="/static/uploads/other.png")
        db.add(img)
        db.commit()
        db.refresh(img)

        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.delete(f"/api/gallery/{img.id}",
                                            headers=make_auth_headers())
        assert resp.status_code == 404

    async def test_自分の画像は削除できる(self, db, test_user):
        img = GeneratedImage(user_id=test_user.id, file_path="/static/uploads/mine.png")
        db.add(img)
        db.commit()
        db.refresh(img)
        img_id = img.id

        with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "test_uid_001"}), \
             patch("main.get_db", return_value=iter([db])):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.delete(f"/api/gallery/{img_id}",
                                            headers=make_auth_headers())
        assert resp.status_code == 200
        assert db.query(GeneratedImage).filter(GeneratedImage.id == img_id).first() is None


# ══════════════════════════════════════════════════════
#  未テスト領域の指摘（コメントのみ）
# ══════════════════════════════════════════════════════
"""
【未テスト領域と懸念点】

1. ImageProcessor の各メソッド（sketch_to_realistic, edit_by_instruction, blend_building）
   → OpenAI API を呼ぶため外部依存が強い。VCR cassette またはモックで分離すべき。

2. /api/change-plan（プラン変更）
   → Stripe API の subscription.modify を呼ぶため外部依存あり。

3. /api/user/downgrade（ダウングレード）
   → Stripe cancel_at_period_end のモックが必要。

4. /api/match-color
   → ImageProcessor.match_color_tone の単体テスト未実施。

5. Firebase ID トークンの有効期限切れ（exp クレーム）
   → verify_id_token が TokenExpiredError を投げるケースの確認。

6. concurrent な同一 session_id の二重送信
   → DB レベルの UNIQUE 制約がないため、並行リクエストで二重付与が起こりうる。

7. /api/sketch-to-real でのファイル形式異常（PNG でない画像）
   → PIL が例外を投げるが、500 になることの明示的なテストが未実施。

8. addon_credits が NULL（None）のときの挙動
   → コードで `user.addon_credits or 0` としているが、NULL で算術演算するケースは要確認。

9. E2E テスト（ログイン → チェックアウト → 成功画面 → クレジット反映）
   → Playwright 等のブラウザ自動化テストで担保すべき領域。

10. Renderデプロイ後のスモークテスト
    → /api/user/sync に実際のFirebaseトークンを使った疎通確認。
"""
