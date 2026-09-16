"""
StatusPageService / DateValidator 테스트

예전엔 api_response의 (미사용) ApiResponseBuilder 테스트와 한 파일
(test_medium_refactoring.py)에 같이 있었다 - 그쪽을 정리하며 이 서비스
자체 테스트로 분리했다.
"""
from services.status_service import StatusPageService, DateValidator


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
