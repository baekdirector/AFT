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


#: 한 사람이 걸 수 있는 감시 개수 상한.
#: 이용자가 친구 5명 안쪽인 취미 규모라 수집량을 작게 유지하는 것이 목적이다.
#: 감시 대상만 주기 수집하므로 이 숫자가 곧 스케줄러 부하다.
MAX_WATCHES_PER_SUBSCRIBER = 5


class Subscriber(db.Model):
    """알림을 받을 사람 하나 = 브라우저의 푸시 구독 하나.

    로그인이 없는 서비스라 사람을 식별할 수단이 푸시 구독 endpoint 뿐이다.
    같은 사람이 다른 기기/브라우저에서 구독하면 별개의 Subscriber 가 된다.
    친구 5명 규모에서는 그걸로 충분하고, 계정 체계를 만드는 것은 과설계다.
    """
    __tablename__ = 'subscribers'

    id = db.Column(db.Integer, primary_key=True)
    # 푸시 서비스가 주는 URL. 사람을 가르는 유일한 키다.
    endpoint = db.Column(db.String(512), nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)

    label = db.Column(db.String(100), nullable=True)          # 사람이 알아볼 별칭
    telegram_chat_id = db.Column(db.String(64), nullable=True)  # 보조 채널(추후)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<Subscriber {self.id} {self.label or self.endpoint[:40]}>'

    def to_subscription_info(self):
        """pywebpush 가 요구하는 모양으로 돌려준다."""
        return {
            'endpoint': self.endpoint,
            'keys': {'p256dh': self.p256dh, 'auth': self.auth},
        }


class Watch(db.Model):
    """'이 배의 이 날짜를 지켜봐 달라' 한 건.

    /status 결과 표의 한 행이 감시 한 건에 대응한다. 그 행이 (배, 선박, 날짜)로
    특정되므로 Snapshot 과 키가 같다. 그래야 수집 결과를 바로 맞물릴 수 있다.
    """
    __tablename__ = 'watches'
    __table_args__ = (
        db.UniqueConstraint('subscriber_id', 'boat_id', 'ship_name', 'target_date',
                            name='uq_watch_subscriber_target'),
        db.Index('ix_watch_active_date', 'active', 'target_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    subscriber_id = db.Column(db.Integer,
                              db.ForeignKey('subscribers.id', ondelete='CASCADE'),
                              nullable=False, index=True)
    boat_id = db.Column(db.Integer, db.ForeignKey('boats.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    ship_name = db.Column(db.String(255), nullable=False)
    target_date = db.Column(db.String(10), nullable=False)   # 'YYYY-MM-DD'

    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    subscriber = db.relationship('Subscriber',
                                 backref=db.backref('watches', lazy='dynamic',
                                                    cascade='all, delete-orphan'))
    boat = db.relationship('Boat',
                           backref=db.backref('watches', lazy='dynamic',
                                              cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Watch {self.ship_name} {self.target_date}>'

    def to_dict(self):
        return {
            'id': self.id,
            'boat_id': self.boat_id,
            # 표의 체크박스는 배 이름으로 행을 찾으므로 이름도 함께 내려준다
            'boat_name': self.boat.name if self.boat else None,
            'ship_name': self.ship_name,
            'target_date': self.target_date,
            'active': self.active,
            # 언제 체크(감시 등록)했는지. /watches 화면의 체크 기록 로그에 쓴다 -
            # "내가 이 배를 정확히 체크했는지"를 시각으로 확인할 수 있어야 한다.
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Notification(db.Model):
    """발송 이력. 존재 이유는 기록이 아니라 중복 방지다.

    dedup_key 는 Transition.dedup_key 를 문자열로 굳힌 것이다. 같은 전환에
    대해 이미 보낸 기록이 있으면 다시 보내지 않는다. 상태가 원복했다가 다시
    열리면 키가 달라지므로 재발송된다(PLAN.md 6).
    """
    __tablename__ = 'notifications'
    __table_args__ = (
        db.Index('ix_notification_dedup', 'watch_id', 'dedup_key'),
    )

    id = db.Column(db.Integer, primary_key=True)
    watch_id = db.Column(db.Integer, db.ForeignKey('watches.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    dedup_key = db.Column(db.String(512), nullable=False)
    channel = db.Column(db.String(32), nullable=False, default='webpush')

    sent_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    result = db.Column(db.String(32), nullable=False, default='pending')  # sent/failed/expired
    detail = db.Column(db.Text, nullable=True)

    watch = db.relationship('Watch',
                            backref=db.backref('notifications', lazy='dynamic',
                                               cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Notification watch={self.watch_id} {self.result}>'


class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    key = db.Column(db.String(255), primary_key=True)
    value = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<AppSetting {self.key}={self.value}>'
