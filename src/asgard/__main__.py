# `python -m asgard` entry — the fast, freeze-free path used by smoke tests and dev.
# `app`이 아니라 `main`을 부른다: 스튜디오가 띄우는 자식 프로세스가 이 문으로 들어오므로,
# 아는 실패가 트레이스백 대신 사유·처방·종료 코드로 나가는 자리도 여기여야 한다.
from .cli import main

if __name__ == "__main__":
    main()
