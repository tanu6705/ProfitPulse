import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "tanvi_sales_project_secret_2026"
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or "tanvi_jwt_secret_2026"
    
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "database.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_COOKIE_SECURE = False 
    JWT_COOKIE_CSRF_PROTECT = False
    
    # --- STORAGE FOR MILESTONE 4 ---
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'reports')
    # Ensure folder exists
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    
    # --- EMAIL SERVICE CONFIG (Required for Milestone 4) ---
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')