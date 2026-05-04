from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
import datetime
import os
from dotenv import load_dotenv

# 設定の読み込み
load_dotenv()

# 環境変数からデータベースURLを取得
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./saas_database.db")
print(f"--- Database Connecting to: {SQLALCHEMY_DATABASE_URL.split('@')[-1] if '@' in SQLALCHEMY_DATABASE_URL else SQLALCHEMY_DATABASE_URL} ---")

# RenderのPostgreSQL URL対応
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if "sqlite" in SQLALCHEMY_DATABASE_URL:
    connect_args = {"check_same_thread": False}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args=connect_args, pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String, unique=True, index=True)
    plan = Column(String, default="free")  # free, standard
    credits = Column(Integer, default=5)       # サブスク付与分（毎月リセット）
    addon_credits = Column(Integer, default=0)         # 追加購入分（繰り越し）
    stripe_subscription_id = Column(String, nullable=True) # 解約制御用に保持
    last_session_id = Column(String, nullable=True)    # 二重付与防止用
    terms_agreed = Column(Boolean, default=False, nullable=False, server_default="0")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    images = relationship("GeneratedImage", back_populates="owner")

class GeneratedImage(Base):
    __tablename__ = "generated_images"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    file_path = Column(String)  # 例: /static/uploads/ab12cd.png
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    owner = relationship("User", back_populates="images")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
