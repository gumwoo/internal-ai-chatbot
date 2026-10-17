"""근거 예산용 token 추정(공통 규칙). 실제 tokenizer가 아니라 추정값이다.

규칙: UTF-8 바이트 수 / 3(올림). 한국어 한 글자는 3바이트다. 같은 규칙을 저장(MOD-05)·예산 조립(MOD-02)에
함께 써서 A/B·설정 사이에 같은 척도를 쓴다. 실제 모델 token과의 차이는 측정해 따로 기록한다(TOKEN_ESTIMATOR).
"""

TOKEN_ESTIMATOR = "utf8-bytes-div3-v1"  # noqa: S105 - 비밀값이 아니라 추정 규칙 이름


def estimate_tokens(text: str) -> int:
    return -(-len(text.encode("utf-8")) // 3)
