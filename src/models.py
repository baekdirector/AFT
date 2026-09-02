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


class Snapshot(db.Model):
    """(배, 날짜, 선박) 하나의 '가장 최근에 확인된 상태' 1행.

    Phase B. 이 표가 있어야 이전과 비교해 변화를 감지할 수 있고(지금까지는
    stateless 라 불가능했다), /status 가 라이브 스크래핑 대신 이 표를 읽으면
    조회가 즉시 끝난다(현재 71척 라이브 조회는 약 114초).

    이력이 아니라 최신 상태만 들고 있는다. (배,날짜,선박) 조합당 1행이며
    수집할 때마다 덮어쓴다. 변화 이력이 필요하면 Notification(Phase C)이 남긴다.

    선박명이 키에 들어가는 이유: sunsang24 선단 페이지 한 장에 여러 척이
    실린다. 실제로 레드헌터 URL 하나가 3척을 내놓는다. 그래서 boat_id 만으로는
    한 행으로 좁혀지지 않는다.
    """
    __tablename__ = 'snapshots'
    __table_args__ = (
        db.UniqueConstraint('boat_id', 'target_date', 'ship_name',
                            name='uq_snapshot_boat_date_ship'),
        db.Index('ix_snapshot_date', 'target_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    boat_id = db.Column(db.Integer, db.ForeignKey('boats.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    target_date = db.Column(db.String(10), nullable=False)   # 'YYYY-MM-DD'
    ship_name = db.Column(db.String(255), nullable=False)

    status = db.Column(db.String(32), nullable=False, default='unknown')
    available = db.Column(db.Integer, nullable=True)
    display_status = db.Column(db.String(255), nullable=True)
    fish = db.Column(db.String(255), nullable=True)
    source_url = db.Column(db.String(2083), nullable=True)

    checked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    boat = db.relationship('Boat', backref=db.backref('snapshots', lazy='dynamic',
                                                      cascade='all, delete-orphan'))

    def __repr__(self):
        return (f'<Snapshot boat={self.boat_id} {self.target_date} '
                f'{self.ship_name} {self.status}>')

    def to_dict(self):
        return {
            'boat_id': self.boat_id,
            'target_date': self.target_date,
            'ship_name': self.ship_name,
            'status': self.status,
            'available': self.available,
            'display_status': self.display_status,
            'fish': self.fish,
            'source_url': self.source_url,
            'checked_at': self.checked_at.isoformat() if self.checked_at else None,
        }


class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    key = db.Column(db.String(255), primary_key=True)
    value = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<AppSetting {self.key}={self.value}>'
