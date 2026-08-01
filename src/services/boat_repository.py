"""
공통 예외 처리 패턴

데이터베이스 작업에서 반복되는 try-except 패턴을 제거합니다.
"""
from functools import wraps
from typing import Callable, TypeVar, Any
from sqlalchemy.exc import IntegrityError

F = TypeVar('F', bound=Callable[..., Any])


def handle_db_errors(func: F) -> F:
    """데이터베이스 함수의 공통 예외 처리 데코레이터
    
    사용 예:
        @handle_db_errors
        def add_boat(...):
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except IntegrityError as e:
            from db import db
            db.session.rollback()
            raise ValueError(f"데이터 무결성 오류: {str(e)}")
        except Exception as e:
            from db import db
            db.session.rollback()
            raise
    return wrapper


class BoatRepository:
    """배 관련 데이터 접근 계층 (DAO 패턴)
    
    db.py의 함수들을 클래스 메서드로 래핑하여
    일관된 예외 처리와 로깅을 제공합니다.
    """
    
    from db import db, add_boat_instance as _add_boat_raw
    from models import Boat
    
    @staticmethod
    def add(name: str, url: str, city: str, port: str, note: str = None, is_shared: bool = True) -> 'Boat':
        """배 추가 (공통 예외 처리)"""
        from db import add_boat_instance
        from sqlalchemy.exc import IntegrityError
        from db import db
        
        try:
            return add_boat_instance(name, url, city, port, note, is_shared)
        except IntegrityError:
            db.session.rollback()
            raise ValueError(f"'{name}' 배는 이미 등록되어 있습니다.")
        except Exception as e:
            db.session.rollback()
            raise ValueError(f"배 등록 중 오류 발생: {str(e)}")
    
    @staticmethod
    def get_all() -> list:
        """모든 배 조회"""
        from db import get_all_boats
        try:
            return get_all_boats()
        except Exception as e:
            raise ValueError(f"배 목록 조회 중 오류 발생: {str(e)}")
    
    @staticmethod
    def get_by_id(boat_id: int):
        """ID로 배 조회"""
        from db import get_boat_by_id
        try:
            boat = get_boat_by_id(boat_id)
            if not boat:
                raise ValueError(f"ID {boat_id}인 배를 찾을 수 없습니다.")
            return boat
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"배 조회 중 오류 발생: {str(e)}")
    
    @staticmethod
    def update(boat_id: int, name: str, url: str, city: str, port: str, note: str = None):
        """배 정보 수정 (공통 예외 처리)"""
        from db import update_boat
        from db import db
        from sqlalchemy.exc import IntegrityError
        
        try:
            boat = update_boat(boat_id, name, url, city, port, note)
            if not boat:
                raise ValueError(f"ID {boat_id}인 배를 찾을 수 없습니다.")
            return boat
        except IntegrityError:
            db.session.rollback()
            raise ValueError(f"'{name}' 배는 이미 등록되어 있습니다.")
        except ValueError:
            raise
        except Exception as e:
            db.session.rollback()
            raise ValueError(f"배 수정 중 오류 발생: {str(e)}")
    
    @staticmethod
    def delete(boat_id: int) -> None:
        """배 삭제 (공통 예외 처리)"""
        from db import delete_boat
        from db import db
        
        try:
            delete_boat(boat_id)
        except ValueError:
            raise
        except Exception as e:
            db.session.rollback()
            raise ValueError(f"배 삭제 중 오류 발생: {str(e)}")
