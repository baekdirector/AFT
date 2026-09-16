"""
api_response 헬퍼 함수 테스트

예전엔 (미사용) ApiResponseBuilder/ApiResponse/ResponseStatus를 같이
검증하는 test_medium_refactoring.py::TestApiResponse에 섞여 있었다 - 그
클래스들은 프로덕션 호출부가 없어 삭제했고(views.py 전 라우트는 아래
헬퍼 함수만 쓴다), 실제로 쓰이는 함수만 남겨 이 파일로 옮겼다.
"""
from services.api_response import success_response, error_response


def test_success_response_function():
    """헬퍼 함수 - 성공"""
    result = success_response(data=[1, 2], message='OK')

    assert result['status'] == 'success'
    assert result['data'] == [1, 2]
    assert result['message'] == 'OK'


def test_error_response_function():
    """헬퍼 함수 - 에러"""
    result = error_response(
        error='Something went wrong',
        error_code='INTERNAL_ERROR'
    )

    assert result['status'] == 'error'
    assert result['error'] == 'Something went wrong'
    assert result['error_code'] == 'INTERNAL_ERROR'
