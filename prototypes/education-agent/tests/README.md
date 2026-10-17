# 정적 시안 회귀 테스트

백엔드·실제 LLM/검색/인증·DB 동시성 테스트가 아니다. 시안의 날짜 재질문, 입력 보존, 초안/재준비/확인, 예외 상태, DOM escape, 모바일 포커스를 실제 Chromium으로 확인한다.

1. 저장소 루트에서 `python -m http.server 8787 --bind 127.0.0.1` 실행(기존 서버가 있으면 재사용).
2. **먼저 결과 경로를 명시한다.** PowerShell 예: `$env:PROTOTYPE_RESULTS_DIR=Join-Path ([System.IO.Path]::GetTempPath()) ("llm-api-review-"+[guid]::NewGuid().ToString("N"))`. 스크립트가 절대 출력 경로를 표시하며 미설정 시 실행을 거절한다. 기존54개 보고서를 덮어쓰지 않는다.
3. Playwright가 설치된 Node 환경에서 `node prototypes/education-agent/tests/browser-flows.cjs` 실행. 일반 설치는 `npm install --no-save playwright`와 `npx playwright install chromium`이다.
4. 설치된 Chrome을 사용하면 PowerShell에서 `$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Program Files/Google/Chrome/Application/chrome.exe'`로 지정한다. 별도 Node 라이브러리 경로는 NODE_PATH로 지정할 수 있다. URL 변경은 PROTOTYPE_URL을 사용한다.
5. 저장소 루트에서 `python -B scripts/check_specs.py`로 문서 링크/JSON/계약 필드·PDF 해시 목록을 확인한다.

브라우저 결과는 지정한 경로의 `third-review-browser-results.json`과 `third-review-*.png`다. 문서 검사도 SPEC_RESULTS_DIR 지정 시 해당 경로를 사용한다. 기존 state-contract 결과는 과거 검증 이력이다. 스크립트 실패는 nonzero exit이며 성공 보고서를 새로 생성하지 않는다. 시간/폼/세션 오류는 `?qa=1`에서만 제공되는 prototypeQA 고정 fixture를 사용한다. 일반 직원 URL에는 상태 선택 메뉴나 QA hook이 없다. 실제 인증/응답 유실을 시안 fixture 통과로 입증하지 않는다.

3차 회귀는 금액/판본·선택 날짜·head ID/payload·실제 action 상태·입력값·포커스를 단언한다. 사례 개수 통과가 임의 자연어 전체의 정확성을 보장하지 않는다.
