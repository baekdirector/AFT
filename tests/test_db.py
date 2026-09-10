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


def test_add_boat_same_name_and_url_fails(app):
    """같은 이름 + 같은 URL로 중복 등록하면 실패한다(진짜 중복 등록)."""
    from db import add_boat_instance

    with app.app_context():
        add_boat_instance(
            name='테스트선',
            url='https://example.com',
            city='인천',
            port='남항(인천항)'
        )

        with pytest.raises(Exception):
            add_boat_instance(
                name='테스트선',
                url='https://example.com',
                city='안산',
                port='오이도항'
            )


def test_add_boat_same_name_different_url_succeeds(app):
    """이름은 같지만 URL(예약 사이트)이 다르면 서로 다른 실제 배로 보고 둘 다
    등록할 수 있어야 한다 - 실측: "빅보스호"가 여수/화성 두 곳에 서로 다른
    배로 각각 존재해 등록이 막혔던 버그(name 단독 유니크 제약)를 고친 것.
    (실제 배 이름 대신 합성 이름을 쓴다 - boat_list.xlsx 시드 데이터에 이미
    "빅보스호"가 있어 그 이름을 쓰면 시드 항목까지 섞여 개수 비교가 깨진다.)"""
    from db import add_boat_instance, get_all_boats

    with app.app_context():
        add_boat_instance(
            name='동명이배호',
            url='https://example-a.sunsang24.com/ship/schedule_fleet',
            city='화성',
            port='전곡항'
        )
        add_boat_instance(
            name='동명이배호',
            url='https://example-b.sunsang24.com/ship/schedule_fleet',
            city='여수',
            port='종포항'
        )

        names = [b.name for b in get_all_boats() if b.name == '동명이배호']
        assert len(names) == 2


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
