"""
날씨 및 조수 API 서비스

views.py에서 분리된 비즈니스 로직 서비스
"""
from typing import Dict, Any, Optional
import requests
from flask import current_app, jsonify
from bs4 import BeautifulSoup


class WeatherService:
    """기상청 기반 날씨 정보 서비스"""
    
    KMA_API_URL = 'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst'
    REQUEST_TIMEOUT = 10
    
    @staticmethod
    def get_api_key() -> Optional[str]:
        """환경 설정에서 KMA API 키 조회"""
        import os
        return current_app.config.get('KMA_API_KEY') or os.environ.get('KMA_API_KEY')
    
    @staticmethod
    def get_grid_coords(lat: float, lon: float) -> Dict[str, int]:
        """위경도를 기상청 격자 좌표로 변환"""
        import math
        
        RE = 6371.00877
        GRID = 5.0
        SLAT1 = 30.0
        SLAT2 = 60.0
        OLON = 126.0
        OLAT = 38.0
        XO = 43
        YO = 136

        DEGRAD = math.pi / 180.0
        re = RE / GRID
        slat1 = SLAT1 * DEGRAD
        slat2 = SLAT2 * DEGRAD
        olon = OLON * DEGRAD
        olat = OLAT * DEGRAD

        sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
        sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
        sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
        sf = math.pow(sf, sn) * math.cos(slat1) / sn
        ro = math.tan(math.pi * 0.25 + olat * 0.5)
        ro = re * sf / math.pow(ro, sn)

        ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
        ra = re * sf / math.pow(ra, sn)
        theta = lon * DEGRAD - olon
        if theta > math.pi:
            theta -= 2.0 * math.pi
        if theta < -math.pi:
            theta += 2.0 * math.pi
        theta *= sn

        nx = int(ra * math.sin(theta) + XO + 0.5)
        ny = int(ro - ra * math.cos(theta) + YO + 0.5)

        return {'nx': nx, 'ny': ny}
    
    @classmethod
    def fetch_weather(cls, lat: float, lon: float, date_str: str) -> Optional[Dict[str, Any]]:
        """KMA 기상청 API에서 날씨 데이터 조회"""
        from datetime import datetime
        
        try:
            grid = cls.get_grid_coords(lat, lon)
            target_date = datetime.strptime(date_str, '%Y-%m-%d')
            base_date = target_date.strftime('%Y%m%d')
            
            api_key = cls.get_api_key()
            if not api_key:
                return None
            
            params = {
                'serviceKey': api_key,
                'pageNo': '1',
                'numOfRows': '1000',
                'dataType': 'JSON',
                'base_date': base_date,
                'base_time': '0500',
                'nx': grid['nx'],
                'ny': grid['ny']
            }
            
            response = requests.get(cls.KMA_API_URL, params=params, timeout=cls.REQUEST_TIMEOUT)
            if response.status_code != 200:
                return None
            
            return response.json()
        except Exception as e:
            current_app.logger.error(f"KMA API error: {e}")
            return None


class TideService:
    """바다타임 조수 정보 서비스"""
    
    BASE_URL = 'https://www.badatime.com'
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36'
    }
    REQUEST_TIMEOUT = 10
    
    @classmethod
    def fetch_tide_page(cls, port_id: int, date_str: Optional[str] = None) -> Optional[str]:
        """바다타임 조수 페이지 HTML 조회"""
        try:
            url = f"{cls.BASE_URL}/{port_id}/tide"
            if date_str:
                url = f"{url}/{date_str}"
            
            response = requests.get(url, headers=cls.HEADERS, timeout=cls.REQUEST_TIMEOUT)
            if response.status_code != 200:
                current_app.logger.warning(f"Tide page fetch failed: {response.status_code} from {url}")
                return None
            
            return response.text
        except Exception as e:
            current_app.logger.error(f"Tide fetch error: {e}")
            return None
    
    @classmethod
    def fetch_graph_page(cls, port_id: int, date_str: str) -> Optional[str]:
        """바다타임 그래프 페이지 HTML 조회"""
        try:
            url = f"{cls.BASE_URL}/{port_id}/graph/{date_str}"
            response = requests.get(url, headers=cls.HEADERS, timeout=cls.REQUEST_TIMEOUT)
            if response.status_code != 200:
                return None
            return response.text
        except Exception as e:
            current_app.logger.error(f"Graph fetch error: {e}")
            return None


class PortDataService:
    """항구 데이터 서비스"""
    
    @staticmethod
    def get_port_coordinates() -> Dict[str, Dict[str, float]]:
        """항구별 좌표 정보"""
        from config import PORT_COORDINATES
        return PORT_COORDINATES
    
    @staticmethod
    def get_city_port_mapping() -> Dict[str, list]:
        """지역별 항구 매핑"""
        from config import CITY_PORT_MAPPING
        return CITY_PORT_MAPPING
    
    @staticmethod
    def get_bada_port_ids() -> Dict[str, int]:
        """항구별 바다타임 포트 ID"""
        from config import BADA_PORT_IDS
        return BADA_PORT_IDS
