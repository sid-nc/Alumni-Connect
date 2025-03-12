from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'secret_key'  # Replace with a secure key in production

DATABASE = 'alumni.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Home Page
@app.route('/')
def home():
    return render_template('home.html')

#Sign up page
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Existing fields
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        batch_year = request.form['batch_year']
        current_job = request.form['current_job']
        company = request.form['company']
        password = generate_password_hash(request.form['password'])

        # Default role is 'user' for all new signups
        role = 'user'
        
        conn = get_db_connection()

        try:
            conn.execute(
                "INSERT INTO users (name, email, phone, batch_year, current_job, company, password, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, email, phone, batch_year, current_job, company, password, role)
            )
            conn.commit()
            return redirect(url_for('login'))

        except sqlite3.IntegrityError as e:
            # Error handling as before
            if "Email already registered" in str(e) or "UNIQUE constraint failed: users.email" in str(e):
                flash("Email already registered", "error")
            else:
                flash("An error occurred. Please try again.", "error")
        finally:
            conn.close()
        
    return render_template('signup.html')




# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_role'] = user['role']  # Store user role in session
            return redirect(url_for('home'))
        else:
            flash("Invalid credentials")
    
    return render_template('login.html')


# Alumni Directory
@app.route('/alumni_directory', methods=['GET', 'POST'])
def alumni_directory():
    results = None
    if request.method == 'POST':
        search_name = request.form['search']
        conn = get_db_connection()
        results = conn.execute("SELECT * FROM users WHERE name LIKE ?", ('%' + search_name + '%',)).fetchall()
        conn.close()
    return render_template('alumni_directory.html', results=results)

# Events Page
@app.route('/events')
def events():
    conn = get_db_connection()
    events = conn.execute("SELECT * FROM events").fetchall()
    conn.close()
    return render_template('events.html', events=events)

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# Route to start a conversation
@app.route('/conversation/<int:user_id>', methods=['POST', 'GET'])
def start_conversation(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    recipient = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    messages = conn.execute(
        "SELECT * FROM messages WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?) ORDER BY timestamp",
        (session['user_id'], user_id, user_id, session['user_id'])
    ).fetchall()
    conn.close()
    
    return render_template('conversation.html', recipient_name=recipient['name'], recipient_id=user_id, messages=messages)

# Route to send a message
@app.route('/send_message/<int:receiver_id>', methods=['POST'])
def send_message(receiver_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    content = request.form['content']
    sender_id = session['user_id']
    
    conn = get_db_connection()
    conn.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
                 (sender_id, receiver_id, content))
    conn.commit()
    conn.close()
    
    return redirect(url_for('start_conversation', user_id=receiver_id))

def initialize_database():
    conn = get_db_connection()
    
    # Create the `users` table if it doesn't exist
    conn.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        batch_year INTEGER,
        current_job TEXT,
        company TEXT,
        password TEXT NOT NULL
    )
    ''')

    # Create the `prevent_duplicate_email` trigger if it doesn't exist
    conn.execute('''
    CREATE TRIGGER IF NOT EXISTS prevent_duplicate_email
    BEFORE INSERT ON users
    FOR EACH ROW
    BEGIN
        SELECT
        CASE
            WHEN (SELECT COUNT(*) FROM users WHERE email = NEW.email) > 0
            THEN RAISE(ABORT, 'Email already registered')
        END;
    END;
    ''')

    conn.commit()
    conn.close()

# Route to delete a message
@app.route('/delete_message/<int:message_id>', methods=['POST'])
def delete_message(message_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    try:
        # Delete the message with the given message_id
        conn.execute("DELETE FROM messages WHERE id = ? AND (sender_id = ? OR receiver_id = ?)", 
                     (message_id, session['user_id'], session['user_id']))
        conn.commit()
        flash("Message deleted successfully.", "success")
    except sqlite3.Error as e:
        flash(f"An error occurred: {e}", "error")
    finally:
        conn.close()
    
    return redirect(url_for('start_conversation', user_id=session['user_id']))

@app.route('/users_with_same_job/<int:user_id>', methods=['GET'])
def users_with_same_job(user_id):
    conn = get_db_connection()
    query = '''
        SELECT name, email, current_job
        FROM users
        WHERE current_job IN (
            SELECT current_job 
            FROM users 
            WHERE id = ?
        ) AND id != ? AND id IN (
            SELECT DISTINCT sender_id
            FROM messages
            WHERE receiver_id = ?
            UNION
            SELECT DISTINCT receiver_id
            FROM messages
            WHERE sender_id = ?
        );
    '''
    users = conn.execute(query, (user_id, user_id, user_id, user_id)).fetchall()
    conn.close()
    
    return render_template('users_with_same_job.html', users=users)

@app.route('/messages_with_users', methods=['GET'])
def messages_with_users():
    conn = get_db_connection()
    query = '''
        SELECT m.content, m.timestamp, u1.name AS sender_name, u2.name AS receiver_name
        FROM messages m
        JOIN users u1 ON m.sender_id = u1.id
        JOIN users u2 ON m.receiver_id = u2.id
        ORDER BY m.timestamp DESC;
    '''
    messages = conn.execute(query).fetchall()
    conn.close()
    
    return render_template('messages_with_users.html', messages=messages)

@app.route('/message_count', methods=['GET'])
def message_count():
    # Ensure user is logged in and has the 'admin' role
    if 'user_id' not in session or session.get('user_role') != 'admin':
        flash("You do not have permission to access this page.", "error")
        return redirect(url_for('home'))
    
    conn = get_db_connection()
    query = '''
        SELECT u.name, COUNT(m.id) AS message_count
        FROM users u
        LEFT JOIN messages m ON u.id = m.sender_id
        GROUP BY u.id
        ORDER BY message_count DESC;
    '''
    message_counts = conn.execute(query).fetchall()
    conn.close()
    
    return render_template('message_count.html', message_counts=message_counts)



if __name__ == '__main__':
    initialize_database()
    app.run(debug=True)
