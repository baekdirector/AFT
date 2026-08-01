"""
MEDIUM 우선순위 리팩토링 테스트
"""
import pytest
from services.status_service import StatusPageService, DateValidator
from services.api_response import ApiResponseBuilder, ResponseStatus, success_response, error_response


class TestStatusPageService:
    """상태 조회 서비스 테스트"""
    
    def test_get_date_params_all_present(self):
        """모든 날짜 파라미터가 있는 경우"""
        class MockRequest:
            def __init__(self):
                self.args = {'year': '2026', 'month': '8', 'day': '1'}
            
            def get(self, key):
                return self.args.get(key)
        
        req = MockRequest()
        year, month, day = StatusPageService.get_date_params_from_request(req)
        
        assert year == 2026
        assert month == 8
        assert day == 1
    
    def test_get_date_params_partial(self):
        """일부 날짜 파라미터만 있는 경우"""
        class MockRequest:
            def __init__(self):
                self.args = {'year': '2026', 'month': None}
            
            def get(self, key):
                return self.args.get(key)
        
        req = MockRequest()
        year, month, day = StatusPageService.get_date_params_from_request(req)
        
        assert year == 2026
        assert month is None
    
    def test_get_date_params_invalid_format(self):
        """잘못된 형식의 파라미터"""
        class MockRequest:
            def __init__(self):
                self.args = {'year': 'invalid', 'month': '8', 'day': '1'}
            
            def get(self, key):
                return self.args.get(key)
        
        req = MockRequest()
        year, month, day = StatusPageService.get_date_params_from_request(req)
        
        assert year is None
        assert month == 8
    
    def test_build_render_context(self):
        """렌더링 컨텍스트 구성"""
        context = StatusPageService.build_render_context(
            form=None,
            entries=[],
            year=2026,
            month=8,
            region_counts={'인천': 5},
            total_registered=10
        )
        
        assert context['year'] == 2026
        assert context['month'] == 8
        assert context['total_registered'] == 10
        assert context['region_counts']['인천'] == 5


class TestDateValidator:
    """날짜 유효성 검증 테스트"""
    
    def test_is_complete_all_present(self):
        """모든 날짜가 있는 경우"""
        assert DateValidator.is_complete(2026, 8, 1) is True
    
    def test_is_complete_missing_day(self):
        """일이 없는 경우"""
        assert DateValidator.is_complete(2026, 8, None) is False
    
    def test_validate_valid_date(self):
        """유효한 날짜"""
        is_valid, msg = DateValidator.validate(2026, 8, 1)
        assert is_valid is True
        assert msg == ""
    
    def test_validate_invalid_month(self):
        """잘못된 월"""
        is_valid, msg = DateValidator.validate(2026, 13, 1)
        assert is_valid is False
        assert "월" in msg
    
    def test_validate_invalid_day(self):
        """잘못된 일"""
        is_valid, msg = DateValidator.validate(2026, 8, 32)
        assert is_valid is False
        assert "일" in msg
    
    def test_validate_invalid_year(self):
        """잘못된 연도"""
        is_valid, msg = DateValidator.validate(1999, 8, 1)
        assert is_valid is False
        assert "연도" in msg


class TestApiResponse:
    """API 응답 표준화 테스트"""
    
    def test_success_response_builder(self):
        """성공 응답 빌드"""
        response = (ApiResponseBuilder()
                   .success(data={'key': 'value'})
                   .build())
        
        assert response.status == ResponseStatus.SUCCESS
        assert response.data == {'key': 'value'}
        assert response.error is None
    
    def test_error_response_builder(self):
        """에러 응답 빌드"""
        response = (ApiResponseBuilder()
                   .error(error='Database error', error_code='DB_ERROR')
                   .build())
        
        assert response.status == ResponseStatus.ERROR
        assert response.error == 'Database error'
        assert response.error_code == 'DB_ERROR'
    
    def test_validation_error_builder(self):
        """검증 에러 응답 빌드"""
        response = (ApiResponseBuilder()
                   .validation_error(error='Invalid date')
                   .build())
        
        assert response.status == ResponseStatus.VALIDATION_ERROR
        assert response.error_code == 'VALIDATION_ERROR'
    
    def test_response_to_dict_success(self):
        """성공 응답을 딕셔너리로"""
        response = ApiResponseBuilder().success(data=[1, 2, 3]).build()
        response_dict = response.to_dict()
        
        assert response_dict['status'] == 'success'
        assert response_dict['data'] == [1, 2, 3]
        assert 'error' not in response_dict
    
    def test_response_to_dict_error(self):
        """에러 응답을 딕셔너리로"""
        response = ApiResponseBuilder().error(
            error='Not found',
            error_code='NOT_FOUND'
        ).build()
        response_dict = response.to_dict()
        
        assert response_dict['status'] == 'error'
        assert response_dict['error'] == 'Not found'
        assert response_dict['error_code'] == 'NOT_FOUND'
    
    def test_response_to_json(self):
        """응답을 JSON으로"""
        response = ApiResponseBuilder().success(data={'test': 'data'}).build()
        json_str = response.to_json()
        
        assert isinstance(json_str, str)
        assert 'success' in json_str
        assert 'test' in json_str
    
    def test_success_response_function(self):
        """헬퍼 함수 - 성공"""
        result = success_response(data=[1, 2], message='OK')
        
        assert result['status'] == 'success'
        assert result['data'] == [1, 2]
        assert result['message'] == 'OK'
    
    def test_error_response_function(self):
        """헬퍼 함수 - 에러"""
        result = error_response(
            error='Something went wrong',
            error_code='INTERNAL_ERROR'
        )
        
        assert result['status'] == 'error'
        assert result['error'] == 'Something went wrong'
        assert result['error_code'] == 'INTERNAL_ERROR'
