from fastapi import FastAPI, File, UploadFile, Form, Header, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
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
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials as fb_credentials

# .envファイルを読み込み（サーバー側にAPIキーを固定）
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:8000")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

# Firebase Admin SDK 初期化（IDトークン検証用）
if not firebase_admin._apps:
    _sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not _sa_json:
        raise RuntimeError("FATAL: FIREBASE_SERVICE_ACCOUNT_JSON is not set. Set this environment variable before starting the server.")
    _cred = fb_credentials.Certificate(json.loads(_sa_json))
    firebase_admin.initialize_app(_cred)

from logic.image_processor import ImageProcessor

app = FastAPI(title="Pars Image SaaS - 建物パース合成")

# ── メンテナンスモード（ファイルで永続化：再起動後も維持） ──
MAINTENANCE_FLAG_FILE = "/tmp/maintenance.flag"

def is_maintenance() -> bool:
    return os.path.exists(MAINTENANCE_FLAG_FILE)

def set_maintenance(on: bool):
    if on:
        open(MAINTENANCE_FLAG_FILE, "w").close()
    else:
        if os.path.exists(MAINTENANCE_FLAG_FILE):
            os.remove(MAINTENANCE_FLAG_FILE)

MAINTENANCE_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>メンテナンス中 - Pars Image</title>
  <style>
    body { font-family: 'Helvetica Neue', sans-serif; background: #f3f4f6;
           display: flex; align-items: center; justify-content: center;
           height: 100vh; margin: 0; }
    .box { background: #fff; border-radius: 12px; padding: 48px 40px;
           text-align: center; max-width: 480px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }
    h1 { font-size: 20px; color: #111827; margin-bottom: 16px; }
    p  { font-size: 14px; color: #6b7280; line-height: 1.7; margin: 0; }
  </style>
</head>
<body>
  <div class="box">
    <h1>🔧 メンテナンス中</h1>
    <p>大変申し訳ございません。<br>ただいまメンテナンス中です。<br>しばらく時間をおいてから、再度アクセスしてください。</p>
  </div>
</body>
</html>"""

@app.middleware("http")
async def maintenance_middleware(request: Request, call_next):
    if is_maintenance():
        path = request.url.path
        if path.startswith("/api/admin/"):
            return await call_next(request)
        return HTMLResponse(content=MAINTENANCE_HTML, status_code=503)
    return await call_next(request)

@app.post("/api/admin/maintenance/on")
async def maintenance_on(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _check_admin_rate_limit(ip):
        return JSONResponse(status_code=429, content={"error": "Too many attempts. Try again later."})
    secret = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        _record_admin_failure(ip)
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    set_maintenance(True)
    print("MAINTENANCE MODE: ON")
    return {"status": "maintenance_on"}

@app.post("/api/admin/maintenance/off")
async def maintenance_off(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _check_admin_rate_limit(ip):
        return JSONResponse(status_code=429, content={"error": "Too many attempts. Try again later."})
    secret = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        _record_admin_failure(ip)
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    set_maintenance(False)
    print("MAINTENANCE MODE: OFF")
    return {"status": "maintenance_off"}

@app.post("/api/admin/fix-user-plan")
async def admin_fix_user_plan(request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if not _check_admin_rate_limit(ip):
        return JSONResponse(status_code=429, content={"error": "Too many attempts. Try again later."})
    secret = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        _record_admin_failure(ip)
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    body = await request.json()
    firebase_uid = body.get("firebase_uid")
    plan = body.get("plan")
    credits = body.get("credits")
    if not firebase_uid or not plan or credits is None:
        return JSONResponse(status_code=400, content={"error": "firebase_uid, plan, credits are required"})
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    old_plan = user.plan
    old_credits = user.credits
    user.plan = plan
    user.credits = int(credits)
    stripe_subscription_id = body.get("stripe_subscription_id")
    if stripe_subscription_id:
        user.stripe_subscription_id = stripe_subscription_id
    db.commit()
    print(f"ADMIN FIX: uid={mask_uid(firebase_uid)} plan={old_plan}->{plan} credits={old_credits}->{credits} sub={stripe_subscription_id}")
    return {"status": "success", "firebase_uid": mask_uid(firebase_uid), "plan": user.plan, "credits": user.credits, "stripe_subscription_id": user.stripe_subscription_id}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # APIエンドポイントはJSONでエラーを返す
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=500, content={"error": "大変申し訳ございません。ただいまご利用できない状況です。しばらく経ってからアクセス願います。"})
    # 画面ページはメンテナンス画面を表示
    return HTMLResponse(content=MAINTENANCE_HTML, status_code=503)


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
        if "terms_agreed" not in columns:
            print("Adding missing column: terms_agreed")
            with database.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN terms_agreed BOOLEAN DEFAULT FALSE"))
                conn.commit()
    except Exception as e:
        print(f"Migration error: {e}")

    # last_session_id にユニークインデックス追加（NULL除く、二重付与DB制約）
    try:
        with database.engine.connect() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uix_users_last_session_id "
                "ON users(last_session_id) WHERE last_session_id IS NOT NULL"
            ))
            conn.commit()
        print("Unique index on last_session_id: OK")
    except Exception as e:
        print(f"Migration error (unique index): {e}")

    print("--- データベース更新完了 ---")


def mask_uid(uid) -> str:
    """firebase_uid をログ出力用にマスク（先頭4文字のみ表示）"""
    if not uid:
        return "unknown"
    return str(uid)[:4] + "..."

# 管理APIのIPベースレート制限（5回失敗/15分でブロック）
_admin_attempts: dict = {}
_ADMIN_RATE_LIMIT_MAX = 5
_ADMIN_RATE_LIMIT_WINDOW = 900  # 15分

# AI/課金系エンドポイントのユーザーIDベースレート制限
_rate_limit_store: dict = {}
_RATE_LIMIT_WINDOW = 60  # 1分
_RATE_LIMIT_AI_MAX = 5        # AI系（blend/instruction/sketch-to-real）: 1分5回
_RATE_LIMIT_PAYMENT_MAX = 10  # 課金系（verify-payment/checkout）: 1分10回

def _check_rate_limit(key: str, max_requests: int) -> bool:
    """True=許可、False=レート制限中。リクエスト成功時にカウントを記録する"""
    now = time.time()
    timestamps = [t for t in _rate_limit_store.get(key, []) if now - t < _RATE_LIMIT_WINDOW]
    if len(timestamps) >= max_requests:
        _rate_limit_store[key] = timestamps
        return False
    timestamps.append(now)
    _rate_limit_store[key] = timestamps
    return True

def _check_admin_rate_limit(ip: str) -> bool:
    """True=許可、False=レート制限中"""
    now = time.time()
    attempts = [t for t in _admin_attempts.get(ip, []) if now - t < _ADMIN_RATE_LIMIT_WINDOW]
    _admin_attempts[ip] = attempts
    return len(attempts) < _ADMIN_RATE_LIMIT_MAX

def _record_admin_failure(ip: str):
    _admin_attempts.setdefault(ip, []).append(time.time())

ERROR_COOLDOWN_SECONDS = 1800  # 同じエラーメールは30分に1度のみ送信
last_error_times = {}

def send_error_email_task(base_error: str, traceback_str: str, user_id: str = None):
    import datetime
    current_time = time.time()

    # レートリミット（スパム防止）: 同じエラーは30分送らない
    if base_error in last_error_times:
        if current_time - last_error_times[base_error] < ERROR_COOLDOWN_SECONDS:
            print(f"Skipped sending email for repeated error: {base_error}")
            return

    last_error_times[base_error] = current_time

    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uid_str = user_id or "不明"

    body = (
        f"Pars Imageでシステムエラーが発生しました。\n\n"
        f"【日時】\n{now_str}\n\n"
        f"【ユーザーID】\n{uid_str}\n\n"
        f"【エラー内容】\n{base_error}\n\n"
        f"【詳細（Traceback）】\n{traceback_str}"
    )

    if not all([smtp_server, smtp_user, smtp_pass]):
        print(f"SMTP未設定のためメール送信スキップ:\n{body}")
        return

    msg = MIMEText(body)
    msg['Subject'] = '【エラー通知】Pars Image システムエラー'
    msg['From'] = smtp_user
    msg['To'] = 'tatsuya.takemura@gmail.com'

    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print("Error email sent successfully.")
    except Exception as e:
        print(f"Failed to send error email: {e}")

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/robots.txt")
async def robots_txt():
    return FileResponse("static/robots.txt", media_type="text/plain")

@app.get("/sitemap.xml")
async def sitemap_xml():
    return FileResponse("static/sitemap.xml", media_type="application/xml")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

def pil_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

async def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        return None
    id_token = authorization.split(" ", 1)[1]
    try:
        decoded = firebase_auth.verify_id_token(id_token, check_revoked=True)
        firebase_uid = decoded["uid"]
    except Exception as e:
        print(f"Token verification failed: {e}")
        return None
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        user = User(firebase_uid=firebase_uid, credits=10, plan="free")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@app.post("/api/user/sync")
async def sync_user(db: Session = Depends(get_db), authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    id_token = authorization.split(" ", 1)[1]
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        firebase_uid = decoded["uid"]
    except Exception as e:
        print(f"sync_user token error: {e}")
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        user = User(firebase_uid=firebase_uid, credits=10, plan="free")
        db.add(user)
        db.commit()
        db.refresh(user)
    addon = user.addon_credits if user.addon_credits is not None else 0
    return {"status": "success", "credits": user.credits, "addon_credits": addon, "plan": user.plan.upper(), "terms_agreed": bool(user.terms_agreed)}

@app.post("/api/user/agree-terms")
async def agree_terms(db: Session = Depends(get_db), authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    id_token = authorization.split(" ", 1)[1]
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        firebase_uid = decoded["uid"]
    except Exception:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    user.terms_agreed = True
    db.commit()
    return {"status": "success"}


@app.get("/api/pic-list")
async def pic_list():
    pic_dir = os.path.join(os.path.dirname(__file__), "static", "pic")
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    files = sorted([f for f in os.listdir(pic_dir) if os.path.splitext(f)[1].lower() in exts]) if os.path.isdir(pic_dir) else []
    return {"images": [f"/static/pic/{f}" for f in files]}


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
async def upload_bg(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    if not user:
        return JSONResponse(status_code=401, content={"error": "ログインが必要です。"})
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
    if not _check_rate_limit(f"ai:{user.firebase_uid}", _RATE_LIMIT_AI_MAX):
        return JSONResponse(status_code=429, content={"error": "リクエストが多すぎます。しばらく経ってから再度お試しください。"})
    total = user.credits + (user.addon_credits or 0)
    if total <= 0:
        return JSONResponse(status_code=402, content={"error": "チケット残高が不足しています。"})

    if quality not in ("high", "medium", "low"):
        quality = "medium"

    try:
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"error": "ファイルサイズが大きすぎます（上限10MB）"})
        img = Image.open(io.BytesIO(contents)).convert("RGBA")

        # クレジット先払い（AI失敗時は返金）
        deducted_from = "credits" if user.credits > 0 else "addon"
        if deducted_from == "credits":
            user.credits -= 1
        else:
            user.addon_credits -= 1
        db.commit()

        try:
            result_img = ImageProcessor.sketch_to_realistic(img, api_token=OPENAI_API_KEY, quality=quality)
        except Exception as e:
            # AI失敗 → クレジット返金
            if deducted_from == "credits":
                user.credits += 1
            else:
                user.addon_credits += 1
            db.commit()
            raise

        b64 = pil_to_base64(result_img)
        return {"status": "success", "image_base64": f"data:image/png;base64,{b64}", "credits_remaining": user.credits}
    except Exception as e:
        base_err = str(e)
        err_msg = traceback.format_exc()
        uid = user.firebase_uid if user else None
        threading.Thread(target=send_error_email_task, args=(base_err, err_msg, uid)).start()
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
    if not _check_rate_limit(f"ai:{user.firebase_uid}", _RATE_LIMIT_AI_MAX):
        return JSONResponse(status_code=429, content={"error": "リクエストが多すぎます。しばらく経ってから再度お試しください。"})
    total = user.credits + (user.addon_credits or 0)
    if total <= 0:
        return JSONResponse(status_code=402, content={"error": "チケット残高が不足しています。"})

    if len(instruction) > 500:
        return JSONResponse(status_code=400, content={"error": "テキスト指示は500文字以内で入力してください。"})

    if quality not in ("high", "medium", "low"):
        quality = "medium"

    try:
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"error": "ファイルサイズが大きすぎます（上限10MB）"})
        img = Image.open(io.BytesIO(contents)).convert("RGBA")

        deducted_from = "credits" if user.credits > 0 else "addon"
        if deducted_from == "credits":
            user.credits -= 1
        else:
            user.addon_credits -= 1
        db.commit()

        try:
            result_img = ImageProcessor.edit_by_instruction(img, instruction, api_token=OPENAI_API_KEY, quality=quality)
        except Exception as e:
            if deducted_from == "credits":
                user.credits += 1
            else:
                user.addon_credits += 1
            db.commit()
            raise

        b64 = pil_to_base64(result_img)
        return {"status": "success", "image_base64": f"data:image/png;base64,{b64}", "credits_remaining": user.credits}
    except Exception as e:
        base_err = str(e)
        err_msg = traceback.format_exc()
        uid = user.firebase_uid if user else None
        threading.Thread(target=send_error_email_task, args=(base_err, err_msg, uid)).start()
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
    if not _check_rate_limit(f"ai:{user.firebase_uid}", _RATE_LIMIT_AI_MAX):
        return JSONResponse(status_code=429, content={"error": "リクエストが多すぎます。しばらく経ってから再度お試しください。"})
    total = user.credits + (user.addon_credits or 0)
    if total <= 0:
        return JSONResponse(status_code=402, content={"error": "チケット残高が不足しています。"})

    if quality not in ("high", "medium", "low"):
        quality = "medium"

    try:
        bg_contents = await bg_file.read()
        bld_contents = await bld_file.read()
        if len(bg_contents) > 10 * 1024 * 1024 or len(bld_contents) > 10 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"error": "ファイルサイズが大きすぎます（上限10MB）"})
        bg_img = Image.open(io.BytesIO(bg_contents)).convert("RGBA")
        bld_img = Image.open(io.BytesIO(bld_contents)).convert("RGBA")

        deducted_from = "credits" if user.credits > 0 else "addon"
        if deducted_from == "credits":
            user.credits -= 1
        else:
            user.addon_credits -= 1
        db.commit()

        try:
            result_img = ImageProcessor.blend_building(
                background=bg_img, building=bld_img,
                center_x=int(cx), center_y=int(cy),
                width=int(width), height=int(height),
                angle=angle, api_token=OPENAI_API_KEY,
                is_sketch=is_sketch, quality=quality
            )
        except Exception as e:
            if deducted_from == "credits":
                user.credits += 1
            else:
                user.addon_credits += 1
            db.commit()
            raise

        b64 = pil_to_base64(result_img)
        return {"status": "success", "image_base64": f"data:image/png;base64,{b64}", "credits_remaining": user.credits}
    except Exception as e:
        base_err = str(e)
        err_msg = traceback.format_exc()
        uid = user.firebase_uid if user else None
        threading.Thread(target=send_error_email_task, args=(base_err, err_msg, uid)).start()
        return JSONResponse(status_code=500, content={"error": "大変申し訳ございません。ただいまご利用できない状況です。しばらく経ってからアクセス願います。"})

@app.post("/api/match-color")
async def match_color_endpoint(
    bg_file: UploadFile = File(...),
    bld_file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    if not user:
        return JSONResponse(status_code=401, content={"error": "ログインが必要です。"})
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
    if not _check_rate_limit(f"payment:{user.firebase_uid}", _RATE_LIMIT_PAYMENT_MAX):
        return JSONResponse(status_code=429, content={"error": "リクエストが多すぎます。しばらく経ってから再度お試しください。"})

    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        return JSONResponse(status_code=400, content={"error": "session_id required"})

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        print(f"Stripe error in verify_payment: {e}")
        return JSONResponse(status_code=400, content={"error": "支払い確認に失敗しました。しばらく経ってから再度お試しください。"})

    # セッション所有者チェック: このセッションがログインユーザーのものか確認
    session_owner = getattr(session, 'client_reference_id', None)
    if session_owner != user.firebase_uid:
        return JSONResponse(status_code=403, content={"error": "このセッションへのアクセス権限がありません。"})

    # 支払い未完了は無視
    if session.payment_status not in ("paid", "no_payment_required"):
        return {"status": "pending"}

    _meta = session.metadata
    credits_to_add = int(getattr(_meta, 'credits_to_add', None) or 0)
    item_name = getattr(_meta, 'item_name', None)

    # 二重付与防止: session_idをグローバルに確認（他ユーザーによる処理済みも含む）
    already_processed = db.query(User).filter(
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
    print(f"verify-payment: user={mask_uid(user.firebase_uid)}, item={item_name}, credits={user.credits}")
    return {"status": "success", "credits": user.credits, "addon_credits": addon}

class CheckoutRequest(BaseModel):
    plan: str = None
    addon: str = None

@app.post("/api/create-checkout-session")
async def create_checkout_session(request: CheckoutRequest, user: User = Depends(get_current_user)):
    if not user:
        return JSONResponse(status_code=401, content={"error": "ログインが必要です。"})
    if not _check_rate_limit(f"payment:{user.firebase_uid}", _RATE_LIMIT_PAYMENT_MAX):
        return JSONResponse(status_code=429, content={"error": "リクエストが多すぎます。しばらく経ってから再度お試しください。"})
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
        print(f"User uid: {mask_uid(user.firebase_uid)}")
        
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
        return JSONResponse(status_code=400, content={"error": "決済セッションの作成に失敗しました。しばらく経ってから再度お試しください。"})


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
        _meta = getattr(session, 'metadata', None)
        credits_to_add = int(getattr(_meta, 'credits_to_add', None) or 0)
        item_name = getattr(_meta, 'item_name', None)

        print(f"Webhook (session.completed) - uid: {mask_uid(firebase_uid)}, item: {item_name}")

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
                    print(f"SUCCESS: User {mask_uid(firebase_uid)} updated - Plan: {user.plan}")
            else:
                print(f"ERROR: User {mask_uid(firebase_uid)} not found in DB")
        else:
            print(f"ERROR: No client_reference_id in session")

    # 2. 2ヶ月目以降の更新支払い成功時
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        sub_id = getattr(invoice, 'subscription', None)
        if not sub_id:
            return {"status": "skipped - no subscription id"}

        # 初回サブスク開始時はcheckout.session.completedで処理済みのためスキップ
        billing_reason = getattr(invoice, 'billing_reason', None)
        if billing_reason == 'subscription_create':
            print(f"Webhook (invoice.payment_succeeded) - skipped initial payment (billing_reason=subscription_create)")
            return {"status": "skipped - initial payment"}

        print(f"Webhook (invoice.payment_succeeded) - sub_id: {sub_id}")

        plan_credits = {"lite": 30, "plus": 70, "max": 200}

        # サブスクリプション詳細を取得してユーザーを特定
        try:
            subscription = stripe.Subscription.retrieve(sub_id)
            _sub_meta = getattr(subscription, 'metadata', None)
            firebase_uid = getattr(_sub_meta, 'firebase_uid', None)

            if firebase_uid:
                user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
                if user:
                    # DBのplanからクレジット数を決定（メタデータに依存しない）
                    credits_to_add = plan_credits.get(user.plan, 0)
                    if credits_to_add > 0:
                        user.credits = credits_to_add
                        db.commit()
                        print(f"SUCCESS: Reset credits for user {mask_uid(firebase_uid)} (plan={user.plan}, monthly renewal)")
                else:
                    print(f"ERROR: User {mask_uid(firebase_uid)} not found for subscription")
            else:
                print(f"ERROR: No firebase_uid in subscription metadata for {sub_id}")
        except Exception as e:
            print(f"ERROR: Failed to process recurring payment: {e}")
            return JSONResponse(status_code=500, content={"error": "internal error"})

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

        print(f"change-plan: user={mask_uid(user.firebase_uid)}, plan={new_plan}")
        return {"status": "success", "plan": new_plan, "credits": config["credits"]}
    except Exception as e:
        print(f"change-plan error: {e}")
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/user/downgrade")
async def downgrade_user(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
    FREE_PLAN_LIMIT = 10
    user.plan = 'free'
    user.credits = min(user.credits or 0, FREE_PLAN_LIMIT)
    
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

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
