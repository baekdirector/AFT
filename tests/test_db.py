"""
데이터베이스 함수 테스트
"""
import pytest


def test_add_boat_instance(app):
    """add_boat_instance 함수 테스트"""
    from db import add_boat_instance, get_all_boats
    
    with app.app_context():
        boat = add_boat_instance(
            name='테스트선',
            url='https://example.com',
            city='인천',
            port='남항(인천항)',
            note='테스트',
            is_shared=False
        )
        
        assert boat.name == '테스트선'
        assert boat.url == 'https://example.com'
        assert boat.id is not None
        
        # 실제로 저장되었는지 확인
        all_boats = get_all_boats()
        assert len(all_boats) >= 1


def test_add_boat_duplicate_name_fails(app):
    """같은 이름의 배 중복 등록 시 실패 테스트"""
    from db import add_boat_instance
    
    with app.app_context():
        add_boat_instance(
            name='테스트선',
            url='https://example.com',
            city='인천',
            port='남항(인천항)'
        )
        
        # 같은 이름으로 다시 등록하면 오류 발생
        with pytest.raises(Exception):
            add_boat_instance(
                name='테스트선',
                url='https://example2.com',
                city='안산',
                port='오이도항'
            )


def test_get_boat_by_id(app):
    """get_boat_by_id 함수 테스트"""
    from db import add_boat_instance, get_boat_by_id
    
    with app.app_context():
        added_boat = add_boat_instance(
            name='테스트선',
            url='https://example.com',
            city='인천',
            port='남항(인천항)'
        )
        
        retrieved_boat = get_boat_by_id(added_boat.id)
        
        assert retrieved_boat is not None
        assert retrieved_boat.name == '테스트선'
        assert retrieved_boat.id == added_boat.id


def test_update_boat(app):
    """update_boat 함수 테스트"""
    from db import add_boat_instance, update_boat, get_boat_by_id
    
    with app.app_context():
        added_boat = add_boat_instance(
            name='테스트선',
            url='https://example.com',
            city='인천',
            port='남항(인천항)',
            note='원래 노트'
        )
        
        updated_boat = update_boat(
            added_boat.id,
            name='수정된선',
            url='https://updated.com',
            city='안산',
            port='오이도항',
            note='수정된 노트'
        )
        
        assert updated_boat.name == '수정된선'
        assert updated_boat.url == 'https://updated.com'
        assert updated_boat.city == '안산'
        assert updated_boat.note == '수정된 노트'


def test_delete_boat(app):
    """delete_boat 함수 테스트"""
    from db import add_boat_instance, delete_boat, get_boat_by_id
    
    with app.app_context():
        added_boat = add_boat_instance(
            name='테스트선',
            url='https://example.com',
            city='인천',
            port='남항(인천항)'
        )
        
        boat_id = added_boat.id
        delete_boat(boat_id)
        
        # 삭제 후 조회하면 None
        deleted_boat = get_boat_by_id(boat_id)
        assert deleted_boat is None


def test_delete_nonexistent_boat_fails(app):
    """존재하지 않는 배 삭제 시 실패 테스트"""
    from db import delete_boat
    
    with app.app_context():
        with pytest.raises(ValueError, match='등록된 배를 찾을 수 없습니다'):
            delete_boat(999)
