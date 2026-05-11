from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from zoneinfo import ZoneInfo
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()
SANTIAGO_TZ = ZoneInfo('America/Santiago')


def now_santiago():
    return datetime.now(SANTIAGO_TZ).replace(tzinfo=None)


# ─── Configuración global (clave admin, etc.) ────────────────────────────────
class Config(db.Model):
    __tablename__ = 'config'
    key   = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False)

    @staticmethod
    def get(key, default=None):
        r = Config.query.get(key)
        return r.value if r else default

    @staticmethod
    def set(key, value):
        r = Config.query.get(key)
        if r:
            r.value = value
        else:
            db.session.add(Config(key=key, value=value))
        db.session.commit()


# ─── Evaluadores ─────────────────────────────────────────────────────────────
class Evaluator(db.Model):
    __tablename__ = 'evaluators'
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    active        = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=now_santiago)

    evaluations = db.relationship('Evaluation', backref='evaluator', lazy=True)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'active': self.active}


# ─── Colaboradores ────────────────────────────────────────────────────────────
class Collaborator(db.Model):
    __tablename__ = 'collaborators'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False, unique=True)
    cargo      = db.Column(db.String(120), default='')
    active     = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=now_santiago)

    evaluations = db.relationship('Evaluation', backref='collaborator', lazy=True)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'cargo': self.cargo, 'active': self.active}


# ─── Categorías KPI ───────────────────────────────────────────────────────────
class KPICategory(db.Model):
    __tablename__ = 'kpi_categories'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(200), nullable=False)
    order  = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)

    items = db.relationship('KPIItem', backref='category', lazy=True,
                            order_by='KPIItem.order')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'order': self.order,
            'active': self.active,
            'items': [i.to_dict() for i in self.items if i.active]
        }


# ─── Ítems KPI ────────────────────────────────────────────────────────────────
class KPIItem(db.Model):
    __tablename__ = 'kpi_items'
    id          = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('kpi_categories.id'), nullable=False)
    name        = db.Column(db.String(200), nullable=False)
    max_points  = db.Column(db.Integer, nullable=False)
    order       = db.Column(db.Integer, default=0)
    active      = db.Column(db.Boolean, default=True)

    scores = db.relationship('EvaluationScore', backref='kpi_item', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'category_id': self.category_id,
            'name': self.name,
            'max_points': self.max_points,
            'order': self.order,
            'active': self.active
        }


# ─── Evaluaciones ─────────────────────────────────────────────────────────────
class Evaluation(db.Model):
    __tablename__ = 'evaluations'
    id               = db.Column(db.Integer, primary_key=True)
    evaluator_id     = db.Column(db.Integer, db.ForeignKey('evaluators.id'), nullable=False)
    collaborator_id  = db.Column(db.Integer, db.ForeignKey('collaborators.id'), nullable=False)
    period_start     = db.Column(db.Date, nullable=False)
    period_end       = db.Column(db.Date, nullable=False)
    observations     = db.Column(db.Text, default='')
    commitments      = db.Column(db.Text, default='')
    is_finalized     = db.Column(db.Boolean, default=False)
    created_at       = db.Column(db.DateTime, default=now_santiago)

    scores = db.relationship('EvaluationScore', backref='evaluation', lazy=True,
                             cascade='all, delete-orphan')

    # ── Cálculos ──────────────────────────────────────────────────────────────
    def total_score(self):
        """Suma total de puntos obtenidos sobre el total posible (todas categorías)."""
        obtained = sum(s.score for s in self.scores)
        possible = sum(s.kpi_item.max_points for s in self.scores if s.kpi_item.active)
        return obtained, possible

    def score_by_category(self):
        """Retorna dict {category_name: (obtained, possible, pct)}."""
        cats = {}
        for s in self.scores:
            cat_name = s.kpi_item.category.name
            if cat_name not in cats:
                cats[cat_name] = [0, 0]
            cats[cat_name][0] += s.score
            cats[cat_name][1] += s.kpi_item.max_points
        return {
            k: (v[0], v[1], round(v[0] / v[1] * 100) if v[1] else 0)
            for k, v in cats.items()
        }

    def overall_pct(self):
        obt, pos = self.total_score()
        return round(obt / pos * 100) if pos else 0

    def letter_grade(self):
        pct = self.overall_pct()
        if pct >= 90:
            return 'Excelente'
        elif pct >= 70:
            return 'Bueno'
        elif pct >= 50:
            return 'Regular'
        else:
            return 'Deficiente'

    def grade_color(self):
        pct = self.overall_pct()
        if pct >= 90:
            return '#0d6832'
        elif pct >= 70:
            return '#1a6ba0'
        elif pct >= 50:
            return '#c27c00'
        else:
            return '#b42318'

    def to_dict(self):
        obt, pos = self.total_score()
        return {
            'id': self.id,
            'evaluator_name': self.evaluator.name,
            'collaborator_name': self.collaborator.name,
            'collaborator_cargo': self.collaborator.cargo,
            'period_start': self.period_start.strftime('%Y-%m-%d'),
            'period_end': self.period_end.strftime('%Y-%m-%d'),
            'period_label': (
                f"{self.period_start.strftime('%d/%m/%Y')} – "
                f"{self.period_end.strftime('%d/%m/%Y')}"
            ),
            'observations': self.observations,
            'commitments': self.commitments,
            'is_finalized': self.is_finalized,
            'obtained': obt,
            'possible': pos,
            'overall_pct': self.overall_pct(),
            'letter_grade': self.letter_grade(),
            'grade_color': self.grade_color(),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M'),
            'score_by_category': self.score_by_category()
        }


# ─── Puntajes por ítem ────────────────────────────────────────────────────────
class EvaluationScore(db.Model):
    __tablename__ = 'evaluation_scores'
    id            = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey('evaluations.id'), nullable=False)
    kpi_item_id   = db.Column(db.Integer, db.ForeignKey('kpi_items.id'), nullable=False)
    answer        = db.Column(db.String(2), nullable=False)  # 'SI' or 'NO'
    score         = db.Column(db.Integer, nullable=False)    # puntos obtenidos

    def to_dict(self):
        return {
            'kpi_item_id': self.kpi_item_id,
            'kpi_name': self.kpi_item.name,
            'max_points': self.kpi_item.max_points,
            'answer': self.answer,
            'score': self.score
        }
