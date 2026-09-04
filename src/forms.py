from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SubmitField, SelectField, HiddenField, TextAreaField
from wtforms.validators import DataRequired, URL, NumberRange, Optional, Length
from config import CITY_PORT_MAPPING

# 지역 공용 정의 (등록/수정/조회 모두에서 활용)
REGION_CHOICES = [('', '지역을 선택하세요')] + [(city, city) for city in sorted(CITY_PORT_MAPPING.keys())]

# 항구는 city 처럼 고정 목록이 아니다 - 미리 등록되지 않은 항구도 직접 입력해서
# 등록할 수 있어야 한다(Boat.port 는 원래 자유 텍스트 컬럼). 화면에서는 select +
# "직접 입력"으로 안내하지만, 서버는 목록에 없는 값도 그대로 받는다.
class BoatRegistrationForm(FlaskForm):
    name = StringField('배 이름', validators=[DataRequired()])
    url = StringField('예약 페이지 URL', validators=[DataRequired(), URL()])
    city = SelectField('지역', validators=[DataRequired()], choices=REGION_CHOICES, coerce=str)
    port = StringField('항구', validators=[DataRequired(), Length(max=100)])
    note = TextAreaField('비고', validators=[Optional()])
    submit = SubmitField('등록하기')

class BoatEditForm(FlaskForm):
    id = HiddenField('ID')
    name = StringField('배 이름', validators=[DataRequired()])
    url = StringField('예약 페이지 URL', validators=[DataRequired(), URL()])
    city = SelectField('지역', validators=[DataRequired()], choices=REGION_CHOICES, coerce=str)
    port = StringField('항구', validators=[DataRequired(), Length(max=100)])
    note = TextAreaField('비고', validators=[Optional()])
    submit = SubmitField('수정하기')

class StatusCheckForm(FlaskForm):
    year = IntegerField('연도', validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    month = IntegerField('월', validators=[DataRequired(), NumberRange(min=1, max=12)])
    day = IntegerField('일', validators=[DataRequired(), NumberRange(min=1, max=31)])
    submit = SubmitField('조회하기')