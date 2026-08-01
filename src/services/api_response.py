"""
API 응답 표준화

일관된 응답 포맷을 제공합니다.
"""
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum


class ResponseStatus(Enum):
    """API 응답 상태"""
    SUCCESS = "success"
    ERROR = "error"
    VALIDATION_ERROR = "validation_error"


@dataclass
class ApiResponse:
    """표준 API 응답 포맷
    
    Example:
        >>> response = ApiResponse(status=ResponseStatus.SUCCESS, data=[...])
        >>> response.to_json()
        {'status': 'success', 'data': [...]}
    """
    status: ResponseStatus
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """딕셔너리로 변환"""
        result = {
            'status': self.status.value,
        }
        if self.data is not None:
            result['data'] = self.data
        if self.error:
            result['error'] = self.error
        if self.error_code:
            result['error_code'] = self.error_code
        if self.message:
            result['message'] = self.message
        return result
    
    def to_json(self) -> str:
        """JSON 문자열로 변환"""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)


class ApiResponseBuilder:
    """API 응답 빌더 (Fluent API)
    
    Example:
        >>> (ApiResponseBuilder()
        ...     .success(data=[1, 2, 3])
        ...     .build())
    """
    
    def __init__(self):
        self._status = ResponseStatus.SUCCESS
        self._data = None
        self._error = None
        self._error_code = None
        self._message = None
    
    def success(self, data: Any = None, message: str = None) -> 'ApiResponseBuilder':
        """성공 응답"""
        self._status = ResponseStatus.SUCCESS
        self._data = data
        self._message = message
        return self
    
    def error(self, error: str, error_code: str = "UNKNOWN_ERROR", message: str = None) -> 'ApiResponseBuilder':
        """에러 응답"""
        self._status = ResponseStatus.ERROR
        self._error = error
        self._error_code = error_code
        self._message = message
        return self
    
    def validation_error(self, error: str, message: str = None) -> 'ApiResponseBuilder':
        """검증 에러 응답"""
        self._status = ResponseStatus.VALIDATION_ERROR
        self._error = error
        self._error_code = "VALIDATION_ERROR"
        self._message = message
        return self
    
    def build(self) -> ApiResponse:
        """응답 객체 생성"""
        return ApiResponse(
            status=self._status,
            data=self._data,
            error=self._error,
            error_code=self._error_code,
            message=self._message
        )


def success_response(data: Any = None, message: str = None) -> Dict:
    """성공 응답 생성"""
    return ApiResponseBuilder().success(data=data, message=message).build().to_dict()


def error_response(error: str, error_code: str = "ERROR", message: str = None) -> Dict:
    """에러 응답 생성"""
    return ApiResponseBuilder().error(error=error, error_code=error_code, message=message).build().to_dict()


def validation_error_response(error: str, message: str = None) -> Dict:
    """검증 에러 응답 생성"""
    return ApiResponseBuilder().validation_error(error=error, message=message).build().to_dict()
