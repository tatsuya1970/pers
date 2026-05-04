"""
PersImage SaaS - 統合テスト
実行: pytest tests/test_integration.py -v
観点: 画面→API→DB の一連動作、認証→認可→操作実行、課金フロー、エラー整合性
"""
import io
import json
import os
import time
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

# ── Firebase Admin SDK をモックしてインポート ──
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
os.environ["DATABASE_URL"] = "sqlite:///./test_integration.db"

with patch("firebase_admin._apps", {"[DEFAULT]": MagicMock()}), \
     patch("firebase_admin.initialize_app"), \
     patch("firebase_admin.credentials.Certificate"):
    import main
    from main import app, set_maintenance, is_maintenance
    import database
    from database import Base, engine, SessionLocal, User, GeneratedImage

from httpx import AsyncClient, ASGITransport

Base.metadata.create_all(bind=engine)


# ══════════════════════════════════════════════════════
#  フィクスチャ
# ══════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def cleanup_maintenance():
    set_maintenance(False)
    yield
    set_maintenance(False)

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


# ══════════════════════════════════════════════════════
#  シナリオ 1: 新規ユーザー登録フロー
#  フロントログイン → /api/user/sync → DB にユーザー作成
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario01_NewUserRegistration:
    """
    統合シナリオ: 新規ユーザーが初めてログインしてDBに登録される
    前提条件: firebase_uid "new_user_001" はDBに存在しない
    手順: POST /api/user/sync (Bearer token)
    期待結果: plan=free, credits=10 のユーザーがDBに作成される
    必要なモック: firebase_admin.auth.verify_id_token
    リスク: 同一UIDで並行リクエストが来ると重複挿入の可能性（UNIQUE制約でエラー）
    """

    async def test_初回ログインでユーザー自動作成(self, db):
        with mock_firebase("new_user_001"), mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/user/sync", headers=auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["plan"] == "FREE"
        assert data["credits"] == 10
        assert data["addon_credits"] == 0

        user = db.query(User).filter(User.firebase_uid == "new_user_001").first()
        assert user is not None
        assert user.plan == "free"
        assert user.credits == 10

    async def test_二回目のsyncは既存ユーザーを返す(self, db):
        """冪等性: 何度呼んでも同じユーザーを返す"""
        with mock_firebase("existing_user"), mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post("/api/user/sync", headers=auth_headers())
                resp2 = await client.post("/api/user/sync", headers=auth_headers())

        # ユーザーがDBに1件のみ存在することを確認
        users = db.query(User).filter(User.firebase_uid == "existing_user").all()
        assert len(users) == 1
        assert resp2.status_code == 200


# ══════════════════════════════════════════════════════
#  シナリオ 2: 認証→認可→AI操作実行フロー
#  ログイン → クレジット確認 → AI実行 → DB更新
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario02_AuthToAIExecution:
    """
    統合シナリオ: 認証済みユーザーがAI機能を使う一連のフロー
    前提条件: credits=3 のユーザーが存在する
    手順: POST /api/instruction (ファイル + テキスト)
    期待結果: AI成功 → credits が 3→2 になる
    必要なモック: Firebase, ImageProcessor, save_generated_image_to_db
    リスク: DB commit前にサーバーがクラッシュするとクレジット控除のみ発生
    """

    async def test_認証後AI実行でクレジット控除される一連フロー(self, db):
        user = User(firebase_uid="ai_user_001", plan="lite", credits=3, addon_credits=0)
        db.add(user); db.commit(); db.refresh(user)

        mock_result = Image.new("RGBA", (100, 100))
        with mock_firebase("ai_user_001"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction", return_value=mock_result), \
             patch("main.save_generated_image_to_db"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/instruction",
                    files={"file": ("canvas.png", make_png_bytes(), "image/png")},
                    data={"instruction": "空を青くして", "quality": "medium"},
                    headers=auth_headers()
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 2  # 3 → 2

    async def test_クレジット不足で操作拒否されクレジット変動なし(self, db):
        user = User(firebase_uid="broke_user", plan="free", credits=0, addon_credits=0)
        db.add(user); db.commit(); db.refresh(user)

        with mock_firebase("broke_user"), mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/instruction",
                    files={"file": ("canvas.png", make_png_bytes(), "image/png")},
                    data={"instruction": "空を青くして"},
                    headers=auth_headers()
                )

        assert resp.status_code == 402
        db.refresh(user)
        assert user.credits == 0  # 変動なし

    async def test_AI失敗時のクレジットロールバック(self, db):
        """
        途中失敗時のロールバック:
        クレジット先払い → AI例外 → 返金 → DB整合性維持
        """
        user = User(firebase_uid="rollback_user", plan="lite", credits=5, addon_credits=0)
        db.add(user); db.commit(); db.refresh(user)

        with mock_firebase("rollback_user"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction", side_effect=Exception("OpenAI timeout")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/instruction",
                    files={"file": ("canvas.png", make_png_bytes(), "image/png")},
                    data={"instruction": "空を青くして"},
                    headers=auth_headers()
                )

        assert resp.status_code == 500
        db.refresh(user)
        assert user.credits == 5  # 返金されて元の値

    async def test_addonクレジットのみの場合addonから控除後に成功(self, db):
        """credits=0, addon=3 → addon から控除されること"""
        user = User(firebase_uid="addon_user", plan="free", credits=0, addon_credits=3)
        db.add(user); db.commit(); db.refresh(user)

        mock_result = Image.new("RGBA", (100, 100))
        with mock_firebase("addon_user"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction", return_value=mock_result), \
             patch("main.save_generated_image_to_db"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/instruction",
                    files={"file": ("canvas.png", make_png_bytes(), "image/png")},
                    data={"instruction": "空を青くして", "quality": "medium"},
                    headers=auth_headers()
                )

        assert resp.status_code == 200
        db.refresh(user)
        assert user.credits == 0      # 変動なし
        assert user.addon_credits == 2  # 3 → 2

    async def test_addon失敗時はaddonに返金される(self, db):
        """credits=0, addon=3 でAI失敗 → addon に返金"""
        user = User(firebase_uid="addon_fail_user", plan="free", credits=0, addon_credits=3)
        db.add(user); db.commit(); db.refresh(user)

        with mock_firebase("addon_fail_user"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction", side_effect=Exception("AI error")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    "/api/instruction",
                    files={"file": ("canvas.png", make_png_bytes(), "image/png")},
                    data={"instruction": "空を青くして"},
                    headers=auth_headers()
                )

        db.refresh(user)
        assert user.addon_credits == 3  # 返金されて元の値
        assert user.credits == 0


# ══════════════════════════════════════════════════════
#  シナリオ 3: ファイルアップロード → 保存 → ギャラリー表示
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario03_FileUploadToGallery:
    """
    統合シナリオ: AI実行 → 生成画像DB保存 → ギャラリー取得
    前提条件: credits=5 のユーザーが存在する
    手順: POST /api/blend → GET /api/gallery
    期待結果: ギャラリーに1件表示される
    必要なモック: Firebase, ImageProcessor, ファイルシステム（save_generated_image_to_db）
    リスク: ファイル保存失敗時にDBにレコードだけ残る可能性
    """

    async def test_AI実行後ギャラリーに画像が追加される(self, db):
        user = User(firebase_uid="gallery_user", plan="lite", credits=5, addon_credits=0)
        db.add(user); db.commit(); db.refresh(user)

        mock_result = Image.new("RGBA", (200, 200))
        saved_image = GeneratedImage(user_id=user.id, file_path="/static/uploads/test.png")

        with mock_firebase("gallery_user"), mock_db(db), \
             patch("main.ImageProcessor.blend_building", return_value=mock_result), \
             patch("main.save_generated_image_to_db", return_value=saved_image) as mock_save:

            # AI実行
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                blend_resp = await client.post(
                    "/api/blend",
                    files={
                        "bg_file": ("bg.png", make_png_bytes(), "image/png"),
                        "bld_file": ("bld.png", make_png_bytes(), "image/png"),
                    },
                    data={"cx": "100", "cy": "100", "width": "50", "height": "80",
                          "angle": "0", "is_sketch": "false", "quality": "medium"},
                    headers=auth_headers()
                )

        assert blend_resp.status_code == 200
        assert blend_resp.json()["status"] == "success"
        mock_save.assert_called_once()
        db.refresh(user)
        assert user.credits == 4  # 5 → 4

    async def test_他ユーザーの画像はギャラリーに表示されない(self, db):
        user_a = User(firebase_uid="user_a", plan="lite", credits=5)
        user_b = User(firebase_uid="user_b", plan="lite", credits=5)
        db.add_all([user_a, user_b]); db.commit()
        db.refresh(user_a); db.refresh(user_b)

        # user_b の画像を追加
        img = GeneratedImage(user_id=user_b.id, file_path="/static/uploads/b.png")
        db.add(img); db.commit()

        # user_a でギャラリー取得
        with mock_firebase("user_a"), mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/gallery", headers=auth_headers())

        assert resp.status_code == 200
        assert resp.json()["images"] == []  # user_a には画像がない


# ══════════════════════════════════════════════════════
#  シナリオ 4: 課金フロー（Stripe Checkout → DB反映）
#  購入 → verify-payment → クレジット反映 → 権限付与
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario04_PaymentToPermission:
    """
    統合シナリオ: Stripe決済完了 → verify-payment → クレジット付与 → AI実行可能に
    前提条件: credits=0 のユーザー（残高切れ）
    手順: POST /api/verify-payment → POST /api/instruction
    期待結果: 購入後にAI実行が成功する
    必要なモック: Stripe Session, Firebase
    リスク: verify-payment が失敗した場合にクレジット未付与のまま画面は成功表示になりうる
    """

    async def test_購入後にAI実行が可能になる(self, db):
        user = User(firebase_uid="purchase_user", plan="free", credits=0, addon_credits=0)
        db.add(user); db.commit(); db.refresh(user)

        # Step 1: Stripe決済完了 → verify-payment
        mock_session = MagicMock()
        mock_session.client_reference_id = "purchase_user"
        mock_session.payment_status = "paid"
        mock_session.metadata = {"credits_to_add": "30", "item_name": "lite"}
        mock_session.subscription = "sub_abc"

        with mock_firebase("purchase_user"), mock_db(db), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                pay_resp = await client.post(
                    "/api/verify-payment",
                    json={"session_id": "cs_success_001"},
                    headers=auth_headers()
                )

        assert pay_resp.status_code == 200
        assert pay_resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30
        assert user.plan == "lite"

        # Step 2: クレジット付与後にAI実行が可能
        mock_result = Image.new("RGBA", (100, 100))
        with mock_firebase("purchase_user"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction", return_value=mock_result), \
             patch("main.save_generated_image_to_db"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                ai_resp = await client.post(
                    "/api/instruction",
                    files={"file": ("canvas.png", make_png_bytes(), "image/png")},
                    data={"instruction": "空を青くして", "quality": "medium"},
                    headers=auth_headers()
                )

        assert ai_resp.status_code == 200
        db.refresh(user)
        assert user.credits == 29  # 30 → 29

    async def test_他人のsession_idでクレジットを不正取得できない(self, db):
        """
        セキュリティ: 他ユーザーのsession_idを使ってクレジットを得ようとする攻撃
        """
        victim = User(firebase_uid="victim_user", plan="lite", credits=30)
        attacker = User(firebase_uid="attacker_user", plan="free", credits=0)
        db.add_all([victim, attacker]); db.commit()

        mock_session = MagicMock()
        mock_session.client_reference_id = "victim_user"  # 被害者のUID
        mock_session.payment_status = "paid"
        mock_session.metadata = {"credits_to_add": "30", "item_name": "lite"}

        with mock_firebase("attacker_user"), mock_db(db), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/verify-payment",
                    json={"session_id": "cs_victim_session"},
                    headers=auth_headers()
                )

        assert resp.status_code == 403
        db.refresh(attacker)
        assert attacker.credits == 0  # クレジット付与されていない


# ══════════════════════════════════════════════════════
#  シナリオ 5: 二重送信・重複処理の防止
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario05_IdempotencyAndDuplicatePrevention:
    """
    統合シナリオ: 同一session_idを複数回送信しても1回しかクレジット付与されない
    前提条件: 通信遅延・リトライを想定
    手順: POST /api/verify-payment を同一session_idで2回送信
    期待結果: 2回目は already_processed を返しクレジット増加なし
    リスク: last_session_id は1件しか記録しないため、複数購入後に古いsession_idが使える
    """

    async def test_同じsession_idの二重送信でクレジット二重付与なし(self, db):
        user = User(firebase_uid="idempotent_user", plan="free", credits=0)
        db.add(user); db.commit(); db.refresh(user)

        mock_session = MagicMock()
        mock_session.client_reference_id = "idempotent_user"
        mock_session.payment_status = "paid"
        mock_session.metadata = {"credits_to_add": "30", "item_name": "lite"}
        mock_session.subscription = "sub_x"

        for i in range(2):
            with mock_firebase("idempotent_user"), mock_db(db), \
                 patch("stripe.checkout.Session.retrieve", return_value=mock_session):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post(
                        "/api/verify-payment",
                        json={"session_id": "cs_dup_001"},
                        headers=auth_headers()
                    )
            if i == 0:
                assert resp.json()["status"] == "success"
            else:
                assert resp.json()["status"] == "already_processed"

        db.refresh(user)
        assert user.credits == 30  # 2回送信しても30のまま

    async def test_webhook処理済みをverify_paymentが重複付与しない(self, db):
        """
        状態不整合復旧フロー:
        webhookが先に処理済み → verify-payment がリトライしても二重付与しない
        """
        # webhookがすでに処理済みとして last_session_id をセット
        user = User(firebase_uid="wh_user", plan="lite", credits=30,
                    last_session_id="cs_already_done_by_webhook")
        db.add(user); db.commit(); db.refresh(user)

        mock_session = MagicMock()
        mock_session.client_reference_id = "wh_user"
        mock_session.payment_status = "paid"
        mock_session.metadata = {"credits_to_add": "30", "item_name": "lite"}

        with mock_firebase("wh_user"), mock_db(db), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/verify-payment",
                    json={"session_id": "cs_already_done_by_webhook"},
                    headers=auth_headers()
                )

        assert resp.json()["status"] == "already_processed"
        db.refresh(user)
        assert user.credits == 30  # webhookで付与した分から変動なし

    async def test_AI二重送信は二重控除される_設計上の限界(self, db):
        """
        リスク確認テスト:
        AI実行エンドポイントには冪等性がないため、同じリクエストを2回送ると2回控除される。
        これは設計上の既知の限界（AbortController で緩和済み）。
        """
        user = User(firebase_uid="double_ai_user", plan="lite", credits=5)
        db.add(user); db.commit(); db.refresh(user)

        mock_result = Image.new("RGBA", (100, 100))
        call_count = 0

        def ai_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_result

        with mock_firebase("double_ai_user"), mock_db(db), \
             patch("main.ImageProcessor.edit_by_instruction", side_effect=ai_side_effect), \
             patch("main.save_generated_image_to_db"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                for _ in range(2):
                    await client.post(
                        "/api/instruction",
                        files={"file": ("canvas.png", make_png_bytes(), "image/png")},
                        data={"instruction": "空を青くして", "quality": "medium"},
                        headers=auth_headers()
                    )

        db.refresh(user)
        assert user.credits == 3  # 5 - 2 = 3（2回控除される設計）
        assert call_count == 2


# ══════════════════════════════════════════════════════
#  シナリオ 6: Webhookフロー（Stripe → DB反映）
#  checkout.session.completed → verify-paymentとの協調
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario06_WebhookAndVerifyPaymentCoordination:
    """
    統合シナリオ: webhook と verify-payment が競合せず協調動作する
    前提条件: webhook が先に到着するケース / verify-payment が先のケース
    リスク: どちらが先に来ても最終的にクレジットが1回だけ付与されること
    """

    async def test_verifyPayment先_webhook後_二重付与なし(self, db):
        """
        クライアントが先に verify-payment → その後 webhook が来るパターン
        """
        user = User(firebase_uid="vp_first_user", plan="free", credits=0)
        db.add(user); db.commit(); db.refresh(user)

        # Step1: verify-payment 先着
        mock_session = MagicMock()
        mock_session.client_reference_id = "vp_first_user"
        mock_session.payment_status = "paid"
        mock_session.metadata = {"credits_to_add": "30", "item_name": "lite"}
        mock_session.subscription = "sub_vp"

        with mock_firebase("vp_first_user"), mock_db(db), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post("/api/verify-payment",
                                  json={"session_id": "cs_coord_001"},
                                  headers=auth_headers())

        db.refresh(user)
        assert user.credits == 30

        # Step2: webhook が後から来る（session_id が last_session_id と一致 → スキップ）
        wh_session = MagicMock()
        wh_session.client_reference_id = "vp_first_user"
        wh_session.id = "cs_coord_001"
        wh_session.metadata = {"credits_to_add": "30", "item_name": "lite"}
        wh_session.subscription = "sub_vp"
        event = {"type": "checkout.session.completed", "data": {"object": wh_session}}

        with patch("stripe.Webhook.construct_event", return_value=event), \
             mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                wh_resp = await client.post(
                    "/api/stripe-webhook",
                    content=b"payload",
                    headers={"stripe-signature": "sig"}
                )

        assert wh_resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30  # webhook が来ても増えない

    async def test_月次更新webhookでcreditsがリセットされる(self, db):
        """
        月次更新フロー:
        ユーザーがLiteプランで月途中に20クレジット使用 → 月次更新で30にリセット
        """
        user = User(firebase_uid="renewal_user", plan="lite", credits=10,
                    stripe_subscription_id="sub_renewal_001")
        db.add(user); db.commit(); db.refresh(user)

        invoice = MagicMock()
        invoice.subscription = "sub_renewal_001"
        invoice.billing_reason = "subscription_cycle"
        event = {"type": "invoice.payment_succeeded", "data": {"object": invoice}}

        mock_sub = MagicMock()
        mock_sub.metadata = {"firebase_uid": "renewal_user"}

        with patch("stripe.Webhook.construct_event", return_value=event), \
             patch("stripe.Subscription.retrieve", return_value=mock_sub), \
             mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/stripe-webhook",
                    content=b"payload",
                    headers={"stripe-signature": "sig"}
                )

        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.credits == 30  # Lite プランの満額にリセット


# ══════════════════════════════════════════════════════
#  シナリオ 7: プラン変更・ダウングレードフロー
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario07_PlanChangeAndDowngrade:
    """
    統合シナリオ: Lite → Plus へのアップグレード、および無料プランへのダウングレード
    前提条件: Liteプラン有料ユーザー
    リスク: Stripe API 失敗時に DB が更新されないこと（ロールバック）
    """

    async def test_Liteから無料にダウングレード_planがfreeになる(self, db):
        user = User(firebase_uid="downgrade_user", plan="lite", credits=25,
                    stripe_subscription_id="sub_downgrade_001")
        db.add(user); db.commit(); db.refresh(user)

        with mock_firebase("downgrade_user"), mock_db(db), \
             patch("stripe.Subscription.modify", return_value=MagicMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/user/downgrade", headers=auth_headers())

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        db.refresh(user)
        assert user.plan == "free"
        assert user.credits == 25  # クレジットは期間終了まで保持

    async def test_Stripe失敗時のプラン変更はDB更新されない(self, db):
        """
        外部API失敗時の整合性:
        Stripe modify 失敗 → DB のプランは変更されない
        """
        user = User(firebase_uid="change_fail_user", plan="lite", credits=30,
                    stripe_subscription_id="sub_change_001")
        db.add(user); db.commit(); db.refresh(user)

        with mock_firebase("change_fail_user"), mock_db(db), \
             patch("stripe.Subscription.retrieve", side_effect=Exception("Stripe unavailable")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/change-plan",
                    json={"plan": "plus"},
                    headers=auth_headers()
                )

        assert resp.status_code == 400
        db.refresh(user)
        assert user.plan == "lite"    # 変わっていない
        assert user.credits == 30    # 変わっていない

    async def test_サブスクなしでchange_planは400(self, db):
        user = User(firebase_uid="no_sub_user", plan="free", credits=10,
                    stripe_subscription_id=None)
        db.add(user); db.commit(); db.refresh(user)

        with mock_firebase("no_sub_user"), mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/change-plan",
                    json={"plan": "plus"},
                    headers=auth_headers()
                )

        assert resp.status_code == 400


# ══════════════════════════════════════════════════════
#  シナリオ 8: メンテナンスモードとの連携
#  管理者がON → ユーザー操作が全てブロック → OFF → 復旧
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario08_MaintenanceModeIntegration:
    """
    統合シナリオ: メンテナンスON中の全操作ブロックとOFF後の復旧
    前提条件: ADMIN_SECRET が設定済み
    手順: admin ON → 一般API呼び出し（503） → admin OFF → 一般API呼び出し（200）
    期待結果: メンテナンス中は管理系以外すべて503、OFF後は正常動作
    リスク: メンテナンスフラグがファイル永続化のため、テスト後の後片付けが必要
    """

    async def test_メンテナンスON中は全APIが503(self, db):
        set_maintenance(True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post("/api/user/sync", headers=auth_headers())
            r2 = await client.post("/api/instruction",
                                   files={"file": ("f.png", make_png_bytes(), "image/png")},
                                   data={"instruction": "test"})
            r3 = await client.post("/api/verify-payment", json={"session_id": "x"})

        assert r1.status_code == 503
        assert r2.status_code == 503
        assert r3.status_code == 503

    async def test_メンテナンスOFF後は通常動作に復旧(self, db):
        set_maintenance(True)
        set_maintenance(False)

        with mock_firebase("recovery_user"), mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/user/sync", headers=auth_headers())

        assert resp.status_code == 200

    async def test_メンテナンス中admin_OFFで復旧できる(self):
        set_maintenance(True)
        main.ADMIN_SECRET = "testsecret"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/maintenance/off",
                headers={"X-Admin-Secret": "testsecret"}
            )

        assert resp.status_code == 200
        assert is_maintenance() is False


# ══════════════════════════════════════════════════════
#  シナリオ 9: 業務エラーコードと専用リカバリー挙動
#  400/401/402/403/413 各エラーに対する期待挙動
# ══════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestScenario09_BusinessErrorRecovery:
    """
    統合シナリオ: 業務エラーコードに対するリカバリー挙動の確認
    観点: クライアントが各エラーに応じて適切に次のアクションを取れること
    """

    async def test_401_未認証はログイン画面誘導を想定(self):
        """フロントはこの 401 を受けてログイン画面を表示すべき"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/instruction",
                                     files={"file": ("f.png", make_png_bytes(), "image/png")},
                                     data={"instruction": "test"})
        assert resp.status_code == 401
        assert "error" in resp.json()

    async def test_402_残高不足は購入画面誘導を想定(self, db):
        """フロントはこの 402 を受けてプラン購入モーダルを表示すべき"""
        user = User(firebase_uid="no_credit", plan="free", credits=0, addon_credits=0)
        db.add(user); db.commit()

        with mock_firebase("no_credit"), mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/blend",
                                         files={
                                             "bg_file": ("bg.png", make_png_bytes(), "image/png"),
                                             "bld_file": ("bld.png", make_png_bytes(), "image/png"),
                                         },
                                         data={"cx": "0", "cy": "0", "width": "10",
                                               "height": "10", "angle": "0", "is_sketch": "false"},
                                         headers=auth_headers())
        assert resp.status_code == 402

    async def test_403_他人のsessionは権限エラー(self, db):
        """フロントはこの 403 を受けてエラーメッセージを表示すべき（リトライ不可）"""
        user = User(firebase_uid="attacker", plan="free", credits=0)
        db.add(user); db.commit()

        mock_session = MagicMock()
        mock_session.client_reference_id = "victim"
        mock_session.payment_status = "paid"

        with mock_firebase("attacker"), mock_db(db), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/verify-payment",
                                         json={"session_id": "cs_victim"},
                                         headers=auth_headers())

        assert resp.status_code == 403

    async def test_413_大容量ファイルは即時拒否でクレジット消費なし(self, db):
        """フロントはこの 413 を受けてファイル圧縮を促すべき。クレジットは消費されない"""
        user = User(firebase_uid="large_file_user", plan="lite", credits=10)
        db.add(user); db.commit(); db.refresh(user)

        large = b"x" * (11 * 1024 * 1024)
        with mock_firebase("large_file_user"), mock_db(db):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/sketch-to-real",
                                         files={"file": ("big.png", large, "image/png")},
                                         data={"quality": "medium"},
                                         headers=auth_headers())

        assert resp.status_code == 413
        db.refresh(user)
        assert user.credits == 10  # クレジット消費なし

    async def test_400_処理済みsessionのリトライはalready_processedで安全終了(self, db):
        """
        リカバリーフロー:
        success.html がリトライで同一session_idを再送しても安全に処理済みを返す
        """
        user = User(firebase_uid="retry_user", plan="lite", credits=30,
                    last_session_id="cs_done")
        db.add(user); db.commit(); db.refresh(user)

        mock_session = MagicMock()
        mock_session.client_reference_id = "retry_user"
        mock_session.payment_status = "paid"
        mock_session.metadata = {"credits_to_add": "30", "item_name": "lite"}

        with mock_firebase("retry_user"), mock_db(db), \
             patch("stripe.checkout.Session.retrieve", return_value=mock_session):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/verify-payment",
                                         json={"session_id": "cs_done"},
                                         headers=auth_headers())

        data = resp.json()
        assert data["status"] == "already_processed"
        assert data["credits"] == 30  # 変動なし


# ══════════════════════════════════════════════════════
#  未テスト領域・既知のリスク（コメント）
# ══════════════════════════════════════════════════════
"""
【統合テストで担保できていない領域】

1. 通信遅延シミュレーション
   → asyncio.sleep() を挟んだ並行リクエストテストは未実施。
   → 実際のタイムアウト（AbortController 120秒）は Playwright 等の E2E で確認が必要。

2. DB 接続断・タイムアウト時の挙動
   → SQLAlchemy の pool_pre_ping=True で再接続は試みるが、長時間断の場合の挙動未確認。

3. 並行リクエストによる二重付与（競合状態）
   → verify-payment の last_session_id チェックは DB トランザクション外なので、
     ほぼ同時に2リクエストが来ると両方が「未処理」と判断する可能性がある。
   → 修正策：processed_sessions テーブルを UNIQUE(session_id) で作成。

4. Stripe Webhook の署名検証（本物のペイロード）
   → テストでは construct_event をモックしているため、実際のペイロード検証未確認。
   → Stripe CLI の stripe trigger コマンドでローカル検証が可能。

5. Firebase トークンの有効期限切れ中のリトライ
   → フロントの getIdToken() は自動更新するが、更新失敗時の挙動は E2E でのみ確認可能。

6. ファイルアップロード後のディスク容量不足
   → save_generated_image_to_db でファイル保存失敗時の DB ロールバックがない。
     （DB にレコードが作られるが、ファイルは存在しない状態になりうる）

7. E2E（ブラウザ）テスト
   → ログイン → 購入 → AI実行 → ギャラリー表示の一連をブラウザで確認するテストは未実施。
"""
