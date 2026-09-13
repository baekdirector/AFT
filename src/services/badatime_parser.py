"""
Badatime 웹 파싱 유틸리티

BeautifulSoup 파싱을 견고하게 처리하기 위해 구조 기반 선택자 사용
"""
import re
from typing import Optional, Dict, List, Any
from bs4 import BeautifulSoup, Tag

BADATIME_BASE = 'https://www.badatime.com'


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


class GraphPageParser:
    """Badatime `/{port_id}/graph/{date}` 페이지 파서.

    이 페이지 하나에 시간대별 날씨·간조/만조·일출몰/월출몰·물때/물흐름이
    전부 들어있다(구 `/tide/{date}` 표 페이지보다 마크업이 깔끔하다). 우리
    화면(status.html 팝업, weather.html)이 더 이상 바다타임을 iframe으로
    그대로 띄우지 않고, 여기서 뽑은 원시 데이터만으로 자체 위젯을 그리기
    위해 만들었다 - LNB(사이드바)를 원천적으로 안 가져오고, 패널 크기도
    우리가 정할 수 있게 하려는 목적(사용자 요청).

    간조/만조·일출몰/월출몰 값은 페이지 안 인라인 <script>에 리터럴로
    박혀 있어(예: `var tideTimes = [{time: "03:12", label: "간조 03:12\\n
    (339) ▼-380", type: "low"}, ...]`, `var sunriseTime = "06:18";`) DOM
    선택자가 아니라 정규식으로 뽑는다. 각 부분을 개별 try/except로 감싸서
    한 부분이 사이트 개편으로 깨져도 나머지는 살아남는다(실패 격리).
    """

    _TIDE_EVENT_RE = re.compile(
        r'\{\s*time:\s*"([\d:]+)"\s*,\s*label:\s*"([^"]*)"\s*,\s*type:\s*"(low|high)"\s*\}'
    )
    _SUN_MOON_RE = re.compile(
        r'var\s+(sunrise|sunset|moonrise|moonset)Time\s*=\s*"([\d:]+|-+:?-*)"\s*;'
    )
    _FLOW_PERCENT_RE = re.compile(r'(\d+)\s*%')

    def __init__(self, html: str):
        self.html = html
        self.soup = BeautifulSoup(html, 'html.parser')

    @staticmethod
    def _absolutize(src: str) -> str:
        if not src:
            return src
        if src.startswith('//'):
            return 'https:' + src
        if src.startswith('/'):
            return BADATIME_BASE + src
        return src

    def parse_hourly(self) -> List[Dict[str, Any]]:
        """`.weather-list > .wp-row` 반복 - 시간대별 날씨/풍향/풍속/파고."""
        rows = self.soup.select('.weather-list .wp-row')
        result = []
        for row in rows:
            time_el = row.select_one('.wp-time span')
            icon_el = row.select_one('.wp-weather img.wp-ico')
            sky_el = row.select_one('.wp-weather .wp-sky')
            temp_el = row.select_one('.wp-tempbox .wp-temp')
            wind_icon_el = row.select_one('.wp-wind .wp-wind-top img')
            wind_dir_el = row.select_one('.wp-wind .wp-wind-top span')
            wind_subs = row.select('.wp-wind .wp-wind-sub')

            result.append({
                'time': time_el.get_text(strip=True) if time_el else '',
                'weather_icon_url': self._absolutize(icon_el['src']) if icon_el and icon_el.get('src') else '',
                'weather_text': sky_el.get_text(strip=True) if sky_el else '',
                'temperature': temp_el.get_text(strip=True) if temp_el else '',
                'wind_dir_icon_url': self._absolutize(wind_icon_el['src']) if wind_icon_el and wind_icon_el.get('src') else '',
                'wind_dir': wind_dir_el.get_text(strip=True) if wind_dir_el else '',
                'wind_speed': wind_subs[0].get_text(' ', strip=True) if len(wind_subs) > 0 else '',
                'wave_height': wind_subs[1].get_text(' ', strip=True) if len(wind_subs) > 1 else '',
            })
        return result

    def parse_tide_events(self) -> List[Dict[str, str]]:
        """간조/만조 - 그날 조석 주기에 따라 3~4건으로 개수가 바뀐다(하드코딩 금지)."""
        events = []
        for m in self._TIDE_EVENT_RE.finditer(self.html):
            time_str, label, kind = m.groups()
            events.append({
                'time': time_str,
                'label': label.replace('\\n', '\n'),
                'type': kind,  # 'low' = 간조, 'high' = 만조
            })
        return events

    def parse_sun_moon(self) -> Dict[str, Optional[str]]:
        """일출/일몰/월출/월몰 - 값이 없는 날은 "--:--"로 오므로 None 처리."""
        result: Dict[str, Optional[str]] = {
            'sunrise': None, 'sunset': None, 'moonrise': None, 'moonset': None,
        }
        for m in self._SUN_MOON_RE.finditer(self.html):
            key, value = m.groups()
            result[key] = value if ':' in value and '-' not in value else None
        return result

    def parse_flow_percent(self) -> Optional[int]:
        """물흐름 퍼센트 - `<span class="ct-flow">물흐름 : 29%</span>`."""
        el = self.soup.select_one('.ct-flow')
        if not el:
            return None
        m = self._FLOW_PERCENT_RE.search(el.get_text())
        return int(m.group(1)) if m else None

    def parse_tide_label(self) -> Optional[str]:
        """물때 이름 텍스트(예: "무시") - 보조 표시용. 실제 N물 숫자는
        services.tide.mulddae 가 따로 계산한다(이 값과 안 섞는다)."""
        el = self.soup.select_one('.ct-tide')
        text = el.get_text(strip=True) if el else ''
        return text or None

    def parse(self) -> Dict[str, Any]:
        """전체를 한 번에 파싱한다. 부분 실패는 격리한다."""
        result: Dict[str, Any] = {
            'hourly': [], 'tide_events': [], 'sun_moon': {}, 'flow_percent': None, 'tide_label': None,
        }
        try:
            result['hourly'] = self.parse_hourly()
        except Exception:
            pass
        try:
            result['tide_events'] = self.parse_tide_events()
        except Exception:
            pass
        try:
            result['sun_moon'] = self.parse_sun_moon()
        except Exception:
            pass
        try:
            result['flow_percent'] = self.parse_flow_percent()
        except Exception:
            pass
        try:
            result['tide_label'] = self.parse_tide_label()
        except Exception:
            pass
        return result
