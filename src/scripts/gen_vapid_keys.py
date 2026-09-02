"""
Web Push 용 VAPID 키페어를 만든다. 한 번만 실행하면 된다.

출력된 값을 환경변수로 넣는다. 코드나 리포에 커밋하지 않는다.
  - Render 대시보드 -> Environment
  - GitHub -> Settings -> Secrets and variables -> Actions

  VAPID_PUBLIC_KEY   브라우저 구독에 쓰인다. 공개돼도 무방하다.
  VAPID_PRIVATE_KEY  서명에 쓰인다. 절대 공개하면 안 된다.
  VAPID_SUBJECT      연락처 (mailto:you@example.com)

주의: 키를 바꾸면 기존 구독이 전부 무효가 되어 사용자가 다시 구독해야 한다.
한 번 정하면 바꾸지 않는 것이 좋다.

사용법:  python src/scripts/gen_vapid_keys.py
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(raw: bytes) -> str:
    """URL-safe base64, 패딩 없음. Web Push 규격이 요구하는 형식이다."""
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def generate() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())

    # 공개키는 비압축 포인트(0x04 || X || Y) 65바이트
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    # 개인키는 32바이트 정수
    private_raw = private_key.private_numbers().private_value.to_bytes(32, 'big')

    return _b64(public_raw), _b64(private_raw)


def main() -> int:
    public, private = generate()
    print('VAPID 키페어를 생성했습니다. 아래를 환경변수로 등록하세요.')
    print('리포에 커밋하지 마세요.\n')
    print(f'VAPID_PUBLIC_KEY={public}')
    print(f'VAPID_PRIVATE_KEY={private}')
    print('VAPID_SUBJECT=mailto:your-email@example.com')
    print('\n※ 키를 바꾸면 기존 구독이 전부 무효가 됩니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
