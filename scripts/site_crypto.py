"""정적 사이트 콘텐츠를 passphrase 기반 AES-GCM으로 암호화.

서버가 없는 정적 호스팅(Vercel 등)이라 진짜 로그인은 못 만든다. 대신 콘텐츠
자체를 브라우저에서 passphrase로만 풀리는 암호문으로 구워서 배포한다 -
passphrase를 모르면 view-source를 봐도 평문이 나오지 않는다 (검색엔진 크롤러도 당연히 못 읽음).

passphrase를 바꾸고 싶으면 아래 PASSPHRASE만 수정하고 build_site.py를 다시 돌리면 된다.
"""
import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PASSPHRASE = "mapp-digest-2026"  # 바꾸고 싶으면 여기만 수정 후 build_site.py 재실행
PBKDF2_ITERATIONS = 100_000


def encrypt_json(obj, passphrase: str = PASSPHRASE) -> dict:
    """JS 쪽 Web Crypto(PBKDF2+AES-GCM)와 1:1 호환되는 포맷으로 암호화."""
    plaintext = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS
    ).derive(passphrase.encode("utf-8"))
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "ct": base64.b64encode(ciphertext).decode(),
    }
