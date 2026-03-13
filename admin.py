from app import app, db, User

with app.app_context():
    # Find your account by username
    user = User.query.filter_by(username='tanvi').first() # Replace with your username
    if user:
        user.role = 'admin'
        db.session.commit()
        print(f"User {user.username} is now an Admin!")
    else:
        print("User not found.")