from fastapi import FastAPI, File, UploadFile, Form, Header, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db, User, GeneratedImage
from dotenv import load_dotenv
import os
import io
import base64
import uvicorn
from PIL import Image
import smtplib
from email.mime.text import MIMEText
import threading
import traceback
import time
import uuid
import stripe
import json
from fastapi import Request
from apscheduler.schedulers.background import BackgroundScheduler

# .envファイルを読み込み（サーバー側にAPIキーを固定）
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:8000")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
print(f"DEBUG: Stripe API Key starts with: {stripe.api_key[:7] if stripe.api_key else 'None'}")

from logic.image_processor import ImageProcessor

app = FastAPI(title="PersImage SaaS - 建物パース合成")

PLAN_CREDITS = {"lite": 30, "plus": 70, "max": 200}

def monthly_credit_reset():
    """毎月1日にStripe webhookの補完として有料プランのcreditsをリセット"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        paid_users = db.query(User).filter(User.plan.in_(["lite", "plus", "max"])).all()
        for user in paid_users:
            allocation = PLAN_CREDITS.get(user.plan, 0)
            if allocation > 0:
                user.credits = allocation
        db.commit()
        print(f"[monthly_credit_reset] {len(paid_users)}人のクレジットをリセットしました")
    except Exception as e:
        print(f"[monthly_credit_reset] エラー: {e}")
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    import database
    from sqlalchemy import inspect, text
    print("--- データベーステーブル作成 & 更新開始 ---")
    database.Base.metadata.create_all(bind=database.engine)
    
    # データベースのマイグレーション（PostgreSQL/SQLite両対応）
    try:
        inspector = inspect(database.engine)
        columns = [c['name'] for c in inspector.get_columns('users')]
        if "stripe_subscription_id" not in columns:
            print("Adding missing column: stripe_subscription_id")
            with database.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR"))
                conn.commit()
        if "addon_credits" not in columns:
            print("Adding missing column: addon_credits")
            with database.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN addon_credits INTEGER DEFAULT 0"))
                conn.commit()
        if "last_session_id" not in columns:
            print("Adding missing column: last_session_id")
            with database.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN last_session_id VARCHAR"))
                conn.commit()
    except Exception as e:
        print(f"Migration error: {e}")
        
    print("--- データベース更新完了 ---")

    # 月次クレジットリセットスケジューラー起動
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
    scheduler.add_job(monthly_credit_reset, 'cron', day=1, hour=3, minute=0)
    scheduler.start()
    print("--- 月次リセットスケジューラー起動完了（毎月1日 3:00 JST）---")

ERROR_COOLDOWN_SECONDS = 3600  # 同じエラーメールは1時間に1度のみ送信
last_error_times = {}

def send_error_email_task(base_error: str, traceback_str: str):
    current_time = time.time()
    
    # レートリミット（スパム防止）: 同じエラーは指定時間送らない
    if base_error in last_error_times:
        if current_time - last_error_times[base_error] < ERROR_COOLDOWN_SECONDS:
            print(f"Skipped sending email for repeated error: {base_error}")
            return
            
    # 送信履歴を更新
    last_error_times[base_error] = current_time

    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    
    if not all([smtp_server, smtp_user, smtp_pass]):
        print("SMTP settings are missing. Would have sent email to tatsuya.takemura@gmail.com with error:\n", traceback_str)
        return

    msg = MIMEText(f"建物パース合成ツール（Web版）でシステムエラーが発生しました。\n\n【エラー内容】\n{base_error}\n\n【システム詳細（Traceback）】\n{traceback_str}")
    msg['Subject'] = '【エラー通知】パース合成ツール システムエラー'
    msg['From'] = smtp_user
    msg['To'] = 'tatsuya.takemura@gmail.com'

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print("Error email sent successfully.")
    except Exception as e:
        print(f"Failed to send error email: {e}")

os.makedirs("static", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

def save_generated_image_to_db(user_id: int, img_data: Image.Image, db: Session):
    file_name = f"{uuid.uuid4()}.png"
    rel_path = f"static/uploads/{file_name}"
    img_data.save(rel_path, format="PNG")
    new_img = GeneratedImage(user_id=user_id, file_path=f"/{rel_path}")
    db.add(new_img)
    return new_img

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

def pil_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

async def get_current_user(x_user_id: str = Header(None), db: Session = Depends(get_db)):
    if not x_user_id:
        return None
    user = db.query(User).filter(User.firebase_uid == x_user_id).first()
    if not user:
        user = User(firebase_uid=x_user_id, credits=10, plan="free")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@app.post("/api/user/sync")
async def sync_user(db: Session = Depends(get_db), x_user_id: str = Header(None)):
    print(f"--- ユーザー同期中: {x_user_id} ---")
    if not x_user_id:
        print("X-User-ID ヘッダーがありません")
        return {"error": "User ID missing"}
    
    user = db.query(User).filter(User.firebase_uid == x_user_id).first()
    if not user:
        print(f"新規ユーザー作成: {x_user_id}")
        user = User(firebase_uid=x_user_id, credits=10, plan="free")
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        print(f"既存ユーザー確認: {x_user_id}, プラン: {user.plan}, クレジット: {user.credits}")
    addon = user.addon_credits if user.addon_credits is not None else 0
    return {"status": "success", "credits": user.credits, "addon_credits": addon, "plan": user.plan.upper()}

@app.get("/api/gallery")
async def get_gallery(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    images = db.query(GeneratedImage).filter(GeneratedImage.user_id == user.id).order_by(GeneratedImage.created_at.desc()).all()
    return {"status": "success", "images": [{"id": i.id, "url": i.file_path, "created_at": i.created_at.isoformat()} for i in images]}

@app.delete("/api/gallery/{image_id}")
async def delete_gallery_image(image_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
    img = db.query(GeneratedImage).filter(GeneratedImage.id == image_id, GeneratedImage.user_id == user.id).first()
    if not img:
        return JSONResponse(status_code=404, content={"error": "画像が見つかりません。"})
        
    # 必要に応じてローカルファイルも削除
    if img.file_path:
        file_system_path = img.file_path.lstrip('/')
        if os.path.exists(file_system_path):
            try:
                os.remove(file_system_path)
            except Exception as e:
                print(f"Failed to delete file {file_system_path}: {e}")
                
    db.delete(img)
    db.commit()
    return {"status": "success", "message": "Deleted successfully."}

@app.post("/api/upload")
async def upload_bg(file: UploadFile = File(...)):
    return {"filename": file.filename, "status": "success", "message": "Background received."}

@app.post("/api/sketch-to-real")
async def sketch_to_real(
    file: UploadFile = File(...),
    quality: str = Form("medium"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手書きイラストをフォトリアルに変換（OpenAI連携）"""
    if not OPENAI_API_KEY or OPENAI_API_KEY == "ここにOpenAIのAPIキーを貼り付けてください":
        return JSONResponse(status_code=500, content={"error": "OPENAI_API_KEYがバックエンドに設定されていません"})
    if not user:
        return JSONResponse(status_code=401, content={"error": "ログインが必要です。"})
    total = user.credits + (user.addon_credits or 0)
    if total <= 0:
        return JSONResponse(status_code=402, content={"error": "チケット残高が不足しています。"})

    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGBA")
        # 既存のロジックをそのまま利用
        result_img = ImageProcessor.sketch_to_realistic(img, api_token=OPENAI_API_KEY, quality=quality)

        if user.credits > 0:
            user.credits -= 1
        else:
            user.addon_credits -= 1
        save_generated_image_to_db(user.id, result_img, db)
        db.commit()
        
        b64 = pil_to_base64(result_img)
        return {"status": "success", "image_base64": f"data:image/png;base64,{b64}", "credits_remaining": user.credits}
    except Exception as e:
        base_err = str(e)
        err_msg = traceback.format_exc()
        threading.Thread(target=send_error_email_task, args=(base_err, err_msg)).start()
        return JSONResponse(status_code=500, content={"error": "大変申し訳ございません。ただいまご利用できない状況です。しばらく経ってからアクセス願います。"})

@app.post("/api/instruction")
async def edit_instruction(
    file: UploadFile = File(...),
    instruction: str = Form(...),
    quality: str = Form("medium"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """テキスト指示による画像編集（OpenAI連携）"""
    if not OPENAI_API_KEY or OPENAI_API_KEY == "ここにOpenAIのAPIキーを貼り付けてください":
        return JSONResponse(status_code=500, content={"error": "OPENAI_API_KEYがバックエンドに設定されていません"})
    if not user:
        return JSONResponse(status_code=401, content={"error": "ログインが必要です。"})
    total = user.credits + (user.addon_credits or 0)
    if total <= 0:
        return JSONResponse(status_code=402, content={"error": "チケット残高が不足しています。"})

    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGBA")
        result_img = ImageProcessor.edit_by_instruction(img, instruction, api_token=OPENAI_API_KEY, quality=quality)

        if user.credits > 0:
            user.credits -= 1
        else:
            user.addon_credits -= 1
        save_generated_image_to_db(user.id, result_img, db)
        db.commit()
        
        b64 = pil_to_base64(result_img)
        return {"status": "success", "image_base64": f"data:image/png;base64,{b64}", "credits_remaining": user.credits}
    except Exception as e:
        base_err = str(e)
        err_msg = traceback.format_exc()
        threading.Thread(target=send_error_email_task, args=(base_err, err_msg)).start()
        return JSONResponse(status_code=500, content={"error": "大変申し訳ございません。ただいまご利用できない状況です。しばらく経ってからアクセス願います。"})

@app.post("/api/blend")
async def blend_endpoint(
    bg_file: UploadFile = File(...),
    bld_file: UploadFile = File(...),
    cx: float = Form(...),
    cy: float = Form(...),
    width: float = Form(...),
    height: float = Form(...),
    angle: float = Form(...),
    is_sketch: bool = Form(False),
    quality: str = Form("medium"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """建物を背景に馴染ませる（ポアソンブレンディング＋OpenAI仕上げ）"""
    if not OPENAI_API_KEY or OPENAI_API_KEY == "ここにOpenAIのAPIキーを貼り付けてください":
        return JSONResponse(status_code=500, content={"error": "OPENAI_API_KEYがバックエンドに設定されていません"})
    if not user:
        return JSONResponse(status_code=401, content={"error": "ログインが必要です。"})
    total = user.credits + (user.addon_credits or 0)
    if total <= 0:
        return JSONResponse(status_code=402, content={"error": "チケット残高が不足しています。"})

    try:
        bg_contents = await bg_file.read()
        bld_contents = await bld_file.read()
        bg_img = Image.open(io.BytesIO(bg_contents)).convert("RGBA")
        bld_img = Image.open(io.BytesIO(bld_contents)).convert("RGBA")

        result_img = ImageProcessor.blend_building(
            background=bg_img,
            building=bld_img,
            center_x=int(cx),
            center_y=int(cy),
            width=int(width),
            height=int(height),
            angle=angle,
            api_token=OPENAI_API_KEY,
            is_sketch=is_sketch,
            quality=quality
        )

        if user.credits > 0:
            user.credits -= 1
        else:
            user.addon_credits -= 1
        save_generated_image_to_db(user.id, result_img, db)
        db.commit()
        
        b64 = pil_to_base64(result_img)
        return {"status": "success", "image_base64": f"data:image/png;base64,{b64}", "credits_remaining": user.credits}
    except Exception as e:
        base_err = str(e)
        err_msg = traceback.format_exc()
        threading.Thread(target=send_error_email_task, args=(base_err, err_msg)).start()
        return JSONResponse(status_code=500, content={"error": "大変申し訳ございません。ただいまご利用できない状況です。しばらく経ってからアクセス願います。"})

@app.post("/api/match-color")
async def match_color_endpoint(
    bg_file: UploadFile = File(...),
    bld_file: UploadFile = File(...)
):
    try:
        bg_contents = await bg_file.read()
        bld_contents = await bld_file.read()
        bg_img = Image.open(io.BytesIO(bg_contents)).convert("RGBA")
        bld_img = Image.open(io.BytesIO(bld_contents)).convert("RGBA")
        
        result_img = ImageProcessor.match_color_tone(bld_img, bg_img)
        b64 = pil_to_base64(result_img)
        return {"status": "success", "image_base64": f"data:image/png;base64,{b64}"}
    except Exception as e:
        base_err = str(e)
        err_msg = traceback.format_exc()
        threading.Thread(target=send_error_email_task, args=(base_err, err_msg)).start()
        return JSONResponse(status_code=500, content={"error": "大変申し訳ございません。ただいまご利用できない状況です。しばらく経ってからアクセス願います。"})

@app.get("/success", response_class=HTMLResponse)
async def read_success():
    with open("static/success.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/verify-payment")
async def verify_payment(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Stripe session_idで支払いを確認し、DBを直接更新する（webhook遅延の補完）"""
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        return JSONResponse(status_code=400, content={"error": "session_id required"})

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    # 支払い未完了は無視
    if session.payment_status not in ("paid", "no_payment_required"):
        return {"status": "pending"}

    metadata = session.metadata or {}
    credits_to_add = int(getattr(metadata, 'credits_to_add', None) or 0)
    item_name = getattr(metadata, 'item_name', None)

    # 二重付与防止: session_idを確認済みとして記録
    already_processed = db.query(User).filter(
        User.firebase_uid == user.firebase_uid,
        User.last_session_id == session_id
    ).first()
    if already_processed:
        addon = user.addon_credits if user.addon_credits is not None else 0
        return {"status": "already_processed", "credits": user.credits, "addon_credits": addon}

    if item_name in ("lite", "plus", "max"):
        user.credits = credits_to_add
        user.plan = item_name
        sub_id = getattr(session, 'subscription', None)
        if sub_id:
            user.stripe_subscription_id = sub_id
    else:
        user.addon_credits = (user.addon_credits or 0) + credits_to_add

    user.last_session_id = session_id
    db.commit()
    db.refresh(user)
    addon = user.addon_credits if user.addon_credits is not None else 0
    print(f"verify-payment: user={user.firebase_uid}, item={item_name}, credits={user.credits}, addon={addon}")
    return {"status": "success", "credits": user.credits, "addon_credits": addon}

class CheckoutRequest(BaseModel):
    plan: str = None
    addon: str = None

@app.post("/api/create-checkout-session")
async def create_checkout_session(request: CheckoutRequest, user: User = Depends(get_current_user)):
    # サブスクリプションプランの設定
    sub_configs = {
        "lite": {
            "price_id": os.getenv("STRIPE_PRICE_ID_LITE", "price_dummy_lite"),
            "credits": 30
        },
        "plus": {
            "price_id": os.getenv("STRIPE_PRICE_ID_PLUS", "price_dummy_plus"),
            "credits": 70
        },
        "max": {
            "price_id": os.getenv("STRIPE_PRICE_ID_MAX", "price_dummy_max"),
            "credits": 200
        },
    }

    addon_configs = {}

    if request.plan:
        config = sub_configs.get(request.plan)
        mode = 'subscription'
    elif request.addon:
        config = addon_configs.get(request.addon)
        mode = 'payment'
    else:
        return JSONResponse(status_code=400, content={"error": "プランまたはアドオンを選択してください"})

    if not config:
        return JSONResponse(status_code=400, content={"error": "無効なアイテムが選択されました"})

    try:
        # デバッグログ
        print(f"--- Stripe Session Creation Start ---")
        print(f"Price ID: {config['price_id']}")
        print(f"User firebase_uid: {user.firebase_uid}")
        
        metadata = {
            "firebase_uid": user.firebase_uid,
            "type": mode,
            "item_name": request.plan or request.addon,
            "credits_to_add": str(config["credits"])  # メタデータは文字列である必要がある
        }

        session_kwargs = {
            "payment_method_types": ['card'],
            "line_items": [{'price': config["price_id"], 'quantity': 1}],
            "mode": mode,
            "success_url": f"{FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{FRONTEND_URL}/",
            "client_reference_id": user.firebase_uid,
            "metadata": metadata
        }

        # サブスクリプションの場合、メタデータをサブスクリプション自体にも伝播させる
        if mode == 'subscription':
            session_kwargs["subscription_data"] = {
                "metadata": metadata
            }

        checkout_session = stripe.checkout.Session.create(**session_kwargs)
        print(f"SUCCESS: Session ID: {checkout_session.id}")
        return {"url": checkout_session.url}
        
    except Exception as e:
        import traceback
        print("!!! STRIPE API ERROR !!!")
        print(traceback.format_exc())
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        # 無効なペイロード
        return JSONResponse(status_code=400, content={"error": "Invalid payload"})
    except stripe.error.SignatureVerificationError as e:
        # 無効な署名
        return JSONResponse(status_code=400, content={"error": "Invalid signature"})

    # 1. 初回のサブスク開始時（または単発購入時）
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        firebase_uid = getattr(session, 'client_reference_id', None)
        metadata = getattr(session, 'metadata', None) or {}
        credits_to_add = int(getattr(metadata, 'credits_to_add', None) or 0)
        item_name = getattr(metadata, 'item_name', None)

        print(f"Webhook (session.completed) - firebase_uid: {firebase_uid}, credits: {credits_to_add}, item: {item_name}")

        if firebase_uid:
            user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
            if user:
                # 二重付与防止: verify-payment で処理済みならスキップ
                session_id = getattr(session, 'id', None)
                if session_id and user.last_session_id == session_id:
                    print(f"SKIPPED: session {session_id} already processed by verify-payment")
                else:
                    if item_name in ('lite', 'plus', 'max'):
                        # サブスク初回: クレジットをリセット付与・プラン更新
                        user.credits = credits_to_add
                        user.plan = item_name
                        sub_id = getattr(session, 'subscription', None)
                        if sub_id:
                            user.stripe_subscription_id = sub_id
                    else:
                        # アドオン単発購入: addon_credits に加算
                        user.addon_credits = (user.addon_credits or 0) + credits_to_add

                    user.last_session_id = session_id
                    db.commit()
                    print(f"SUCCESS: User {firebase_uid} updated - Credits: {user.credits}, Addon: {user.addon_credits}, Plan: {user.plan}")
            else:
                print(f"ERROR: User {firebase_uid} not found in DB")
        else:
            print(f"ERROR: No client_reference_id in session")

    # 2. 2ヶ月目以降の更新支払い成功時
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        sub_id = getattr(invoice, 'subscription', None)
        if not sub_id:
            return {"status": "skipped - no subscription id"}

        print(f"Webhook (invoice.payment_succeeded) - sub_id: {sub_id}")

        # サブスクリプション詳細を取得してメタデータから情報を復元
        try:
            subscription = stripe.Subscription.retrieve(sub_id)
            sub_metadata = getattr(subscription, 'metadata', None) or {}
            firebase_uid = getattr(sub_metadata, 'firebase_uid', None)
            credits_to_add = int(getattr(sub_metadata, 'credits_to_add', None) or 30)

            if firebase_uid:
                user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
                if user:
                    # 毎月リセット: サブスク分は繰り越しせず上書き
                    user.credits = credits_to_add
                    db.commit()
                    print(f"SUCCESS: Reset credits to {credits_to_add} for user {firebase_uid} (monthly renewal)")
                else:
                    print(f"ERROR: User {firebase_uid} not found for subscription {sub_id}")
            else:
                print(f"ERROR: No firebase_uid in subscription metadata for {sub_id}")
        except Exception as e:
            print(f"ERROR: Failed to process recurring payment: {e}")
    
    return {"status": "success"}

@app.post("/api/change-plan")
async def change_plan(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """既存サブスクリプションのプラン変更（日割り精算）"""
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    body = await request.json()
    new_plan = body.get("plan")

    plan_configs = {
        "lite": {"price_id": os.getenv("STRIPE_PRICE_ID_LITE", "price_dummy_lite"), "credits": 30},
        "plus": {"price_id": os.getenv("STRIPE_PRICE_ID_PLUS", "price_dummy_plus"), "credits": 70},
        "max":  {"price_id": os.getenv("STRIPE_PRICE_ID_MAX", "price_dummy_max"),  "credits": 200},
    }

    config = plan_configs.get(new_plan)
    if not config:
        return JSONResponse(status_code=400, content={"error": "無効なプランです"})

    if not user.stripe_subscription_id:
        return JSONResponse(status_code=400, content={"error": "有効なサブスクリプションがありません"})

    try:
        subscription = stripe.Subscription.retrieve(user.stripe_subscription_id)
        item_id = subscription["items"]["data"][0]["id"]

        stripe.Subscription.modify(
            user.stripe_subscription_id,
            items=[{"id": item_id, "price": config["price_id"]}],
            proration_behavior="create_prorations",
            metadata={
                "firebase_uid": user.firebase_uid,
                "credits_to_add": str(config["credits"]),
                "item_name": new_plan,
            }
        )

        user.plan = new_plan
        user.credits = config["credits"]
        db.commit()

        print(f"change-plan: user={user.firebase_uid}, plan={new_plan}, credits={config['credits']}")
        return {"status": "success", "plan": new_plan, "credits": config["credits"]}
    except Exception as e:
        print(f"change-plan error: {e}")
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/user/downgrade")
async def downgrade_user(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
    # 無料プランに変更（サブスク分はゼロ、追加購入分は保持）
    user.plan = 'free'
    user.credits = 0
    
    # Stripeのサブスクリプションがあれば解約予約（期間終了時に停止）
    if user.stripe_subscription_id:
        try:
            stripe.Subscription.modify(
                user.stripe_subscription_id,
                cancel_at_period_end=True
            )
            print(f"Stripe subscription {user.stripe_subscription_id} set to cancel at period end.")
        except Exception as e:
            print(f"Stripe cancellation warning: {e}")

    db.commit()
    return {"status": "success", "message": "無料プランに変更されました。現在の期間終了後に自動更新が停止します。"}

@app.post("/api/add-credits")
async def add_credits(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # デバッグ用/デモ用: 実際にはStripe経由のみにする場合はここを削除
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    user.credits += 10
    db.commit()
    db.refresh(user)
    return {"status": "success", "credits": user.credits}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
