# prepare 입력 출처 계약

## 제안에서 검증까지

CT-06 ToolCallProposal=`name,arguments,provider_call_id,origin_candidates?`. prepare_it_ticket의 논리 입력은 `fields,origin_candidates,execution_context,call_ordinal`이다. origin_candidates는 신뢰되지 않는 제안이며 actor/run/승인 정보를 포함할 수 없다. 준비 도구의 자유문장이 있으면 해당 필드의 후보가 필수다. 공급자 도구 인자 안의 origin_candidates는 MOD-07이 CT-06의 별도 origin_candidates로 정규화하고 arguments에는 업무 fields만 남긴다. MOD-02는 모델에 제공한 허용 user 원문에 message_id를 표시한다. MOD-02가 계산한 정규 field_origins는 CT-06 ToolExecutionInput.field_origins로 MOD-03에 넘어가고, MOD-03은 이를 PrepareTicket 입력으로 MOD-12에 전달한다. 모델의 임의 field_origins 완성본을 신뢰하지 않는다. "run 문맥"의 user 메시지는 해당 run의 CT-03 snapshot에 포함된 본인 user 메시지와 수락한 질문이며 CP-07이 그 집합만 읽는다.

후보 user_quote=`field,kind=user_quote,message_id,quote`. MOD-02가 CP-07의 현재 소유/run 문맥 user 원문을 읽고 **Unicode code point 기준 시작 포함/끝 제외 구간을 계산**한다. JavaScript UTF-16 인덱스를 그대로 쓰지 않는다. quote가 정확히 한 번 일치할 때만 span을 생성하며 미일치/반복 모호성은 추가 확인한다. 모델은 quote/message_id를 제안할 수 있지만 span의 계산·채택 주체가 아니다.

정규 field_origins=`field,kind,source_message_id,span_start,span_end,normalization,template_id?`. normalization 닫힌 값은 identity/trim/iso_kst_datetime/canonical_category/user_boolean이다. 자유문장은 identity/trim만 허용한다. 원문은 수정하지 않고 변환 결과를 따로 기록한다. MOD-12는 CP-07로 같은 user 원문을 읽어 span과 변환 결과를 재검증한다. 권한·소유권·실제 값 일치를 모두 확인하며 assistant/PDF/Wiki/도구 로그를 user 원문으로 인정하지 않는다.

## 서버 고정 템플릿과 직접 입력

초기 허용 registry는 `ticket.subject.generic.v1` 하나이며 literal은 `IT 지원 요청`, 적용 필드는 subject만이다. 설명/발생 시각/영향/긴급 여부/자산번호를 채우는 템플릿은 없다. registry 변경은 계약 revision과 검토가 필요하다. 모델 후보는 template_id만 제안하고 서버가 literal·필드 범위를 결정한다. 모델이 임의 template 본문을 보내도 사용하지 않는다.

UI revise는 세션/CSRF/소유권을 통과한 직접 입력을 `kind=user_input`으로 서버가 기록한다. 프로필 회신 수단은 MOD-09의 현재 프로필에서 얻는 서버 필드로 자유문장 template과 다르다. 변경 전 payload와 새 값의 출처를 감사에 남기며 빈 필드를 추정해 채우지 않는다.

## 검증 사례

이모지 앞/뒤 한국어 quote의 code point offset, repeated quote 거절, 다른 대화 message_id 거절, 허용 밖 normalization/template 거절, 검색 원문 복사 거절, UI 직접 입력 감사. T-31 범위이며 아직 서버 검증을 구현한 것은 아니다.
