from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    # Role: 'owner', 'accountant', 'staff' (Requirement for Milestone 4)
    role = db.Column(db.String(20), default='owner', nullable=False) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    businesses = db.relationship('Business', backref='owner',cascade="all, delete-orphan", lazy=True)

    last_login = db.Column(db.DateTime)
    last_logout = db.Column(db.DateTime)
    

class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    products = db.relationship('Product', backref='business', lazy=True)
    transactions = db.relationship('Transaction', backref='business', lazy=True)
    sales = db.relationship('Sale', backref='business', lazy=True)
    reports = db.relationship('Report', backref='business', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    cost_price = db.Column(db.Float, nullable=False)
    sale_price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20), nullable=False) # income / expense
    category = db.Column(db.String(100))
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    product_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_per_unit = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    cogs = db.Column(db.Float) 
    date = db.Column(db.Date, default=datetime.utcnow)

# Added Report Model for Milestone 4 (Smart Reporting)
class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    report_type = db.Column(db.String(50)) # 'Monthly', 'Annual', 'Inventory'
    file_path = db.Column(db.String(500))  # URL or path to PDF/Excel
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)