from flask import Flask, render_template, redirect, url_for, request, session, flash, make_response
from models import init_db, get_user_by_email, add_user, verify_password, is_admin, connect_db
from werkzeug.security import generate_password_hash, check_password_hash
from xhtml2pdf import pisa
import io, os

app = Flask(__name__)
app.secret_key = 'supersecretkey'

if not os.path.exists('database.db'):
    init_db()

@app.route('/')
def home():
    if 'user_id' in session or session.get('admin'):
        if session.get('role') == 'creator':
            return redirect(url_for('creator_dashboard'))
        elif session.get('role') == 'reviewer':
            return redirect(url_for('reviewer_dashboard'))
        elif session.get('admin'):
            return redirect(url_for('admin_dashboard'))

    total_documents = 142
    shared_documents = 28
    pending_review = 15
    total_templates = 8
    recent_activities = [
        {'document_name': 'Project Proposal.docx', 'timestamp': 'Edited 2 hours ago'},
        {'document_name': 'Budget Report.pdf', 'timestamp': 'Approved 4 hours ago'},
        {'document_name': 'Meeting Notes.docx', 'timestamp': 'Needs review'},
    ]

    return render_template(
        'home.html',
        total_documents=total_documents,
        shared_documents=shared_documents,
        pending_review=pending_review,
        total_templates=total_templates,
        recent_activities=recent_activities
    )

@app.route('/login', methods=['GET', 'POST'])
def login():

    if 'user_id' in session or session.get('admin'):
        if session.get('role') == 'creator':
            return redirect(url_for('creator_dashboard'))
        elif session.get('role') == 'reviewer':
            return redirect(url_for('reviewer_dashboard'))
        elif session.get('admin'):
            return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if is_admin(email, password):
            session.clear()
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))

        conn = connect_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['user_name'] = user['name']
            if user['role'] == 'creator':
                return redirect(url_for('creator_dashboard'))
            elif user['role'] == 'reviewer':
                return redirect(url_for('reviewer_dashboard'))

        flash('Invalid credentials', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session or session.get('admin'):
        if session.get('role') == 'creator':
            return redirect(url_for('creator_dashboard'))
        elif session.get('role') == 'reviewer':
            return redirect(url_for('reviewer_dashboard'))
        elif session.get('admin'):
            return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        full_name = request.form['fullName']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirmPassword']
        terms = request.form.get('terms')

        if not full_name or not email or not password or not confirm_password or not terms:
            error_message = "All fields are required."
            return render_template('register.html', error_message=error_message)

        if password != confirm_password:
            error_message = "Passwords do not match."
            return render_template('register.html', error_message=error_message)

        if get_user_by_email(email):
            error_message = "This email is already registered. Please log in."
            return render_template('register.html', error_message=error_message)

        add_user(full_name, email, password)

        flash("Account created successfully! You can now log in.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.')
    return redirect(url_for('home'))

@app.route('/creator-dashboard')
def creator_dashboard():
    if session.get('role') != 'creator':
        return redirect(url_for('login'))

    conn = connect_db()

    docs = conn.execute(
        'SELECT * FROM documents WHERE author_id = ? ORDER BY updated_at DESC', (session['user_id'],)
    ).fetchall()

    user = conn.execute(
        'SELECT name FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()

    recent_activities = []
    for doc in docs[:5]:
        if doc['status'] == 'review':
            action = 'Submitted for review'
        elif doc['status'] == 'approved':
            action = 'Approved'
        elif doc['status'] == 'rejected':
            action = 'Rejected'
        else:
            action = 'Edited'

        recent_activities.append({
            'document_name': doc['title'],
            'timestamp': f"{action} at {doc['updated_at']}"
        })

    conn.close()

    return render_template('creator_dashboard.html',
                           documents=docs,
                           user_name=user['name'],
                           recent_activities=recent_activities)

@app.route('/reviewer-dashboard')
def reviewer_dashboard():
    if session.get('role') != 'reviewer':
        return redirect(url_for('login'))

    query = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')

    conn = connect_db()

    # Base SQL with statuses: review + completed
    sql = '''
        SELECT d.*, u.name as author_name
        FROM documents d
        JOIN users u ON d.author_id = u.id
        WHERE d.status IN ('review', 'approved', 'rejected')
    '''
    params = []

    # Search filter
    if query:
        sql += ' AND (d.title LIKE ? OR u.name LIKE ?)'
        like_query = f'%{query}%'
        params += [like_query, like_query]

    # Sorting
    if sort == 'oldest':
        sql += ' ORDER BY d.updated_at ASC'
    elif sort == 'author':
        sql += ' ORDER BY u.name ASC'
    else:
        sql += ' ORDER BY d.updated_at DESC'

    documents = conn.execute(sql, params).fetchall()

    # Reviewer name for recent activity
    reviewer_name = session.get('user_name', 'Reviewer')

    recent_activities = conn.execute('''
        SELECT d.title as document_name, MAX(c.created_at) as timestamp
        FROM comments c
        JOIN documents d ON c.document_id = d.id
        WHERE c.author = ? AND c.created_at >= datetime('now', '-7 days')
        GROUP BY c.document_id
        ORDER BY timestamp DESC
        LIMIT 10
    ''', (reviewer_name,)).fetchall()

    conn.close()

    return render_template('reviewer_dashboard.html',
                           documents=documents,
                           recent_activities=recent_activities,
                            user_name=reviewer_name)


@app.route('/admin-dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('login'))

    conn = connect_db()

    # Handle Add Reviewer
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'reviewer')

        existing = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('Email already exists')
        else:
            hashed_pw = generate_password_hash(password)
            conn.execute(
                'INSERT INTO users (name, email, password, role, status) VALUES (?, ?, ?, ?, ?)',
                (name, email, hashed_pw, role, 'active')
            )
            conn.commit()
            flash(f'{role.capitalize()} added successfully.')

    # Fetch all users
    users = conn.execute('SELECT * FROM users ORDER BY id DESC').fetchall()

    # Fetch all documents with author info
    documents = conn.execute('''
        SELECT d.*, u.name as author_name
        FROM documents d
        JOIN users u ON d.author_id = u.id
        ORDER BY d.updated_at DESC
    ''').fetchall()

    # Dashboard stats
    stats = {
        'total_users': conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],
        'total_documents': conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0],
        'approved_documents': conn.execute('SELECT COUNT(*) FROM documents WHERE status = "approved"').fetchone()[0],
        'rejected_documents': conn.execute('SELECT COUNT(*) FROM documents WHERE status = "rejected"').fetchone()[0],
        'review_documents': conn.execute('SELECT COUNT(*) FROM documents WHERE status = "review"').fetchone()[0],
        'draft_documents': conn.execute('SELECT COUNT(*) FROM documents WHERE status = "draft"').fetchone()[0],
    }

    # Recent activity with proper reviewer name fallback
    recent_activity = conn.execute('''
        SELECT 
            c.comment, 
            COALESCE(u.name, c.author) AS reviewer_name, 
            c.created_at, 
            d.title
        FROM comments c
        JOIN documents d ON c.document_id = d.id
        LEFT JOIN users u ON c.author = u.name
        ORDER BY c.created_at DESC
        LIMIT 10
    ''').fetchall()

    conn.close()

    return render_template(
        'admin_dashboard.html',
        users=users,
        documents=documents,
        stats=stats,
        recent_activity=recent_activity
    )


@app.route('/admin/document/<int:doc_id>', methods=['GET', 'POST'])
def view_document(doc_id):
    if not session.get('admin'):
        return redirect(url_for('login'))

    conn = connect_db()

    # Fetch document and author
    doc = conn.execute('''
        SELECT d.id, d.title, d.content, d.updated_at, d.status, u.name AS author_name
        FROM documents d
        JOIN users u ON d.author_id = u.id
        WHERE d.id = ?
    ''', (doc_id,)).fetchone()

    if not doc:
        conn.close()
        flash('Document not found.')
        return redirect(url_for('admin_dashboard'))

    # Handle Approve / Reject
    if request.method == 'POST':
        action = request.form['action']
        comment = request.form.get('comment', '')

        new_status = 'approved' if action == 'approve' else 'rejected'

        conn.execute('UPDATE documents SET status = ?, updated_at = datetime("now") WHERE id = ?',
                     (new_status, doc_id))
        conn.execute('INSERT INTO comments (document_id, author, comment, created_at) VALUES (?, ?, ?, datetime("now"))',
                     (doc_id, 'Admin', comment))
        conn.commit()
        flash(f'Document {new_status} successfully.')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    # Fetch version history
    versions = conn.execute('''
        SELECT version_number, content, updated_at
        FROM document_versions
        WHERE document_id = ?
        ORDER BY version_number DESC
    ''', (doc_id,)).fetchall()

    # Fetch comments with reviewer name fallback
    comments = conn.execute('''
        SELECT 
            c.comment,
            COALESCE(u.name, c.author) AS reviewer_name,
            c.author,
            c.created_at
        FROM comments c
        LEFT JOIN users u ON c.author = u.name
        WHERE c.document_id = ?
        ORDER BY c.created_at DESC
    ''', (doc_id,)).fetchall()

    conn.close()
    return render_template('admin_view_document.html', doc=doc, versions=versions, comments=comments)



@app.route('/document/new', methods=['GET', 'POST'])
def create_document():
    if session.get('role') != 'creator':
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        action = request.form['action']
        status = 'review' if action == 'submit' else 'draft'

        conn = connect_db()
        conn.execute('INSERT INTO documents (title, content, author_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, datetime("now"), datetime("now"))',
                     (title, content, session['user_id'], status))
        conn.commit()
        conn.close()
        flash('Document saved successfully.')
        return redirect(url_for('creator_dashboard'))

    return render_template('document_editor.html', doc=None)

@app.route('/document/<int:doc_id>/edit', methods=['GET', 'POST'])
def edit_document(doc_id):
    if session.get('role') != 'creator':
        return redirect(url_for('login'))

    conn = connect_db()
    doc = conn.execute('SELECT * FROM documents WHERE id = ? AND author_id = ?', 
                       (doc_id, session['user_id'])).fetchone()

    if not doc:
        flash('Document not found.')
        return redirect(url_for('creator_dashboard'))

    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        action = request.form['action']
        status = 'review' if action == 'submit' else 'draft'

        # Save current version before update
        existing_doc = conn.execute('SELECT content FROM documents WHERE id = ?', (doc_id,)).fetchone()
        if existing_doc:
            latest_version = conn.execute(
                'SELECT MAX(version_number) FROM document_versions WHERE document_id = ?',
                (doc_id,)
            ).fetchone()[0] or 0
            conn.execute('''
                INSERT INTO document_versions (document_id, version_number, content, updated_at)
                VALUES (?, ?, ?, datetime("now"))
            ''', (doc_id, latest_version + 1, existing_doc['content']))

        # Update document
        conn.execute('UPDATE documents SET title = ?, content = ?, status = ?, updated_at = datetime("now") WHERE id = ?',
                     (title, content, status, doc_id))
        conn.commit()
        conn.close()

        flash('Document updated successfully.')
        return redirect(url_for('creator_dashboard'))

    return render_template('document_editor.html', doc=doc)


@app.route('/document/<int:doc_id>/history')
def document_history(doc_id):
    if session.get('role') != 'creator' and not session.get('admin'):
        return redirect(url_for('login'))

    conn = connect_db()

    # Fetch document title
    doc = conn.execute(
        'SELECT title FROM documents WHERE id = ?',
        (doc_id,)
    ).fetchone()

    if not doc:
        conn.close()
        flash('Document not found.')
        return redirect(url_for('creator_dashboard'))

    # Fetch version history
    versions = conn.execute('''
        SELECT version_number, content, updated_at
        FROM document_versions
        WHERE document_id = ?
        ORDER BY version_number DESC
    ''', (doc_id,)).fetchall()

    # Fetch all reviewer/admin comments for this document #picks the first non null value
    comments = conn.execute('''
        SELECT 
            c.comment,
            COALESCE(u.name, c.author) AS reviewer_name, 
            c.created_at
        FROM comments c
        LEFT JOIN users u ON c.author = u.name
        WHERE c.document_id = ?
        ORDER BY c.created_at DESC
    ''', (doc_id,)).fetchall()

    conn.close()

    return render_template(
        'document_history.html',
        doc=doc,
        versions=versions,
        comments=comments 
    )

#document review and document

@app.route('/document/<int:doc_id>/review', methods=['GET', 'POST'])
def review_document(doc_id):
    if session.get('role') != 'reviewer':
        return redirect(url_for('login'))

    conn = connect_db()

    doc = conn.execute('''
        SELECT d.*, u.name AS author_name
        FROM documents d
        JOIN users u ON d.author_id = u.id
        WHERE d.id = ?
    ''', (doc_id,)).fetchone()

    if not doc:
        conn.close()
        flash('Document not found.')
        return redirect(url_for('reviewer_dashboard'))

    if request.method == 'POST':
        action = request.form['action']
        comment = request.form['comment']

        status = 'approved' if action == 'approve' else 'rejected'
        reviewer_name = session.get('user_name', 'Reviewer')  # You can replace with session-stored name

        conn.execute('''
            UPDATE documents
            SET status = ?, updated_at = datetime("now")
            WHERE id = ?
        ''', (status, doc_id))

        conn.execute('''
            INSERT INTO comments (document_id, author, comment, created_at)
            VALUES (?, ?, ?, datetime("now"))
        ''', (doc_id, reviewer_name, comment))
        conn.commit()
        conn.close()

        flash(f'Document {status}.')
        return redirect(url_for('reviewer_dashboard'))

    comments = conn.execute('SELECT * FROM comments WHERE document_id = ?', (doc_id,)).fetchall()
    conn.close()

    return render_template('document_review.html', doc=doc, comments=comments)


@app.route('/document/<int:doc_id>/download')
def download_pdf(doc_id):
    if session.get('role') not in ('creator', 'reviewer', 'admin'):
        return redirect(url_for('login'))

    conn = connect_db()
    doc = conn.execute('SELECT title, content, status FROM documents WHERE id = ?', (doc_id,)).fetchone()
    conn.close()

    if not doc or doc['status'] != 'approved':
        flash('Only approved documents can be downloaded as PDF.')
        return redirect(url_for('creator_dashboard'))

    html_content = f'''
        <html>
        <head><meta charset="UTF-8"></head>
        <body>
            <h1>{doc["title"]}</h1>
            {doc["content"]}
        </body>
        </html>
    '''

    pdf = io.BytesIO()
    pisa.CreatePDF(html_content, dest=pdf)
    pdf.seek(0)

    response = make_response(pdf.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=\"{doc["title"]}.pdf\"'
    return response


@app.route('/admin/user/<int:user_id>/edit', methods=['GET', 'POST'])
def edit_user(user_id):
    conn = connect_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    if request.method == 'POST':
        name = request.form['name']
        role = request.form['role']
        conn.execute('UPDATE users SET name = ?, role = ? WHERE id = ?', (name, role, user_id))
        conn.commit()
        conn.close()
        flash('User updated successfully.')
        return redirect(url_for('admin_dashboard'))

    conn.close()
    return render_template('edit_user.html', user=user)


@app.route('/admin/user/<int:user_id>/delete')
def delete_user(user_id):
    conn = connect_db()
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    flash('User deleted successfully.')
    return redirect(url_for('admin_dashboard'))


if __name__ == '__main__':
    app.run(debug=True)
