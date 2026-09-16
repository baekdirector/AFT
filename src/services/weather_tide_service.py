"""
항구 데이터 서비스

views.py에서 분리된 비즈니스 로직 서비스
"""
from typing import Dict
from flask import g


class PortDataService:
    """항구 데이터 서비스"""

    @staticmethod
    def get_port_coordinates() -> Dict[str, Dict[str, float]]:
        """항구별 좌표 정보. `models.Port` 표에서 읽는다(예전엔 정적
        PORT_COORDINATES dict + PortCoordinate 오버레이 테이블을 합쳤지만,
        이제 그 정적 dict는 db.initialize_ports()가 앱 시작 시 1회 옮겨
        담는 시드 데이터일 뿐이고 이 표가 유일한 출처다 - 관리자 콘솔
        "항구 정보" 탭이 여기 직접 쓴다). 요청 하나 안에서 여러 번 불려도
        (예: `/` 라우트는 3번) Port 표가 요청 도중 바뀌지 않으므로 `g`에
        요청 단위로 캐시한다."""
        if 'port_coordinates' not in g:
            from models import Port
            g.port_coordinates = {row.name: {'lat': row.lat, 'lon': row.lon} for row in Port.query.all()}
        return g.port_coordinates

    @staticmethod
    def get_city_port_mapping() -> Dict[str, list]:
        """지역별 항구 매핑. `models.Port` 표에서 region별로 묶어 만든다.
        get_port_coordinates와 같은 이유로 요청 단위 캐시(`g`)를 쓴다."""
        if 'city_port_mapping' not in g:
            from models import Port
            mapping: Dict[str, list] = {}
            for row in Port.query.order_by(Port.region, Port.name).all():
                mapping.setdefault(row.region, []).append(row.name)
            g.city_port_mapping = mapping
        return g.city_port_mapping

    @staticmethod
    def get_bada_port_ids() -> Dict[str, int]:
        """항구별 바다타임 포트 ID"""
        from config import BADA_PORT_IDS
        return BADA_PORT_IDS
