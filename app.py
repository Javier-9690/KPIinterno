import os
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, flash)
from models import db, Config, Evaluator, Collaborator, KPICategory, KPIItem, Evaluation, EvaluationScore

load_dotenv()

SANTIAGO_TZ = ZoneInfo('America/Santiago')

def now_santiago():
    return datetime.now(SANTIAGO_TZ).replace(tzinfo=None)

def today_santiago():
    return datetime.now(SANTIAGO_TZ).date()

# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'kpi-secret-2025')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///kpi.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


# ── Seed inicial ──────────────────────────────────────────────────────────────
def seed_database():
    """Carga datos iniciales si la BD está vacía."""
    if KPICategory.query.first():
        return

    # Clave admin por defecto
    if not Config.query.get('admin_key'):
        Config.set('admin_key', 'Admin2025!')

    # Categorías y KPIs del Excel
    cats_data = [
        {
            'name': 'Eficiencia y Responsabilidad',
            'order': 1,
            'items': [
                ('Cumplimiento de tareas asignadas', 30),
                ('Calidad del trabajo',              20),
                ('Cumplimiento de procedimientos',   20),
                ('Cumplimiento de tiempos',          20),
                ('Resolución de problemas',          10),
            ]
        },
        {
            'name': 'Puntualidad y Asistencia',
            'order': 2,
            'items': [
                ('Asistencia efectiva',                    40),
                ('Puntualidad de ingreso',                 40),
                ('Aviso oportuno de ausencias o atrasos',  20),
            ]
        },
        {
            'name': 'Compañerismo',
            'order': 3,
            'items': [
                ('Apoyo al equipo',                         30),
                ('Comunicación y entrega de información',   30),
                ('Respeto y conducta laboral',              25),
                ('Colaboración ante contingencias',         15),
            ]
        },
    ]

    for cat_data in cats_data:
        cat = KPICategory(name=cat_data['name'], order=cat_data['order'])
        db.session.add(cat)
        db.session.flush()
        for i, (item_name, pts) in enumerate(cat_data['items']):
            db.session.add(KPIItem(category_id=cat.id, name=item_name,
                                   max_points=pts, order=i))

    # Colaboradores del Excel
    colaboradores = [
        ('MARCELA CASTRO',    'Recepcionista'),
        ('ESTEFANIA GRANDON', 'Recepcionista'),
        ('NADIA RONCALES',    'Recepcionista'),
        ('HECTOR LANAS',      'Recepcionista'),
        ('BASTIAN HERNANDEZ', 'Recepcionista'),
        ('RICARDO ALCAYAGA',  'Recepcionista'),
        ('CONSUELO NEIRA',    'Recepcionista'),
        ('JONY MERIÑO',       'Recepcionista'),
        ('JAVIER RIVERA',     'Recepcionista'),
    ]
    for nombre, cargo in colaboradores:
        db.session.add(Collaborator(name=nombre, cargo=cargo))

    # Evaluador inicial
    ev = Evaluator(name='ADMINISTRADOR')
    ev.set_password('Admin2025!')
    db.session.add(ev)

    db.session.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────
def check_admin(key):
    return key == Config.get('admin_key', 'Admin2025!')

def current_evaluator():
    eid = session.get('evaluator_id')
    return Evaluator.query.get(eid) if eid else None

def require_login():
    if not current_evaluator():
        return redirect(url_for('login'))
    return None


# ══════════════════════════════════════════════════════════════════════════════
# RUTAS PÚBLICAS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    ev = current_evaluator()
    if ev:
        return redirect(url_for('dashboard'))
    evaluators = Evaluator.query.filter_by(active=True).order_by(Evaluator.name).all()
    return render_template('index.html', evaluators=evaluators)


@app.route('/login', methods=['POST'])
def login():
    ev_id = request.form.get('evaluator_id', type=int)
    pw    = request.form.get('password', '')
    ev    = Evaluator.query.get(ev_id)
    if ev and ev.active and ev.check_password(pw):
        session['evaluator_id'] = ev.id
        return redirect(url_for('dashboard'))
    flash('Contraseña incorrecta o evaluador inactivo.', 'danger')
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/dashboard')
def dashboard():
    redir = require_login()
    if redir: return redir
    ev = current_evaluator()

    evals = (Evaluation.query
             .filter_by(evaluator_id=ev.id)
             .order_by(Evaluation.created_at.desc())
             .limit(30).all())

    collaborators = Collaborator.query.filter_by(active=True).order_by(Collaborator.name).all()
    return render_template('dashboard.html', ev=ev, evaluations=evals,
                           collaborators=collaborators, today=today_santiago())


# ══════════════════════════════════════════════════════════════════════════════
# NUEVA EVALUACIÓN
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/evaluacion/nueva')
def new_evaluation():
    redir = require_login()
    if redir: return redir
    ev = current_evaluator()

    collaborators = Collaborator.query.filter_by(active=True).order_by(Collaborator.name).all()
    categories    = (KPICategory.query.filter_by(active=True)
                     .order_by(KPICategory.order).all())

    today = today_santiago()
    period_end   = today
    period_start = today - timedelta(days=9)

    return render_template('evaluacion.html', ev=ev,
                           collaborators=collaborators,
                           categories=categories,
                           period_start=period_start.strftime('%Y-%m-%d'),
                           period_end=period_end.strftime('%Y-%m-%d'))


@app.route('/evaluacion/guardar', methods=['POST'])
def save_evaluation():
    redir = require_login()
    if redir: return redir
    ev = current_evaluator()

    try:
        collab_id    = int(request.form['collaborator_id'])
        period_start = datetime.strptime(request.form['period_start'], '%Y-%m-%d').date()
        period_end   = datetime.strptime(request.form['period_end'],   '%Y-%m-%d').date()
        observations = request.form.get('observations', '').strip()
        commitments  = request.form.get('commitments', '').strip()
        finalize     = request.form.get('finalize') == '1'

        evaluation = Evaluation(
            evaluator_id    = ev.id,
            collaborator_id = collab_id,
            period_start    = period_start,
            period_end      = period_end,
            observations    = observations,
            commitments     = commitments,
            is_finalized    = finalize,
        )
        db.session.add(evaluation)
        db.session.flush()

        items = KPIItem.query.filter_by(active=True).all()
        for item in items:
            answer = request.form.get(f'kpi_{item.id}', 'NO')
            score  = item.max_points if answer == 'SI' else 0
            db.session.add(EvaluationScore(
                evaluation_id=evaluation.id,
                kpi_item_id=item.id,
                answer=answer,
                score=score
            ))

        db.session.commit()
        return redirect(url_for('view_evaluation', eval_id=evaluation.id))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al guardar: {e}', 'danger')
        return redirect(url_for('new_evaluation'))


# ══════════════════════════════════════════════════════════════════════════════
# VER / EDITAR EVALUACIÓN
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/evaluacion/<int:eval_id>')
def view_evaluation(eval_id):
    redir = require_login()
    if redir: return redir
    ev   = current_evaluator()
    evl  = Evaluation.query.get_or_404(eval_id)
    cats = (KPICategory.query.filter_by(active=True)
            .order_by(KPICategory.order).all())
    return render_template('ver_evaluacion.html', ev=ev, evl=evl, cats=cats)


@app.route('/evaluacion/<int:eval_id>/editar', methods=['GET', 'POST'])
def edit_evaluation(eval_id):
    redir = require_login()
    if redir: return redir
    ev  = current_evaluator()
    evl = Evaluation.query.get_or_404(eval_id)

    if request.method == 'POST':
        admin_key = request.form.get('admin_key', '')
        if not check_admin(admin_key):
            flash('Clave administrativa incorrecta.', 'danger')
            return redirect(url_for('edit_evaluation', eval_id=eval_id))

        evl.period_start  = datetime.strptime(request.form['period_start'], '%Y-%m-%d').date()
        evl.period_end    = datetime.strptime(request.form['period_end'],   '%Y-%m-%d').date()
        evl.observations  = request.form.get('observations', '').strip()
        evl.commitments   = request.form.get('commitments', '').strip()
        evl.is_finalized  = request.form.get('finalize') == '1'

        for score in evl.scores:
            answer       = request.form.get(f'kpi_{score.kpi_item_id}', 'NO')
            score.answer = answer
            score.score  = score.kpi_item.max_points if answer == 'SI' else 0

        db.session.commit()
        flash('Evaluación actualizada correctamente.', 'success')
        return redirect(url_for('view_evaluation', eval_id=eval_id))

    cats = (KPICategory.query.filter_by(active=True)
            .order_by(KPICategory.order).all())
    return render_template('editar_evaluacion.html', ev=ev, evl=evl, cats=cats)


# ══════════════════════════════════════════════════════════════════════════════
# CARTA / IMPRESIÓN
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/evaluacion/<int:eval_id>/carta')
def carta(eval_id):
    redir = require_login()
    if redir: return redir
    evl  = Evaluation.query.get_or_404(eval_id)
    cats = (KPICategory.query.filter_by(active=True)
            .order_by(KPICategory.order).all())
    return render_template('carta.html', evl=evl, cats=cats,
                           today=today_santiago())


# ══════════════════════════════════════════════════════════════════════════════
# HISTORIAL
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/historial')
def history():
    redir = require_login()
    if redir: return redir
    ev = current_evaluator()

    collab_id  = request.args.get('collaborator_id', type=int)
    date_from  = request.args.get('date_from', '')
    date_to    = request.args.get('date_to', '')

    query = Evaluation.query.filter_by(evaluator_id=ev.id)
    if collab_id:
        query = query.filter_by(collaborator_id=collab_id)
    if date_from:
        query = query.filter(Evaluation.period_start >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(Evaluation.period_end   <= datetime.strptime(date_to,   '%Y-%m-%d').date())

    evals = query.order_by(Evaluation.created_at.desc()).all()
    collaborators = Collaborator.query.filter_by(active=True).order_by(Collaborator.name).all()

    return render_template('historial.html', ev=ev, evaluations=evals,
                           collaborators=collaborators,
                           collab_id=collab_id, date_from=date_from, date_to=date_to)


# ══════════════════════════════════════════════════════════════════════════════
# PANEL ADMINISTRACIÓN
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    redir = require_login()
    if redir: return redir
    ev = current_evaluator()
    error = None
    authenticated = session.get('admin_auth', False)

    if request.method == 'POST' and not authenticated:
        key = request.form.get('admin_key', '')
        if check_admin(key):
            session['admin_auth'] = True
            authenticated = True
        else:
            error = 'Clave incorrecta.'

    if not authenticated:
        return render_template('admin_login.html', ev=ev, error=error)

    collaborators = Collaborator.query.order_by(Collaborator.name).all()
    evaluators    = Evaluator.query.order_by(Evaluator.name).all()
    categories    = (KPICategory.query.order_by(KPICategory.order).all())
    return render_template('admin.html', ev=ev,
                           collaborators=collaborators,
                           evaluators=evaluators,
                           categories=categories)


# ── Admin: Colaboradores ──────────────────────────────────────────────────────
@app.route('/admin/colaborador/nuevo', methods=['POST'])
def admin_add_collaborator():
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    name  = request.json.get('name', '').strip().upper()
    cargo = request.json.get('cargo', '').strip()
    if not name:
        return jsonify({'error': 'Nombre requerido'}), 400
    if Collaborator.query.filter_by(name=name).first():
        return jsonify({'error': 'Ya existe'}), 400
    c = Collaborator(name=name, cargo=cargo)
    db.session.add(c)
    db.session.commit()
    return jsonify(c.to_dict())


@app.route('/admin/colaborador/<int:cid>', methods=['PUT'])
def admin_edit_collaborator(cid):
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    c = Collaborator.query.get_or_404(cid)
    data = request.json
    if 'name'   in data: c.name   = data['name'].strip().upper()
    if 'cargo'  in data: c.cargo  = data['cargo'].strip()
    if 'active' in data: c.active = data['active']
    db.session.commit()
    return jsonify(c.to_dict())


# ── Admin: Evaluadores ────────────────────────────────────────────────────────
@app.route('/admin/evaluador/nuevo', methods=['POST'])
def admin_add_evaluator():
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    data = request.json
    name = data.get('name', '').strip().upper()
    pw   = data.get('password', '').strip()
    if not name or not pw:
        return jsonify({'error': 'Nombre y contraseña requeridos'}), 400
    if Evaluator.query.filter_by(name=name).first():
        return jsonify({'error': 'Ya existe'}), 400
    ev = Evaluator(name=name)
    ev.set_password(pw)
    db.session.add(ev)
    db.session.commit()
    return jsonify(ev.to_dict())


@app.route('/admin/evaluador/<int:eid>', methods=['PUT'])
def admin_edit_evaluator(eid):
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    ev   = Evaluator.query.get_or_404(eid)
    data = request.json
    if 'name'     in data: ev.name   = data['name'].strip().upper()
    if 'password' in data and data['password']: ev.set_password(data['password'])
    if 'active'   in data: ev.active = data['active']
    db.session.commit()
    return jsonify(ev.to_dict())


# ── Admin: Categorías KPI ─────────────────────────────────────────────────────
@app.route('/admin/categoria/nueva', methods=['POST'])
def admin_add_category():
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nombre requerido'}), 400
    max_order = db.session.query(db.func.max(KPICategory.order)).scalar() or 0
    cat = KPICategory(name=name, order=max_order + 1)
    db.session.add(cat)
    db.session.commit()
    return jsonify(cat.to_dict())


@app.route('/admin/categoria/<int:cid>', methods=['PUT'])
def admin_edit_category(cid):
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    cat  = KPICategory.query.get_or_404(cid)
    data = request.json
    if 'name'   in data: cat.name   = data['name'].strip()
    if 'active' in data: cat.active = data['active']
    db.session.commit()
    return jsonify(cat.to_dict())


# ── Admin: Ítems KPI ──────────────────────────────────────────────────────────
@app.route('/admin/kpi/nuevo', methods=['POST'])
def admin_add_kpi():
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    data        = request.json
    cat_id      = data.get('category_id')
    name        = data.get('name', '').strip()
    max_points  = data.get('max_points', 10)
    if not name or not cat_id:
        return jsonify({'error': 'Datos incompletos'}), 400
    max_order = db.session.query(db.func.max(KPIItem.order)).filter_by(category_id=cat_id).scalar() or 0
    item = KPIItem(category_id=cat_id, name=name, max_points=int(max_points), order=max_order + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict())


@app.route('/admin/kpi/<int:kid>', methods=['PUT'])
def admin_edit_kpi(kid):
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    item = KPIItem.query.get_or_404(kid)
    data = request.json
    if 'name'       in data: item.name       = data['name'].strip()
    if 'max_points' in data: item.max_points = int(data['max_points'])
    if 'active'     in data: item.active     = data['active']
    db.session.commit()
    return jsonify(item.to_dict())


# ── Admin: Cambiar clave ──────────────────────────────────────────────────────
@app.route('/admin/cambiar-clave', methods=['POST'])
def admin_change_key():
    if not session.get('admin_auth'):
        return jsonify({'error': 'No autorizado'}), 403
    new_key = request.json.get('new_key', '').strip()
    if len(new_key) < 6:
        return jsonify({'error': 'La clave debe tener al menos 6 caracteres'}), 400
    Config.set('admin_key', new_key)
    return jsonify({'ok': True})


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_auth', None)
    return redirect(url_for('dashboard'))


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

with app.app_context():
    db.create_all()
    seed_database()

if __name__ == '__main__':
    app.run(debug=True, port=5001)
