"""
Badatime 웹 파싱 유틸리티

BeautifulSoup 파싱을 견고하게 처리하기 위해 구조 기반 선택자 사용
"""
import re
from typing import Optional, Dict, List, Any
from bs4 import BeautifulSoup

BADATIME_BASE = 'https://www.badatime.com'


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
    #: label(예: "간조 03:12\n(339) ▼-380") 안의 cm값·증감을 뽑는다 - 카드
    #: 행(만조/간조 표)과 조위 곡선 보간(앵커 좌표) 양쪽에 필요하다.
    _TIDE_LEVEL_DELTA_RE = re.compile(r'\((\d+)\)\s*([▲▼])([+-]?\d+)')

    @staticmethod
    def _time_to_minutes(time_str: str) -> Optional[int]:
        parts = time_str.split(':')
        if len(parts) != 2:
            return None
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None

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
            rain_el = row.select_one('.wp-tempbox .wp-rain')

            result.append({
                'time': time_el.get_text(strip=True) if time_el else '',
                'weather_icon_url': self._absolutize(icon_el['src']) if icon_el and icon_el.get('src') else '',
                'weather_text': sky_el.get_text(strip=True) if sky_el else '',
                'temperature': temp_el.get_text(strip=True) if temp_el else '',
                'wind_dir_icon_url': self._absolutize(wind_icon_el['src']) if wind_icon_el and wind_icon_el.get('src') else '',
                'wind_dir': wind_dir_el.get_text(strip=True) if wind_dir_el else '',
                'wind_speed': wind_subs[0].get_text(' ', strip=True) if len(wind_subs) > 0 else '',
                'wave_height': wind_subs[1].get_text(' ', strip=True) if len(wind_subs) > 1 else '',
                # 비가 안 오는 날은 badatime 쪽 마크업 자체가 비어 있다(0mm를
                # 안 적는다) - 그런 경우는 빈 문자열로 정직하게 둔다.
                'precipitation': rain_el.get_text(' ', strip=True) if rain_el else '',
            })
        return result

    def parse_tide_events(self) -> List[Dict[str, Any]]:
        """간조/만조 - 그날 조석 주기에 따라 3~4건으로 개수가 바뀐다(하드코딩 금지).

        `mins`(자정 기준 분)/`level`(cm)/`delta`(부호 있는 증감)는 label
        문자열 안에서 추가로 뽑는다 - 카드 행 렌더링과 조위 곡선 보간
        앵커 양쪽에 필요하다. label 자체는 그대로 남겨 이전 버전과
        호환한다.
        """
        events = []
        for m in self._TIDE_EVENT_RE.finditer(self.html):
            time_str, label, kind = m.groups()
            label = label.replace('\\n', '\n')
            level = delta = None
            lm = self._TIDE_LEVEL_DELTA_RE.search(label)
            if lm:
                level = int(lm.group(1))
                delta = int(lm.group(3))  # 부호는 이미 캡처 그룹에 포함됨(예: "+292"/"-380")
            events.append({
                'time': time_str,
                'label': label,
                'type': kind,  # 'low' = 간조, 'high' = 만조
                'mins': self._time_to_minutes(time_str),
                'level': level,
                'delta': delta,
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


class DailyPageParser:
    """Badatime `/{port_id}/daily` 페이지 파서 - 오늘부터 30일치 물때 요약.

    달력 월 단위가 아니라 **요청 시점 기준 앞으로 30일 롤링 윈도우**다(실측
    확인, 2026-09-14 조회 시 9/14~10/13). 하루당 물때/물흐름/만조/간조/
    일출몰/월출몰/날씨 아이콘이 한 행(`tr.day-row`)에 다 있어서, 월별 화면
    하나 그리려고 그래프 페이지를 30번 부를 필요가 없다(사용자 제보로
    발견 - `GraphPageParser`와는 완전히 다른 마크업이라 별도 클래스로 둔다).

    각 행의 날짜는 요일 텍스트로 월 경계를 추측하지 않고, "상세보기" 링크
    (`/{port_id}/graph/{date}`)에 박힌 실제 날짜를 그대로 쓴다.
    """

    # 일요일은 badatime이 <font color="#FF0000">일</font>로 감싸서 괄호와
    # 요일 글자가 서로 다른 텍스트 노드로 쪼개진다 - get_text(' ', strip=True)가
    # 그 사이에 공백을 넣어 "20( 일 )"처럼 되므로, 괄호 안쪽 공백도 허용해야
    # 일요일 행에서 요일이 빈 문자열로 사라지지 않는다(실측 fixture로 발견).
    _WEEK_CELL_RE = re.compile(r'(\d{1,2})\s*\(\s*([일월화수목금토])\s*\)')
    _EVENT_CELL_RE = re.compile(r'(\d{1,2}:\d{2})\s*\(\s*(\d+)\s*\)\s*([▲▼])([+-]?\d+)')
    _DETAIL_LINK_RE = re.compile(r'/graph/(\d{4})-(\d{1,2})-(\d{1,2})')

    def __init__(self, html: str):
        self.html = html
        self.soup = BeautifulSoup(html, 'html.parser')

    @staticmethod
    def _absolutize(src: str) -> str:
        return GraphPageParser._absolutize(src)

    def _parse_event_cell(self, cell, kind: str) -> List[Dict[str, Any]]:
        """만조(`td.manjo`)/간조(`td.ganjo`) 칸 - 하루 최대 2건. 카드/곡선
        보간에 그대로 쓸 수 있게 GraphPageParser.parse_tide_events()와 같은
        모양(mins/level/delta)으로 맞춘다."""
        if not cell:
            return []
        text = cell.get_text(' ', strip=True)
        events = []
        for m in self._EVENT_CELL_RE.finditer(text):
            time_str, level_str, arrow, delta_str = m.groups()
            events.append({
                'time': time_str,
                'type': kind,
                'mins': GraphPageParser._time_to_minutes(time_str),
                'level': int(level_str),
                'delta': int(delta_str),
            })
        return events

    def parse(self) -> List[Dict[str, Any]]:
        """하루 1건씩, 최대 30건. 한 행이 깨져도 나머지 날짜는 살아남는다
        (실패 격리)."""
        days = []
        for row in self.soup.select('tr.day-row'):
            try:
                days.append(self._parse_row(row))
            except Exception:
                continue
        return days

    def _parse_row(self, row) -> Dict[str, Any]:
        week_el = row.select_one('td#week')
        week_text = week_el.get_text(' ', strip=True) if week_el else ''
        wm = self._WEEK_CELL_RE.search(week_text)
        weekday = wm.group(2) if wm else ''
        lunar_el = row.select_one('td#week span')
        lunar_date = lunar_el.get_text(strip=True) if lunar_el else ''

        detail_link = row.select_one('td.pc-only a')
        date_str = None
        if detail_link and detail_link.get('href'):
            dm = self._DETAIL_LINK_RE.search(detail_link['href'])
            if dm:
                y, mo, d = dm.groups()
                date_str = f'{y}-{int(mo):02d}-{int(d):02d}'

        moon_el = row.select_one('td.moon img')
        tide_el = row.select_one('td.tide .tide-text')
        flow_el = row.select_one('td.pc-flow .progress-bar')
        weather_imgs = row.select('td.weather img')
        s_rs = row.select_one('td.s_rs')
        m_rs = row.select_one('td.m_rs')
        s_times = list(s_rs.stripped_strings) if s_rs else []
        m_times = list(m_rs.stripped_strings) if m_rs else []

        flow_percent = None
        if flow_el and flow_el.get('data-value'):
            try:
                flow_percent = int(flow_el['data-value'])
            except ValueError:
                flow_percent = None

        tide_events = (
            self._parse_event_cell(row.select_one('td.manjo'), 'high')
            + self._parse_event_cell(row.select_one('td.ganjo'), 'low')
        )
        tide_events.sort(key=lambda e: e['mins'] if e['mins'] is not None else 0)

        return {
            'date': date_str,
            'weekday': weekday,
            'lunar_date': lunar_date,
            'moon_icon_url': self._absolutize(moon_el['src']) if moon_el and moon_el.get('src') else '',
            'tide_label': tide_el.get_text(strip=True).replace(' ', '') if tide_el else '',
            'flow_percent': flow_percent,
            'weather': [
                {'icon_url': self._absolutize(img['src']), 'alt': img.get('alt', '')}
                for img in weather_imgs if img.get('src')
            ],
            'tide_events': tide_events,
            'sunrise': s_times[0] if len(s_times) > 0 else None,
            'sunset': s_times[1] if len(s_times) > 1 else None,
            'moonrise': m_times[0] if len(m_times) > 0 else None,
            'moonset': m_times[1] if len(m_times) > 1 else None,
        }
