import os
import io
import csv
import numpy as np
import pandas as pd
from flask import send_file
from datetime import datetime, timedelta
from flask import Flask,jsonify, render_template, request, redirect, url_for, flash, Response, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_bcrypt import Bcrypt
from sqlalchemy import func, case, literal_column
from sklearn.linear_model import LinearRegression
from sqlalchemy import union_all
from flask_jwt_extended import get_jwt, get_jwt_identity
from flask import render_template_string

from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, unset_jwt_cookies, set_access_cookies
)

# Ensure models.py contains User, Transaction, Sale, Product, Business, Report
from models import db, User, Transaction, Sale, Product, Business, Report 
from config import Config

app = Flask(__name__)
app.config.from_object(Config)


app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# Create database tables
with app.app_context():
    db.create_all()

    # This automatically upgrades 'tanvi' to admin status
    admin_user = User.query.filter_by(username='tanvi').first()
    if admin_user:
        if admin_user.role != 'admin':
            admin_user.role = 'admin'
            db.session.commit()
            print("✅ Account 'tanvi' elevated to Admin!")
        else:
            print("ℹ️ Account 'tanvi' is already an Admin.")
    else:
        print("❌ 'tanvi' not found in database. Please register first.")



# ---------------- UTILS & MULTI-BUSINESS HELPER ----------------
def get_active_biz_id():
    """Helper to manage which business profile is currently active in the session."""
    biz_id = session.get('active_business_id')
    if not biz_id:
        user_id = get_jwt_identity()
        first_biz = Business.query.filter_by(user_id=user_id).first()
        if first_biz:
            session['active_business_id'] = first_biz.id
            return first_biz.id
    return biz_id

@app.route('/')
def index():
    # If the user is logged in, redirect them to the dashboard automatically
    # (Update this check based on how you store your user session)
    if 'user_id' in session: 
        return redirect(url_for('dashboard'))
        
    return render_template('landing.html')

# ---------------- REGISTER ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        # NEW: Capture business name from the updated register.html
        biz_name = request.form.get('business_name', f"{username}'s Shop")

        if User.query.filter_by(email=email).first() or User.query.filter_by(username=username).first():
            flash("User already exists.", "danger")
            return redirect(url_for('register'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        # Ensure 'role' is handled if your model requires it
        new_user = User(username=username, email=email, password=hashed_password, role='user') 
        db.session.add(new_user)
        db.session.commit()

        # Create the business profile linked to the new user
        new_biz = Business(name=biz_name, user_id=new_user.id)
        db.session.add(new_biz)
        db.session.commit()

        flash("Registration Successful! Please login.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and bcrypt.check_password_hash(user.password, request.form['password']):

            # --- MANDATORY: TRACK LOGIN ---
            user.last_login = datetime.utcnow()
            db.session.commit()

            access_token = create_access_token(identity=str(user.id),
                                               additional_claims={"role": user.role})
            response = redirect(url_for('dashboard'))
            set_access_cookies(response, access_token)
            
            # Set initial business in session
            first_biz = Business.query.filter_by(user_id=user.id).first()
            if first_biz:
                session['active_business_id'] = first_biz.id
                
            flash("Login Successful!", "success")
            return response
        flash("Invalid Credentials.", "danger")
    return render_template('login.html')

#-------------Admin Route to Promote User to Admin (Run Once)-------------
# ------------- Updated Admin Route with Global Stats -------------
@app.route('/admin/users')
@jwt_required()
def admin_users():
    user_id = get_jwt_identity()
    current_user = User.query.get(user_id)

    if current_user.role != 'admin':
        flash("Access Denied!", "danger")
        return redirect(url_for('dashboard'))
    
    # --- MANDATORY: RE-CHALLENGE PASSWORD ---
    # We check a small session flag. If it's not there, they must verify.
    if not session.get('admin_panel_unlocked'):
        return render_template('admin_verify.html')

    all_users = User.query.all()
    
    # NEW: Calculate Global Platform Metrics
    global_stats = {
        'total_users': User.query.count(),
        'total_businesses': Business.query.count(),
        'total_transactions': Transaction.query.count(),
        # Sum of all income across the entire platform
        'platform_revenue': db.session.query(func.sum(Transaction.amount)).filter(Transaction.type == 'income').scalar() or 0,
        'platform_sales': db.session.query(func.sum(Sale.total_amount)).scalar() or 0
    }
    
    return render_template('admin_users.html', users=all_users, stats=global_stats)

# The handler for that verification page
@app.route('/admin/verify_gate', methods=['POST'])
@jwt_required()
def admin_verify_gate():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    password = request.form.get('password')

    if user and bcrypt.check_password_hash(user.password, password):
        session['admin_panel_unlocked'] = True # Unlock for this session
        return redirect(url_for('admin_users'))
    
    flash("Incorrect Admin Password!", "danger")
    return redirect(url_for('dashboard'))


# ------------- DELETE USER (Admin Only) -------------
@app.route('/admin/delete_user/<int:user_id>')
@jwt_required()
def delete_user(user_id):
    admin_id = int(get_jwt_identity())
    claims = get_jwt()
    
    # 1. Security Check: Is the requester an admin?
    if claims.get('role') != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('dashboard'))

    # 2. Prevent self-deletion
    if admin_id == user_id:
        flash("You cannot delete your own admin account!", "error")
        return redirect(url_for('admin_users'))

    user_to_delete = User.query.get_or_404(user_id)
    
    try:
        # This will delete the user and all linked data if you set up cascades in models.py
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"User '{user_to_delete.username}' and all associated data deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error: Could not delete user. Check database constraints.", "danger")
        print(f"Delete Error: {e}")

    return redirect(url_for('admin_users'))


# ------------- DELETE BUSINESS (Admin Only) -------------
@app.route('/admin/delete_business/<int:biz_id>')
@jwt_required()
def delete_biz(biz_id):
    claims = get_jwt()
    if claims.get('role') != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('dashboard'))

    biz = Business.query.get_or_404(biz_id)
    
    try:
        db.session.delete(biz)
        db.session.commit()
        flash(f"Business '{biz.name}' deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error deleting business.", "danger")
        print(f"Delete Error: {e}")

    return redirect(url_for('admin_users'))

@app.context_processor
def inject_user_role():
    # If you are using JWT or Session, fetch the role here
    # Example using a common session pattern
    
    role = None
    try:
        # This assumes you stored 'role' in your JWT identity or claims
        # Adjust based on how you log users in
        claims = get_jwt()
        role = claims.get('role') 
    except Exception:
        role = None
        
    return dict(user_role=role)

# ---------------- DASHBOARD ----------------
from sqlalchemy import func, case

@app.route('/dashboard')
@jwt_required()
def dashboard():
    user_id = int(get_jwt_identity())
    biz_id = get_active_biz_id()
    
    user_businesses = Business.query.filter_by(user_id=user_id).all()
    active_biz = Business.query.get(biz_id)

    # Fetch records
    transactions = Transaction.query.filter_by(business_id=biz_id).order_by(Transaction.date.desc()).all()
    sales_records = Sale.query.filter_by(business_id=biz_id).order_by(Sale.date.desc()).all()
    low_stock = Product.query.filter_by(business_id=biz_id).filter(Product.stock <= 5).all()

    # Totals
    total_income = sum(t.amount for t in transactions if t.type == "income")
    total_expense = sum(t.amount for t in transactions if t.type == "expense")
    total_sales = sum(s.total_amount for s in sales_records)
    total_cogs = sum(s.cogs for s in sales_records)
    profit = (total_sales - total_cogs) + total_income - total_expense

    # --- CHART DATA PREPARATION (Python-Grouped Version) ---
    merged_data = {}

    # 1. Process Sales Records
    for s in sales_records:
        if s.date:
            m = s.date.strftime("%b %Y")  # e.g., "Mar 2026"
            if m not in merged_data:
                merged_data[m] = {'inc': 0.0, 'exp': 0.0}
            merged_data[m]['inc'] += float(s.total_amount or 0)

    # 2. Process Transactions (Income & Expenses)
    for t in transactions:
        if t.date:
            m = t.date.strftime("%b %Y")
            if m not in merged_data:
                merged_data[m] = {'inc': 0.0, 'exp': 0.0}
            
            if t.type == "income":
                merged_data[m]['inc'] += float(t.amount or 0)
            else:
                merged_data[m]['exp'] += float(t.amount or 0)

    # 3. Sort Chronologically
    try:
        sorted_keys = sorted(merged_data.keys(), key=lambda x: datetime.strptime(x, "%b %Y"))
    except Exception:
        sorted_keys = sorted(merged_data.keys()) # Fallback sort

    chart_labels = sorted_keys
    chart_income = [merged_data[m]['inc'] for m in sorted_keys]
    chart_expense = [merged_data[m]['exp'] for m in sorted_keys]
    chart_profit = [merged_data[m]['inc'] - merged_data[m]['exp'] for m in sorted_keys]

    return render_template('dashboard.html', 
                           income=total_income, expense=total_expense, 
                           sales=total_sales, profit=profit, 
                           transactions=transactions, sales_records=sales_records, 
                           low_stock_items=low_stock, user_businesses=user_businesses,
                           active_biz=active_biz, chart_labels=chart_labels,
                           chart_income=chart_income, chart_expense=chart_expense,
                           chart_profit=chart_profit)

@app.route('/delete_sale/<int:id>')
@jwt_required()
def delete_sale(id):
    biz_id = get_active_biz_id()
    sale = Sale.query.filter_by(id=id, business_id=biz_id).first_or_404()
    db.session.delete(sale)
    db.session.commit()
    flash("Sale record deleted.", "success")
    return redirect(url_for('dashboard'))

@app.route('/delete_transaction/<int:id>')
@jwt_required()
def delete_transaction(id):
    biz_id = get_active_biz_id()
    tx = Transaction.query.filter_by(id=id, business_id=biz_id).first_or_404()
    db.session.delete(tx)
    db.session.commit()
    flash("Transaction record deleted.", "success")
    return redirect(url_for('dashboard'))

#-------------ADD BUSINESS (New Route)----------------
@app.route('/add_business', methods=['GET', 'POST'])
@jwt_required()
def add_business():
    user_id = int(get_jwt_identity())
    if request.method == 'POST':
        biz_name = request.form.get('name')
        if not biz_name:
            flash("Business name is required!", "danger")
            return redirect(url_for('add_business'))
            
        new_biz = Business(name=biz_name, user_id=user_id)
        db.session.add(new_biz)
        db.session.commit()
        
        # Automatically switch to the new business
        session['active_business_id'] = new_biz.id
        flash(f"Business '{biz_name}' created and set as active!", "success")
        return redirect(url_for('dashboard'))
        
    return render_template('add_business.html')


#--------------SWITCH BUSINESS (New Route)----------------
@app.route('/switch_business/<int:biz_id>')
@jwt_required()
def switch_business(biz_id):
    user_id = int(get_jwt_identity())
    # Security: Ensure user owns the business
    biz = Business.query.filter_by(id=biz_id, user_id=user_id).first()
    if biz:
        session['active_business_id'] = biz.id
        flash(f"Switched to {biz.name}", "success")
    else:
        flash("Unauthorized access!", "danger")
    return redirect(url_for('dashboard'))

# ---------------- INVENTORY ----------------
@app.route('/inventory', methods=['GET', 'POST'])
@jwt_required()
def inventory():
    user_id = int(get_jwt_identity())
    biz_id = get_active_biz_id()
    
    # Fetch active business and user for UI context
    active_biz = Business.query.get(biz_id)
    current_user = User.query.get(user_id)

    if request.method == 'POST':
        # Check if we are updating an existing product or adding a new one
        product_id = request.form.get('product_id')
        
        if product_id:
            # UPDATE EXISTING PRODUCT
            product = Product.query.filter_by(id=product_id, business_id=biz_id).first_or_404()
            product.name = request.form['name']
            product.cost_price = float(request.form['cost_price'])
            product.sale_price = float(request.form['sale_price'])
            product.stock = int(request.form['stock'])
            flash(f"Updated {product.name} successfully!", "success")
        else:
            # ADD NEW PRODUCT
            new_product = Product(
                name=request.form['name'],
                cost_price=float(request.form['cost_price']),
                sale_price=float(request.form['sale_price']),
                stock=int(request.form['stock']),
                business_id=biz_id
            )
            db.session.add(new_product)
            flash("Product added to inventory!", "success")
        
        db.session.commit()
        return redirect(url_for('inventory'))

    # Fetch all products for this specific business
    products = Product.query.filter_by(business_id=biz_id).all()
    
    return render_template('inventory.html', 
                           products=products, 
                           active_biz=active_biz,
                           user_role=current_user.role)

# Add this route to handle deletions
@app.route('/delete_product/<int:id>')
@jwt_required()
def delete_product(id):
    biz_id = get_active_biz_id()
    product = Product.query.filter_by(id=id, business_id=biz_id).first_or_404()
    
    db.session.delete(product)
    db.session.commit()
    flash("Product removed from inventory.", "success")
    return redirect(url_for('inventory'))


# ---------------- LOG TRANSACTION (Fixes BuildError) ----------------
@app.route('/log', methods=['GET', 'POST']) # This name must match url_for('log')
@jwt_required()
def log_transaction():
    user_id = int(get_jwt_identity())
    biz_id = get_active_biz_id()

    if request.method == 'POST':
        title = request.form.get('title')
        t_type = request.form.get('type') # 'income' or 'expense'
        amount = float(request.form.get('amount'))
        date_str = request.form.get('date')
        
        new_tx = Transaction(
            title=title, 
            type=t_type, 
            amount=amount, 
            date=datetime.strptime(date_str, "%Y-%m-%d"), 
            business_id=biz_id
        )
        db.session.add(new_tx)
        db.session.commit()
        flash("Transaction added!", "success")
        return redirect(url_for('log_transaction'))

    return render_template('log.html')

# ---------------- SALES ----------------
@app.route('/sales', methods=['GET', 'POST'])
@jwt_required()
def sales():
    user_id = int(get_jwt_identity())
    biz_id = get_active_biz_id()
    products = Product.query.filter_by(business_id=biz_id).all()

    if request.method == 'POST':
        product = Product.query.get(request.form.get('product_id'))
        qty = int(request.form['quantity'])
        if product and product.stock >= qty:
            new_sale = Sale(
                product_id=product.id, product_name=product.name,
                quantity=qty, price_per_unit=product.sale_price,
                total_amount=qty * product.sale_price,
                cogs=qty * product.cost_price,
                date=datetime.strptime(request.form['date'], "%Y-%m-%d"),
                business_id=biz_id
                
            )
            product.stock -= qty
            db.session.add(new_sale)
            db.session.commit()
            flash("Sale Recorded!", "success")
            return redirect(url_for('dashboard'))
        flash("Stock Error!", "danger")
    return render_template('sales.html', products=products)

# ---------------- ANALYTICS (AI INTEGRATED) ----------------
@app.route('/analytics')
@jwt_required()
def analytics():
    biz_id = get_active_biz_id()
    # CRITICAL: Fetch the business object so the template can show the name
    active_biz = Business.query.get(biz_id)
    
    # 1. Fetch Sales and COGS grouped by month
    raw_data = db.session.query(
        func.strftime("%Y-%m", Sale.date).label('month'), 
        func.sum(Sale.total_amount),
        func.sum(Sale.cogs)
    ).filter_by(business_id=biz_id).group_by('month').order_by('month').all()

    # Format: [Month, Income, Cost, Profit]
    monthly_chart = []
    for r in raw_data:
        # Converting "2026-03" to "Mar 2026" for a better look on charts
        month_label = datetime.strptime(r[0], "%Y-%m").strftime("%b %Y")
        monthly_chart.append([month_label, float(r[1]), float(r[2]), float(r[1] - r[2])])

    # Initialize defaults for AI logic
    growth_percent = 0
    profit_margin = 0
    next_month_val = 0
    forecast_data = []

    # 2. AI LINEAR REGRESSION LOGIC
    if len(monthly_chart) >= 2:
        X = np.array(range(len(monthly_chart))).reshape(-1, 1)
        y = np.array([row[3] for row in monthly_chart]) 

        model = LinearRegression()
        model.fit(X, y)
        
        next_idx = np.array([[len(monthly_chart)]])
        next_month_val = max(0, model.predict(next_idx)[0])

        for i in range(1, 7):
            future_idx = np.array([[len(monthly_chart) + i - 1]])
            pred = model.predict(future_idx)[0]
            future_date = (datetime.now() + timedelta(days=30*i)).strftime("%b %Y")
            forecast_data.append([future_date, round(max(0, pred), 2)])

        curr_profit = monthly_chart[-1][3]
        prev_profit = monthly_chart[-2][3]
        if prev_profit != 0:
            growth_percent = round(((curr_profit - prev_profit) / abs(prev_profit)) * 100, 2)
    
    if len(monthly_chart) >= 1:
        latest = monthly_chart[-1]
        if latest[1] > 0:
            profit_margin = round((latest[3] / latest[1]) * 100, 2)

    # Pass everything to the template
    return render_template("analytics.html", 
                           active_biz=active_biz, # Added this
                           monthly_chart=monthly_chart,
                           forecast_data=forecast_data, 
                           growth_percent=growth_percent, 
                           profit_margin=profit_margin, 
                           next_month_val=next_month_val)

# ---------------- UPLOAD CSV (New Route) ----------------
@app.route('/upload_csv', methods=['POST'])
@jwt_required()
def upload_csv():
    user_id = int(get_jwt_identity())
    biz_id = get_active_biz_id()
    file = request.files.get('file')
    
    if file and file.filename.endswith('.csv'):
        # Decode and read the stream
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        count = 0
        for row in csv_reader:
            try:
                # Use .strip() to remove accidental spaces from headers/values
                title = row.get('Title', '').strip()
                trans_type = row.get('Type', '').strip().lower()
                amount = float(row.get('Amount', 0))
                date_str = row.get('Date', '').strip()

                # Skip empty rows
                if not title or not date_str:
                    continue

                tx = Transaction(
                    title=title, 
                    type=trans_type, 
                    amount=amount, 
                    # Convert to date object
                    date=datetime.strptime(date_str, "%Y-%m-%d").date(),
                    # Remove user_id if it's not in your Transaction model (check models.py)
                    business_id=biz_id
                )
                db.session.add(tx)
                count += 1
            except Exception as e:
                # THIS IS KEY: Print the error to your terminal to debug
                print(f"Skipping row due to error: {e} | Row data: {row}")
                continue
        
        db.session.commit()
        flash(f"Successfully uploaded {count} transactions!", "success")
    
    return redirect(url_for('dashboard')) # Redirect to dashboard to see the chart update

# ---------------- REPORTING & EXPORT ----------------
from sqlalchemy import extract

@app.route('/export/<string:format>')
@jwt_required()
def export_data(format):
    biz_id = get_active_biz_id()
    active_biz = Business.query.get(biz_id)
    
    # NEW: Get the selected month from the URL parameters
    selected_month = request.args.get('month', 'all')
    
    # 1. Base Queries
    sales_query = Sale.query.filter_by(business_id=biz_id)
    trans_query = Transaction.query.filter_by(business_id=biz_id)

    # 2. Apply Month Filter (if a specific month is selected)
    if selected_month != 'all':
        # extract('month', ...) gets the month integer from the date column
        sales_query = sales_query.filter(extract('month', Sale.date) == int(selected_month))
        trans_query = trans_query.filter(extract('month', Transaction.date) == int(selected_month))

    sales = sales_query.all()
    transactions = trans_query.all()
    
    # 3. Calculate Financial Summaries (Filtered Data only)
    # Summing up sales and income transactions
    total_sales_revenue = sum(s.total_amount for s in sales)
    total_other_income = sum(t.amount for t in transactions if t.type == "income")
    
    total_income = total_sales_revenue + total_other_income
    total_expense = sum(t.amount for t in transactions if t.type == "expense")
    total_cogs = sum(s.cogs for s in sales)
    net_profit = total_income - total_expense - total_cogs

    # 4. Handle Excel/CSV
    if format in ['csv', 'excel']:
        report_data = []
        for s in sales:
            report_data.append({'Date': s.date, 'Type': 'Sale', 'Title': s.product_name, 'Amount': s.total_amount, 'COGS': s.cogs})
        for t in transactions:
            report_data.append({'Date': t.date, 'Type': t.type.capitalize(), 'Title': t.title, 'Amount': t.amount, 'COGS': 0})
        
        df = pd.DataFrame(report_data)
        
        if format == 'csv':
            output = io.StringIO()
            df.to_csv(output, index=False)
            return Response(output.getvalue(), mimetype="text/csv", 
                            headers={"Content-disposition": f"attachment; filename={active_biz.name}_Report.csv"})
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=f"{active_biz.name}_Report.xlsx")

    # 5. Handle PDF (Passes filtered data to the template)
    elif format == 'pdf':
        return render_template("pdf_report.html", 
                               biz=active_biz, 
                               sales=sales, 
                               transactions=transactions,
                               summary={
                                   'income': total_income,
                                   'expense': total_expense,
                                   'cogs': total_cogs,
                                   'profit': net_profit
                               },
                               # Pass selected_month to show on the report header
                               report_month=selected_month,
                               date=datetime.now().strftime("%Y-%m-%d"))
    
# ------------- PROFILE ROUTE -------------
@app.route('/profile')
@jwt_required()
def profile():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    user_businesses = Business.query.filter_by(user_id=user_id).all()
    return render_template('profile.html', user=user, user_businesses=user_businesses)


# ------------- CHANGE PASSWORD -------------
@app.route('/change_password', methods=['POST'])
@jwt_required()
def change_password():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    current_pw = request.form.get('current_password')
    new_pw = request.form.get('new_password')
    
    # 1. Verify the current password first
    if not bcrypt.check_password_hash(user.password, current_pw):
        flash("Current password incorrect!", "danger")
        return redirect(url_for('profile'))
    
    # 2. If correct, update to the new password
    if new_pw:
        user.password = bcrypt.generate_password_hash(new_pw).decode('utf-8')
        db.session.commit()
        flash("Security credentials updated successfully!", "success")
    
    return redirect(url_for('profile'))

# ------------- UPDATE BUSINESS NAME -------------
@app.route('/update_business_name/<int:biz_id>', methods=['POST'])
@jwt_required()
def update_business_name(biz_id):
    user_id = int(get_jwt_identity())
    # Security: Ensure current user owns this business
    biz = Business.query.filter_by(id=biz_id, user_id=user_id).first_or_404()
    
    new_name = request.form.get('new_name')
    if new_name:
        biz.name = new_name
        db.session.commit()
        flash(f"Business renamed to {new_name}", "success")
    return redirect(url_for('profile'))


#---------------Admin Verfiy---------------
@app.route('/api/admin/verify', methods=['POST'])
@jwt_required()
def admin_verify():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    data = request.get_json()
    if check_password_hash(user.password, data.get('password')):
        # Create a short-lived token (e.g., 15 mins) specifically for Admin actions
        admin_token = create_access_token(
            identity=current_user_id, 
            additional_claims={"admin_access": True},
            expires_delta=timedelta(minutes=15)
        )
        return jsonify({"admin_token": admin_token}), 200
    return jsonify({"msg": "Invalid Admin Password"}), 401

#---------------Setup admin access-------------
@app.route('/setup_admin_access')
def setup_admin_access():
    # This specifically targets your live usernames
    users_to_elevate = ['tanvi', 'tanvi_kadve']
    updated = []
    
    for username in users_to_elevate:
        user = User.query.filter_by(username=username).first()
        if user:
            user.role = 'admin'
            updated.append(username)
    
    if updated:
        db.session.commit()
        return f"Success! Elevated: {', '.join(updated)}. Now log out and log back in."
    return "No users found. Did you register those usernames on the LIVE site yet?"

# ------------- ADMIN: CHANGE ANY USER PASSWORD -------------
@app.route('/admin/force_password/<int:user_id>', methods=['POST'])
@jwt_required()
def admin_force_password(user_id):
    claims = get_jwt()
    if claims.get('role') != 'admin':
        return jsonify({"msg": "Unauthorized"}), 403

    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password')
    
    if new_password:
        # Use bcrypt to match your registration style
        user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
        db.session.commit()
        flash(f"Password for {user.username} has been reset by Admin.", "success")
    
    return redirect(url_for('admin_users'))

@app.route('/admin/export_system_logs')
@jwt_required()
def export_system_logs():
    claims = get_jwt()
    if claims.get('role') != 'admin':
        return "Unauthorized", 403

    # Fetch all users
    users = User.query.all()
    
    # Prepare data for the CSV
    log_data = []
    for user in users:
        log_data.append({
            "Username": user.username,
            "Email": user.email,
            "Role": user.role,
            "Account Created": user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else "N/A",
            "Last Login": user.last_login.strftime('%Y-%m-%d %H:%M') if user.last_login else "Never",
            "Last Logout": user.last_logout.strftime('%Y-%m-%d %H:%M') if user.last_logout else "Never",
            "Businesses Managed": len(user.businesses)
        })

    # Create DataFrame and convert to CSV
    df = pd.DataFrame(log_data)
    
    output = io.StringIO()
    df.to_csv(output, index=False)
    
    # Return as a downloadable file
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=ProfitPulse_System_Audit_Log.csv"}
    )

# ---------------- LOGOUT ----------------
@app.route('/logout')
@jwt_required()
def logout():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    # --- MANDATORY: TRACK LOGOUT ---
    if user:
        user.last_logout = datetime.utcnow()
        db.session.commit()

    response = redirect(url_for('login'))
    unset_jwt_cookies(response)
    session.clear()
    flash("Logged out.", "success")
    return response

@app.route('/')
def home():
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)