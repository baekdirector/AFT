from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SubmitField, SelectField, HiddenField, TextAreaField, PasswordField, FloatField
from wtforms.validators import DataRequired, URL, NumberRange, Optional, Length


def get_region_choices():
    """지역 선택지를 매 요청마다 새로 계산한다(등록/수정/조회 공용 -
    status_service.StatusPageService.get_region_names()도 이 함수를 쓴다).

    예전엔 모듈 임포트 시점에 정적 CITY_PORT_MAPPING dict로 한 번만 계산했지만,
    이제 지역 목록이 DB(models.Port, 관리자 콘솔 "항구 정보" 탭에서 편집)에서
    나오므로 임포트 시점엔 앱/DB가 아직 준비되지 않았을 수 있다 - 호출할
    때마다 다시 계산해야 방금 추가된 지역도 바로 선택지에 뜬다."""
    from services.weather_tide_service import PortDataService
    return [('', '지역을 선택하세요')] + [(city, city) for city in sorted(PortDataService.get_city_port_mapping().keys())]


# 항구는 city 처럼 고정 목록이 아니다 - 미리 등록되지 않은 항구도 직접 입력해서
# 등록할 수 있어야 한다(Boat.port 는 원래 자유 텍스트 컬럼). 화면에서는 select +
# "직접 입력"으로 안내하지만, 서버는 목록에 없는 값도 그대로 받는다.
# lat/lon 은 그중에서도 정말 새 항구(Port 표에 없는 곳)일 때만 의미가 있는
# 선택 입력이다 - 비워도 등록/수정이 그대로 된다(db.upsert_port_coordinate 가
# 값이 있을 때만 저장한다).
class BoatRegistrationForm(FlaskForm):
    name = StringField('배 이름', validators=[DataRequired()])
    url = StringField('예약 페이지 URL', validators=[DataRequired(), URL()])
    city = SelectField('지역', validators=[DataRequired()], choices=[], coerce=str)
    port = StringField('항구', validators=[DataRequired(), Length(max=100)])
    lat = FloatField('위도(선택)', validators=[Optional()])
    lon = FloatField('경도(선택)', validators=[Optional()])
    note = TextAreaField('비고', validators=[Optional()])
    submit = SubmitField('등록하기')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city.choices = get_region_choices()

class BoatEditForm(FlaskForm):
    id = HiddenField('ID')
    name = StringField('배 이름', validators=[DataRequired()])
    url = StringField('예약 페이지 URL', validators=[DataRequired(), URL()])
    city = SelectField('지역', validators=[DataRequired()], choices=[], coerce=str)
    port = StringField('항구', validators=[DataRequired(), Length(max=100)])
    lat = FloatField('위도(선택)', validators=[Optional()])
    lon = FloatField('경도(선택)', validators=[Optional()])
    note = TextAreaField('비고', validators=[Optional()])
    submit = SubmitField('수정하기')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city.choices = get_region_choices()

class StatusCheckForm(FlaskForm):
    year = IntegerField('연도', validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    month = IntegerField('월', validators=[DataRequired(), NumberRange(min=1, max=12)])
    day = IntegerField('일', validators=[DataRequired(), NumberRange(min=1, max=31)])
    submit = SubmitField('조회하기')

class AdminLoginForm(FlaskForm):
    username = StringField('아이디', validators=[DataRequired()])
    password = PasswordField('비밀번호', validators=[DataRequired()])
    submit = SubmitField('로그인')