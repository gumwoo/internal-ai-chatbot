"""D-68(P-26 C): 답 문장에 검색·확인 약속이 있는지 본다.

도구를 부르지 않고 "검색하겠습니다"로 끝낸 첫 응답을 잡는 표면 문구 규칙이다. dev·옛 holdout에서 도구 없이
끝난 답으로 만들었고, holdout2 답을 보고 조사(부터·도·먼저)와 "검색을 진행해 주세요"를 더했다(최종 측정은 새
검증셋으로 한다). 사용자에게 무언가를 요구하는 조건("알려 주시면", "원하시면")에 달린 약속과 "…해 드릴 수
있습니다" 같은 제안은 약속으로 보지 않는다(그때는 되묻기·제안이 맞을 수 있다).
"""

import re

_SENTENCE = re.compile(r"[^.!?\n]+")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|‘[^’]*’|“[^”]*”|「[^」]*」|『[^』]*』")
# 검색·조회·찾기 동사의 약속형("검색해 보겠습니다", "찾아보겠습니다", "검색 후 답변드리겠습니다")
_LOOKUP = re.compile(
    r"(?:검색|조회)(?:을|를|부터|도)?\s*(?:먼저\s*)?(?:해\s*)?(?:보겠|하겠|드리겠|진행하겠|볼게|할게)"
    r"|(?:검색|조회)하도록\s*하겠"
    r"|찾아\s*(?:보겠|드리겠|확인하겠|확인한\s*뒤|안내(?:해)?\s*드리겠|답(?:변)?\s*드리겠)|찾아보겠|찾겠"
    r"|검색해\s*확인하겠"
    r"|검색\s*(?:후|한\s*뒤|결과를\s*(?:받은|확인한|본)\s*(?:뒤|후)|결과를\s*바탕으로)[^.!?\n]*(?:답|안내)"
    # D-88: holdout7 2턴째에 도구 없이 끝난 답의 문형("검색이 필요합니다", "찾아본 뒤 답드리겠습니다",
    # "원문을 검색해 정확히 안내드리겠습니다")
    r"|검색(?:이|을)?\s*(?:먼저\s*)?필요(?:합니다|해요|하므로)"
    r"|찾아본\s*(?:뒤|후)[^.!?\n]*(?:답|안내)"
    r"|검색해\s*[^.!?\n]{0,20}(?:안내|답(?:변)?)\s*(?:해\s*)?드리겠"
)
# "확인하겠습니다"·"알아보겠습니다"는 일반 동사라 같은 문장에 규정·문서 같은 대상이 있을 때만 약속으로 본다
_CHECK = re.compile(
    r"확인(?:을)?\s*(?:해\s*)?(?:보겠|하겠|드리겠|해\s*드리겠|드리려고|볼게|할게)"
    r"|확인하도록\s*하겠|확인한\s*(?:뒤|후)\s*(?:안내|답)|알아보겠|살펴보겠"
)
# 도구를 불러야 할 자리에서 "검색을 진행해 주세요"라고 쓴 경우.
# "교육포털에서 … 검색해 주세요"·"검색창에 …"(사용자 안내)는 뺀다.
_ASK_SEARCH = re.compile(r"검색(?:을)?\s*(?:먼저\s*)?(?:진행해|해)\s*주세요")
_ELSEWHERE = re.compile(r"에서|검색창|포털|인트라넷|사이트")
_DOC = re.compile(r"규정|문서|안내|원문|자료|절차|기준|사내")
# 사용자에게 무언가를 요구하는 조건("알려 주시면", "원하신다면", "말씀해 주시는 대로")
_CONDITION = re.compile(r"(?:시면|원하면|있으면|주면|신다면|시다면|시는\s*대로)(?=[\s,]|$)")
# 앞 문장이 사용자에게 정보를 요청했거나 이 문장이 그 조건을 받는 말로 시작한다
# ("알려 주세요. 그러면 찾아보겠습니다")
_ASKS_USER = re.compile(r"(?:알려|말씀해|입력해|보내|확인해)\s*주(?:세요|시겠어요|십시오|실\s*수\s*있을까요)")
_THEN = re.compile(r"^\s*(?:그러면|그럼|그다음|그\s*후|확인되면|받으면|주시면)")
# 주어가 다른 사람·부서다("IT 지원팀이 확인해 드리겠습니다", "담당 부서에서 확인한 뒤 안내드립니다")
_OTHER_SUBJECT = re.compile(
    r"(?:팀|부서|담당자|담당|관리자|헬프데스크|센터|팀장님|선배)(?:이|가|에서|께서)\s"
)
_REPORTED = re.compile(r"^(?:다는|다고)")  # "확인하겠다는 뜻은 아닙니다"


def promises_lookup(text: str | None) -> bool:
    """답에 조건 없는 검색·확인 약속 문장이 하나라도 있으면 True."""
    text = _QUOTED.sub(" ", text or "")  # 인용한 남의 말은 약속이 아니다
    previous = ""
    for match in _SENTENCE.finditer(text):
        sentence = match.group(0)
        hit = _LOOKUP.search(sentence)
        if hit is None:
            check = _CHECK.search(sentence)
            hit = check if check and _DOC.search(sentence) else None
        if hit is None:
            ask = _ASK_SEARCH.search(sentence)
            elsewhere = ask is not None and _ELSEWHERE.search(sentence[: ask.start()])
            hit = ask if ask and not elsewhere and _DOC.search(text) else None
        if hit is not None and not (
            _CONDITION.search(sentence[: hit.start()])
            or _OTHER_SUBJECT.search(sentence[: hit.start()])
            or _REPORTED.match(sentence[hit.end() :])
            or _THEN.match(sentence)
            or _ASKS_USER.search(previous)
        ):
            return True
        previous = sentence
    return False


# D-86: 검색 없이 사건 날짜만 되묻는 답("시작일을 알려 주시면", "날짜가 필요합니다"). 날짜를 몰라도 서버가
# 판본별 원문을 주므로(D-67) 날짜 되묻기는 검색 뒤 서버가 정한다. 어떤 교육·티켓인지 묻는 말은 잡지 않는다.
_DATE_WORD = (
    r"(?:날짜|일자|언제|며칠|연도|시작일|출발일|종료일|복귀일|상신일|결재일|승인일|근무일|신청일|처리일"
    r"|발령일|지출일|사용일)"
)
_DATE_ASK = re.compile(
    _DATE_WORD + r"(?:을|를|이|가|은|는|도)?\s*(?:정확히\s*|먼저\s*|함께\s*)?"
    r"(?:알려|말씀|확인해\s*주|주시면|주셔야|필요|확인이\s*필요)"
)


def asks_for_date(text: str | None) -> bool:
    """답이 사용자에게 사건 날짜를 요청하는가."""
    return bool(_DATE_ASK.search(_QUOTED.sub(" ", text or "")))


# D-88: 이어지는 턴의 규정 질문을 검색 없이 답했는가. 사용자 메시지는 질문이고(요약·인사·감사 제외),
# 답은 규정 내용(기준·기한·승인·절차 같은 말)을 말한다.
_QUESTION = re.compile(
    r"[?？]|(?:나요|까요|죠|인가요|되나요|하나요|건가요|을까|니까|는지|은지|어때|언제|며칠|얼마|어떻게|누가|뭘|무엇|어디)"
    r"\s*[.!]?\s*$|(?:알려|말해)\s*(?:줘|주세요|주실)"
)
_NOT_LOOKUP = re.compile(r"요약|정리해\s*줘|다시\s*말해|고마|감사|알겠|수고")
_RULE_WORDS = re.compile(
    r"규정|기준|기한|영업일|승인|결재|신청|제출|한도|원칙|절차|지침|보존|등급|정산|허용|금지|예외"
)


def rule_question(message: str | None) -> bool:
    """규정을 찾아봐야 할 수 있는 질문인가(물음표·의문 어미, 요약·인사·감사 요청은 아님)."""
    text = (message or "").strip()
    return bool(_QUESTION.search(text)) and not _NOT_LOOKUP.search(text)


def discusses_rules(answer: str | None) -> bool:
    """답이 규정 내용(기준·기한·승인·절차 등)을 말하는가."""
    return bool(_RULE_WORDS.search(answer or ""))
