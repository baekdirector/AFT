"""
API 응답 표준화

일관된 응답 포맷을 제공합니다.
"""
from typing import Any, Dict, Optional


def success_response(data: Any = None, message: Optional[str] = None) -> Dict:
    """성공 응답 생성"""
    result: Dict[str, Any] = {'status': 'success'}
    if data is not None:
        result['data'] = data
    if message:
        result['message'] = message
    return result


def error_response(error: str, error_code: str = "ERROR", message: Optional[str] = None) -> Dict:
    """에러 응답 생성"""
    result: Dict[str, Any] = {'status': 'error'}
    if error:
        result['error'] = error
    if error_code:
        result['error_code'] = error_code
    if message:
        result['message'] = message
    return result


def validation_error_response(error: str, message: Optional[str] = None) -> Dict:
    """검증 에러 응답 생성"""
    return error_response(error=error, error_code='VALIDATION_ERROR', message=message)
