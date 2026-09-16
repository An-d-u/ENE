# ENE 동반 앱 미디어 확장 계약 V1

기본 [텍스트·TLS 계약](protocol.md)에 추가하는 선택적 미디어 계약이다. 양쪽 저장소의 이 문서와 `media_cases.json`은 동일한 바이트로 관리한다.

구현 단계: B1은 해석기와 순수 협상/세대 검증만 제공한다. 실제 음성·캐릭터 모듈이 연결되기 전에는 hello/ready에서 능력을 광고하지 않는다. 구형 대화·TLS 계약과 기존 `cases.json`은 유지한다. 아래 HTTP·출력·캐릭터 규칙의 실제 연결과 검증은 후속 B/C/D 작업에서 수행한다.

유효한 구조라는 이유만으로 실행 권한을 부여하지 않는다. 수신 경계는 협상·방향·등록/서버/연결을 다시 확인하고, 음성 조정기는 공개 메시지/작업/발화 참조 및 offer의 실제 sample rate를 확인한다. 구조 검사에서는 프레임 상한을 최대 rate로 제한하고, 실행 검사에서 해당 rate의 4초/180초 상한으로 좁힌다. 모델/매개변수/표정 ID의 현재 카탈로그 일치는 각 PC 조정기가 확인한다.

`character_changed.model_version`의 null은 생략할 수 없는 ‘모델 없음’ 표시다. `extension_error.command_id`는 선택 필드다. 기존 최상위 미지 필드는 제거하지만 수신 원문의 크기는 제거 전에 검사한다. 확장 필드에서 대화의 event_seq/revision을 받거나 증가시키지 않는다.

## 3. 구현할 계약

### 3.1 공통 봉투와 협상

기존 `hello.capabilities`와 `ready.capabilities`는 교집합을 사용한다. `character_controls_v1`은 `character_v1`도 있을 때만 유효하다. 모듈이 실제 연결되기 전에는 능력을 광고하지 않는다. 구형 앱/PC에는 새로운 message type을 보내지 않는다.

확장 능력이 하나라도 있으면 ready 다음에 `extensions_ready`를 보내며 기존 ready의 필수 필드를 바꾸지 않는다. 확장 봉투 `X`는 `protocol_version=1`, `type`, `registration_generation`(양의 안전 정수), `server_epoch`(UUID), `connection_generation`(UUID)다. gateway_generation은 PC 내부 AdmissionContext로 추가 검증한다. 연결 식별자를 URL에 넣지 않는다. 미협상 확장·다른 세대는 실행하지 않으며 base 대화 `event_seq`와 revision을 변경하지 않는다.

UUID는 기존 계약 검사기를 재사용하고 숫자는 boolean과 구분한다. 문자열은 UTF-8·surrogate·깊이 제한을 유지한다. 고정 오류 코드는 64자 이내다. 알 수 없는 최상위 필드는 기존 허용 목록으로 제거하되, 설정 patch의 알 수 없는 키는 전체 거절한다.

| 메시지 | 방향 | X 이외 필수 필드 |
| --- | --- | --- |
| `extensions_ready` | PC→APP | `capabilities`(최대 3개) |
| `audio_availability` | APP→PC | `available`(bool), `conversation_id`, `reason`(고정 코드) |
| `audio_status` | PC→APP | `mode`(`disabled/pc_only/auto`), `reason` |
| `audio_offer` | PC→APP | `conversation_id`, `message_id`, `operation_id`, `utterance_id`(모두 UUID), `sample_rate`, `channels`, `sample_width=2`, `prepare_timeout_ms=2000` |
| `audio_prepared` | APP→PC | 위 4개 참조 ID, `buffered_frames`(0~rate×4) |
| `audio_rejected` | APP→PC | 위 참조 ID, `reason` |
| `audio_start` | PC→APP | 위 참조 ID; 재생 허가가 아닌 다른 메시지로 시작하지 않음 |
| `audio_started` | APP→PC | 위 참조 ID, `played_frames=0` |
| `audio_source_end` | PC→APP | 위 참조 ID, `total_frames`(0~rate×180) |
| `audio_progress` | APP→PC | 위 참조 ID, `played_frames`, `mouth_open`(유한 0~1) |
| `audio_progress_ack` | PC→APP | 위 참조 ID, 수락한 `played_frames`; APP의 반쪽 제어 단절 감지에 사용 |
| `audio_finished` | APP→PC | 위 참조 ID, `played_frames` |
| `audio_cancel` | 양방향 | 위 참조 ID, `reason` |
| `character_changed` | PC→APP | `state_revision`(양수), `model_version`(SHA-256 또는 null), `reason` |
| `character_snapshot_request` | APP→PC | 추가 필드 없음; 합쳐서 요청하며 동시 1개 |
| `character_action` | PC→APP | `action_seq`(단조 증가), `model_version`, `kind`(`expression/gesture`), `action_id`(공개 허용 ID), `duration_ms`(0~30000) |
| `character_playback` | PC→APP | `conversation_id`, `message_id`, `utterance_id`, `output`(`pc/phone/none`), `played_ms`(0~180000), `mouth_open`, `active`(bool) |
| `head_pat` | APP→PC | `model_version`, `interaction_id`(UUID), `interaction_no`(단조 증가), `seq`, `phase`(`start/update/end/cancel`), `intensity`(0~1) |
| `head_pat_state` | PC→APP | 같은 세션/모델/순서 필드, `source`(`pc/phone`), `phase`(`accepted/update/ended/cancelled/rejected`), `intensity`, `reason` |
| `character_settings_patch` | APP→PC | `model_version`, `command_id`(UUID), `expected_revision`, `changes`(아래 허용 키), `parameters`(ID→수치/null; null은 보정 삭제) |
| `character_settings_result` | PC→APP | `command_id`, `status`(`accepted/conflict/rejected`), `settings_revision`, `reason` |
| `extension_error` | PC→APP | `feature`(협상된 능력), `code`, 선택적 `command_id`; 채팅의 치명적 `error`와 구분 |

음성 참조 묶음은 `AudioRef`로 운반한다. `operation_id`는 PC가 실제 내부 작업 ID와 맵핑하는 공개 UUID이며 최신 전역 요청에서 재구성하지 않는다. 처리 예외의 원문·파일 경로·토큰은 봉투에 넣지 않는다. 제어 메시지 총 64KiB, 진행/입력 갱신은 2KiB 이하, settings patch는 48KiB 이하·보정 256개로 제한한다.

### 3.2 HTTPS와 캐릭터 스냅샷

모든 경로는 `Authorization: Bearer ...`, `X-ENE-Connection`에 현재 연결 UUID를 요구한다. 기존 TLS 검증을 재사용하고 `Cache-Control: no-store`, 압축 없음, query/Origin/Range/redirect 거절을 적용한다. 인증 401, 구연결/없는 자산 404, 정책 위반 400, 제한 429, 취소된 음성 410을 사용하고 고정 코드만 반환한다.

- `GET /companion/v1/audio/{utterance_id}`: `Content-Type: application/octet-stream`, `X-ENE-Audio-Format: pcm_s16le`, `X-ENE-Sample-Rate`, `X-ENE-Channels`. 프레임 정렬된 PCM만 읽고 offer와 헤더 일치를 검사한다. HTTP 종료와 `audio_source_end.total_frames`가 모두 일치해야 정상 종료다. 동시 1개·음성 ID당 최초 소비 1회; 재접속·Range 재생 없음.
- `GET /companion/v1/character/manifest`: 스냅샷 `{model_id, model_version, runtime_version, state_revision, settings_revision, action_seq, settings, parameters, parameter_catalog, expression_ids, gesture_ids, default_expression, assets, entry_asset_id, status}`. `action_seq`는 캡처 시점의 마지막 일회성 사건 번호다. 미지원/모델 없음은 `status`와 빈 목록, null 모델 ID로 표현한다. 전체 256KiB.
- `assets` 원소는 `{id, sha256, size, mime}`. `parameter_catalog`는 최대 256개 `{id,min,max,default}`이고 표시 문자열도 길이 128 이내다. 순서 변화가 버전을 바꾸지 않도록 정렬한다. 모델 경로나 표시 이름은 포함하지 않는다.
- `GET /companion/v1/character/assets/{asset_id}`: 현재 manifest에 있는 자산만 제공한다. 자산 ID는 원본 바이트 SHA-256, 전달 해시는 안전한 참조로 변환한 뒤 계산한다. JSON 내 파일 참조는 같은 자산 묶음의 ID 상대 경로로 바꾸고 원래 파일명을 보내지 않는다. 지원하지 않는 선택적 Sound 참조는 제거하고 그 음향 파일은 전달하지 않는다.

모델 버전은 변환된 manifest의 불변 자산 목록과 실행부 버전의 해시다. 동일 바이트/실행부는 서버 재시작 후에도 같은 버전을 유지한다. 조회 중 현재 버전이 바뀌면 다운로드를 취소하고 새 manifest로 시작한다. 프리뷰/서버별 자산을 섞지 않는다. 파일 변경 경합에 대비해 파일 핸들과 메타데이터를 확인하고 실제 전달 바이트의 해시를 검증한다. 검증 중 변경되면 제공하지 않는다.

한 연결의 HTTP는 음성 1개+자산 2개+manifest 1개 이내다. 인증 이후 데이터 요청 제한은 초당 8개·버스트 16개, 제어 확장 제한은 초당 30개·버스트 60개다. 대화 전송 제한과 분리한다. asset 읽기 유휴 10초·총 60초, 전체 모델 받기 5분 한도다. 미인증 경로는 기존 preauth 제한을 적용한다.

### 3.3 수치·상태 규칙

| 경계 | 고정 값 |
| --- | --- |
| 음성 | PCM16LE, 채널 1/2, rate 8000~48000, 조각 최대 32768바이트, 180초·36MiB 이하 |
| 전송 메모리 | 각 PC/APP의 새 전송 대기 버퍼 합계 `min(rate×channels×2×4, 1MiB)`; 중복 prefix도 합산 |
| 음성 준비 | 200ms 또는 EOF인 더 짧은 전체 음성, PC 제안 2초, APP 준비 후 허가 3초 |
| 진행 | 실제 위치 조회 50ms, 전송 100~500ms 간격, 보고 누락 또는 위치 정지 5초면 취소 |
| 반대편 입 모양 | 최대 10Hz, 마지막 갱신 750ms 초과면 입을 닫음 |
| 모델 | 파일 256개, 합계 128MiB, 한 파일 32MiB, 텍스처 한 변 8192px, manifest 256KiB |
| 캐시 | 서버 신원별, 앱 전체 256MiB·최대 두 버전, 준비 중 파일도 합산, 백업 제외 |
| 입력 | 쓰다듬기 갱신 10Hz 이하, 유휴 2초, 완료 ID 256개+연결별 최대 수락 번호 |

PC에 이미 완성된 WAV가 있는 경우 원본 immutable bytes 한 개를 최대 36MiB까지 참조하고, 네트워크 쓰기는 소비 속도에 맞춰 조각 단위로 수행한다. 완성 음성 전체를 4초 큐에 한 번에 넣지 않는다. 생성 중 스트림은 작은 prefix를 보존하되 PC 전환 전 포화가 임박하면 폰 제안을 취소하고 그 prefix부터 PC sink로 한 번만 전달한다. 폰 확정 이후 포화는 취소이며 동일 발화를 PC에서 재생하지 않는다.

출력 상태는 `PC`, `OFFERED`, `PHONE_COMMITTED`, `PLAYING`, `DONE`이다. `PHONE_COMMITTED`는 start를 socket에 넘기기 전에 Qt에서 기록한다. `send` 결과 유실/실패 후 PC로 되돌리지 않는다. 진행 watchdog은 PC/APP 모두 단조 시계를 사용한다. APP은 100~500ms 간격으로 보낸 progress에 대한 ACK가 5초 동안 없으면 중단한다. 기본 heartbeat의 nonce나 주기를 바꾸지 않는다.

공통 설정의 `settings_revision`과 캐릭터 `state_revision`을 분리한다. 모바일 patch는 오래된 settings_revision이면 항상 충돌이다. PC 설정 창은 열 때 baseline과 수정 키를 보관하고 키별 마지막 변경 revision으로 검증한다. 겹치지 않는 수정은 최신 상태에 병합하되 겹치는 키가 외부에서 바뀌었으면 저장하지 않고 갱신한다. 제스처/표정이 바뀌었다는 이유로 설정 저장을 거절하지 않는다.


## 설정 변경의 구문 허용 목록

불리언: `enable_builtin_idle_motion`, `enable_auto_eye_blink`, `enable_idle_motion`, `enable_expressive_motion`, `enable_expressive_pose_transitions`, `enable_idle_synthetic_gestures`, `enable_head_pat`.

수치: `idle_motion_strength` 0.2~2.0, `idle_motion_speed` 0.5~2.0, `expressive_motion_strength` 0.2~2.5, `expressive_motion_speed` 0.4~2.0, `expressive_motion_speech_boost` 0~2.5, `synthetic_gesture_scale` 0.5~3.0, `head_pat_strength` 0.5~2.5.

정수: `head_pat_fade_in_ms` 50~1000, `head_pat_fade_out_ms` 50~1200, `head_pat_end_emotion_duration_sec` 1~30.

문자열: `idle_synthetic_gesture_frequency`는 low/normal/high. `head_pat_active_emotion_custom`, `head_pat_end_emotion_custom`은 현재 표정 ID 또는 빈 문자열이며 UTF-8 128바이트 이하다. 행동/매개변수 ID도 UTF-8 128바이트 이하다.

`parameters`는 최대 256개 ID→유한 수치/null이다. 현재 모델의 min/max 검사는 저장 조정기가 수행한다. 알 수 없는 changes 키는 전체 거절한다.

## 개발 검증 참고

Kotlin의 sealed 메시지 직렬화 방식은 [공식 다형성 직렬화 문서](https://kotlinlang.org/docs/serialization-polymorphism.html)를 따른다. 증분 컴파일의 내부 오류가 있을 때는 의존성이나 코드를 임의 변경하기 전에 `'-Pkotlin.incremental=false'`를 인자로 준 재컴파일로 구분한다. 이 확인은 설치·실기기·음성 출력 성공을 뜻하지 않는다.
