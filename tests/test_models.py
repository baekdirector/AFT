"""
Boat 모델 테스트
"""
import pytest
from datetime import datetime


def test_boat_model_creation(app):
    """Boat 모델 인스턴스 생성 테스트"""
    from models import Boat
    
    boat = Boat(
        name='테스트선',
        url='https://example.com',
        city='인천',
        port='남항(인천항)',
        note='테스트',
        is_shared=False
    )
    
    assert boat.name == '테스트선'
    assert boat.url == 'https://example.com'
    assert boat.city == '인천'
    assert boat.is_shared == False


def test_boat_to_dict(app):
    """Boat.to_dict() 메서드 테스트"""
    from models import Boat
    
    boat = Boat(
        name='테스트선',
        url='https://example.com',
        city='인천',
        port='남항(인천항)',
        note='테스트',
        is_shared=True
    )
    
    boat_dict = boat.to_dict()
    
    assert boat_dict['name'] == '테스트선'
    assert boat_dict['url'] == 'https://example.com'
    assert boat_dict['city'] == '인천'
    assert boat_dict['port'] == '남항(인천항)'
    assert boat_dict['is_shared'] == True
    assert 'created_at' in boat_dict


def test_boat_repr(app):
    """Boat.__repr__() 메서드 테스트"""
    from models import Boat
    
    boat = Boat(
        name='테스트선',
        url='https://example.com',
        city='인천',
        port='남항(인천항)'
    )
    
    assert repr(boat) == '<Boat 테스트선>'
