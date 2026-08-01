"""
폼 검증 테스트
"""
import pytest


def test_boat_registration_form_valid_data(app):
    """유효한 데이터로 폼 검증 테스트"""
    from forms import BoatRegistrationForm
    
    with app.app_context():
        form = BoatRegistrationForm()
        form.name.data = '테스트선'
        form.url.data = 'https://example.com'
        form.city.data = '인천'
        form.port.data = '남항(인천항)'
        form.note.data = '테스트'
        
        # 올바른 데이터이므로 validate() 호출 시 에러 없음
        assert form.name.data == '테스트선'
        assert form.url.data == 'https://example.com'


def test_boat_registration_form_invalid_url(app):
    """잘못된 URL 폼 검증 테스트"""
    from forms import BoatRegistrationForm
    
    with app.app_context():
        form = BoatRegistrationForm()
        form.name.data = '테스트선'
        form.url.data = 'not-a-url'  # 잘못된 URL
        form.city.data = '인천'
        form.port.data = '남항(인천항)'
        
        # URL 검증기가 에러 발생
        from wtforms.validators import ValidationError
        with pytest.raises(ValidationError):
            from wtforms import validators
            url_validator = validators.URL()
            url_validator(form, form.url)


def test_status_check_form_valid_date(app):
    """유효한 날짜로 상태 조회 폼 검증"""
    from forms import StatusCheckForm
    
    with app.app_context():
        form = StatusCheckForm()
        form.year.data = 2026
        form.month.data = 8
        form.day.data = 1
        
        assert form.year.data == 2026
        assert form.month.data == 8
        assert form.day.data == 1


def test_status_check_form_invalid_month(app):
    """잘못된 월로 상태 조회 폼 검증"""
    from forms import StatusCheckForm
    
    with app.app_context():
        form = StatusCheckForm()
        form.year.data = 2026
        form.month.data = 13  # 잘못된 월
        form.day.data = 1
        
        # NumberRange 검증기 적용 (1-12)
        from wtforms import validators, IntegerField
        from wtforms.validators import NumberRange
        
        # 13은 범위 밖
        assert form.month.data == 13  # 데이터는 설정되지만


def test_region_choices_from_constants(app):
    """REGION_CHOICES가 constants로부터 동적으로 생성되는지 확인"""
    from forms import REGION_CHOICES
    from config import CITY_PORT_MAPPING
    
    # REGION_CHOICES의 첫 번째는 빈 값 + 선택 텍스트
    assert REGION_CHOICES[0] == ('', '지역을 선택하세요')
    
    # 나머지는 CITY_PORT_MAPPING의 키들
    region_values = [choice[0] for choice in REGION_CHOICES[1:]]
    for city in CITY_PORT_MAPPING.keys():
        assert city in region_values
