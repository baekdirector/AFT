from datetime import datetime
from db import db

class Boat(db.Model):
    __tablename__ = 'boats'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    url = db.Column(db.String(2083), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    port = db.Column(db.String(100), nullable=False)
    note = db.Column(db.Text, nullable=True)
    is_shared = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Boat {self.name}>'
    
    def to_dict(self):
        """Boat 객체를 딕셔너리로 변환하여 JSON 직렬화 가능하게 만듭니다."""
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'city': self.city,
            'port': self.port,
            'note': self.note,
            'is_shared': self.is_shared,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    key = db.Column(db.String(255), primary_key=True)
    value = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<AppSetting {self.key}={self.value}>'
