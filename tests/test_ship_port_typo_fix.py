"""선사 노트의 항구 오타(연안부드 -> 연안부두)를 1회만 바로잡는다."""
from db import db, fix_ship_port_typos
from models import AppSetting, FishingShip


def test_known_typo_is_fixed_once_and_other_ports_are_untouched(app):
    with app.app_context():
        AppSetting.query.filter_by(key='ship_port_typos_fixed_20261010').delete()
        db.session.add_all([
            FishingShip(name='와이파이호', region='인천', port='연안부드'),
            FishingShip(name='금강스타', region='인천', port='연안부두'),
            FishingShip(name='범블비호', region='보령', port='오천'),
        ])
        db.session.commit()

        fix_ship_port_typos()
        ports = {s.name: s.port for s in FishingShip.query.all()}
        assert ports == {'와이파이호': '연안부두', '금강스타': '연안부두', '범블비호': '오천'}

        # 플래그가 서 있으면 다시 돌지 않는다(나중에 사용자가 같은 값을 일부러 넣어도 덮어쓰지 않음)
        FishingShip.query.filter_by(name='와이파이호').update({'port': '연안부드'})
        db.session.commit()
        fix_ship_port_typos()
        assert FishingShip.query.filter_by(name='와이파이호').one().port == '연안부드'
