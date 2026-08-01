"""
상태 조회 관련 비즈니스 로직 서비스

status() 라우트에서 복잡한 로직을 분리하여 관심사를 명확히 합니다.
"""
from typing import Dict, List, Tuple, Optional
from forms import REGION_CHOICES


class StatusPageService:
    """상태 조회 페이지 데이터 준비 서비스"""
    
    @staticmethod
    def get_date_params_from_request(request) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """요청에서 연월일 파라미터 추출 및 정수 변환"""
        y_arg = request.args.get("year")
        m_arg = request.args.get("month")
        d_arg = request.args.get("day")
        
        year, month, day = None, None, None
        
        try:
            if y_arg:
                year = int(y_arg)
        except (TypeError, ValueError):
            year = None
        
        try:
            if m_arg:
                month = int(m_arg)
        except (TypeError, ValueError):
            month = None
        
        try:
            if d_arg:
                day = int(d_arg)
        except (TypeError, ValueError):
            day = None
        
        return year, month, day
    
    @staticmethod
    def get_region_names() -> List[str]:
        """예약현황 화면의 지역 목록을 업무 순서로 반환"""
        preferred_order = ['인천', '안산', '화성', '평택', '당진', '서산', '태안', '보령', '군산', '격포', '여수', '고흥']
        available_regions = {label for value, label in REGION_CHOICES if value}
        return [region for region in preferred_order if region in available_regions]
    
    @staticmethod
    def get_selected_regions(request) -> List[str]:
        """요청에서 선택된 지역 목록 추출"""
        selected = request.args.getlist("regions")
        return selected if selected else ['전체']
    
    @staticmethod
    def get_selected_boats(request) -> List[str]:
        """요청에서 선택된 배 목록 추출"""
        return request.args.getlist("boats")
    
    @staticmethod
    def build_render_context(
        form,
        entries: List[Dict],
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None,
        region_names: Optional[List[str]] = None,
        selected_regions: Optional[List[str]] = None,
        selected_boats: Optional[List[str]] = None,
        region_counts: Optional[Dict] = None,
        total_registered: int = 0,
        region_boats: Optional[Dict] = None
    ) -> Dict:
        """render_template에 전달할 컨텍스트 구성"""
        return {
            'form': form,
            'entries': entries,
            'year': year or "",
            'month': month or "",
            'day': day or "",
            'region_names': region_names or [],
            'selected_regions': selected_regions or ['전체'],
            'selected_boats': selected_boats or [],
            'region_counts': region_counts or {},
            'total_registered': total_registered,
            'region_boats': region_boats or {},
        }


class DateValidator:
    """날짜 유효성 검증"""
    
    @staticmethod
    def is_complete(year: Optional[int], month: Optional[int], day: Optional[int]) -> bool:
        """연월일이 모두 입력되었는지 확인"""
        return year is not None and month is not None and day is not None
    
    @staticmethod
    def validate(year: int, month: int, day: int) -> Tuple[bool, str]:
        """날짜 유효성 검증
        
        Returns:
            (is_valid, error_message)
        """
        if not (1 <= month <= 12):
            return False, "월은 1~12 사이여야 합니다."
        if not (1 <= day <= 31):
            return False, "일은 1~31 사이여야 합니다."
        if not (2000 <= year <= 2100):
            return False, "연도는 2000~2100 사이여야 합니다."
        return True, ""
