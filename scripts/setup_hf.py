"""Collect the user's HF token locally without echoing it or putting it in shell history."""
import getpass
import os
from pathlib import Path
from dotenv import set_key

root = Path(__file__).resolve().parents[1]
print('Community-1 모델 페이지에서 접근 조건에 동의한 계정의 Read 토큰을 입력하세요.')
token = getpass.getpass('HF 토큰 (입력 내용은 표시되지 않음): ').strip()
if not token.startswith('hf_') or any(c.isspace() for c in token):
    raise SystemExit('hf_로 시작하는 Hugging Face 토큰을 입력해 주세요. 설정을 변경하지 않았습니다.')
path = root / '.env'
fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
os.close(fd)
path.chmod(0o600)
set_key(str(path), 'HF_TOKEN', token)
path.chmod(0o600)
print('서버 전용 .env에 저장했습니다. 다른 설정은 유지했습니다.')
print('다음 명령: cd backend && uv run --extra speech python ../scripts/prepare_models.py --diarization')
