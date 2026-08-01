"""
Badatime 웹 파싱 유틸리티

BeautifulSoup 파싱을 견고하게 처리하기 위해 구조 기반 선택자 사용
"""
from typing import Optional, Dict, List, Any
from bs4 import BeautifulSoup, Tag


class TideTableParser:
    """Badatime 조수 테이블 파서
    
    매직 인덱스 대신 각 행의 첫 번째 셀 텍스트로 행을 식별하여
    구조 변경에 강건성을 높입니다.
    """
    
    ROW_LABELS = {
        'time': '시간',
        'weather': '날씨',
        'temp': '기온',
        'wind_dir': '풍향',
        'wind_speed': '풍속',
        'wave_height': '파고',
        'humidity': '습도',
        'precipitation': '강수'
    }
    
    def __init__(self, table: Tag):
        self.table = table
        self.rows = table.select('tbody > tr')
        self._row_map: Dict[str, Optional[Tag]] = {}
        self._identify_rows()
    
    def _identify_rows(self) -> None:
        """각 행을 첫 번째 셀의 텍스트로 식별"""
        for row in self.rows:
            first_cell = row.find('td')
            if not first_cell:
                continue
            label_text = first_cell.get_text(strip=True).lower()
            
            # 라벨 매칭
            for key, label in self.ROW_LABELS.items():
                if label in label_text:
                    self._row_map[key] = row
                    break
            
            # 첫 번째 행 (헤더) - 시간 정보를 포함
            if not self._row_map.get('time') and self._is_time_row(row):
                self._row_map['time'] = row
    
    def _is_time_row(self, row: Tag) -> bool:
        """시간 헤더 행 식별 (여러 시간 셀을 포함)"""
        cells = row.find_all('td')
        if len(cells) < 3:
            return False
        time_count = 0
        for cell in cells[1:]:
            text = cell.get_text(strip=True)
            if '시' in text or any(c.isdigit() for c in text):
                time_count += 1
        return time_count >= 3
    
    def extract_times(self) -> List[str]:
        """시간 헤더 추출"""
        time_row = self._row_map.get('time')
        if not time_row:
            return []
        
        times = []
        cells = time_row.find_all('td')[1:]  # 첫 번째 열 제외
        for cell in cells:
            text = cell.get_text(strip=True).replace('현재', '').strip()
            if text:
                times.append(text)
        return times
    
    def extract_weather_data(self) -> Dict[str, List[str]]:
        """모든 날씨 관련 데이터 추출"""
        time_count = len(self.extract_times())
        result = {}
        
        data_fields = {
            'weather': [],
            'temp': [],
            'wind_dir': [],
            'wind_speed': [],
            'wave_height': [],
            'humidity': [],
            'precipitation': []
        }
        
        for key in data_fields:
            row = self._row_map.get(key)
            if row:
                cells = row.find_all('td')[1:]
                for cell in cells[:time_count]:
                    data_fields[key].append(cell.get_text(strip=True))
            else:
                data_fields[key] = [''] * time_count
        
        return data_fields
    
    def extract_weather_icons(self) -> List[str]:
        """날씨 아이콘 URL 추출"""
        weather_row = self._row_map.get('weather')
        if not weather_row:
            return []
        
        icons = []
        cells = weather_row.find_all('td')[1:]
        for cell in cells:
            img = cell.find('img')
            icons.append(img['src'] if img else '')
        return icons
    
    def extract_wind_direction_icons(self) -> List[str]:
        """풍향 아이콘 URL 추출"""
        wind_dir_row = self._row_map.get('wind_dir')
        if not wind_dir_row:
            return []
        
        icons = []
        cells = wind_dir_row.find_all('td')[1:]
        for cell in cells:
            img = cell.find('img')
            icons.append(img['src'] if img else '')
        return icons
    
    def parse(self) -> Optional[Dict[str, Any]]:
        """전체 테이블 파싱"""
        try:
            times = self.extract_times()
            if not times:
                return None
            
            weather_data = self.extract_weather_data()
            weather_icons = self.extract_weather_icons()
            wind_icons = self.extract_wind_direction_icons()
            
            result = []
            for i in range(len(times)):
                result.append({
                    'time': times[i] if i < len(times) else '',
                    'weather_icon_url': weather_icons[i] if i < len(weather_icons) else '',
                    'weather_text': weather_data['weather'][i] if i < len(weather_data['weather']) else '',
                    'temperature': weather_data['temp'][i] if i < len(weather_data['temp']) else '',
                    'wind_dir': weather_data['wind_dir'][i] if i < len(weather_data['wind_dir']) else '',
                    'wind_dir_icon_url': wind_icons[i] if i < len(wind_icons) else '',
                    'wind_speed': weather_data['wind_speed'][i] if i < len(weather_data['wind_speed']) else '',
                    'wave_height': weather_data['wave_height'][i] if i < len(weather_data['wave_height']) else '',
                    'humidity': weather_data['humidity'][i] if i < len(weather_data['humidity']) else '',
                    'precipitation': weather_data['precipitation'][i] if i < len(weather_data['precipitation']) else ''
                })
            
            return result
        except Exception as e:
            return None
