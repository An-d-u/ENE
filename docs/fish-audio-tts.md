# Fish Audio 음성 설정

ENE의 **설정 → TTS 설정**에서 공급자를 **Fish Audio**로 선택하면 바로 아래에 API 키 입력칸과 모델·음성 설정이 나타납니다. 다른 공급자로 바꾸면 해당 입력칸이 숨겨집니다.

## 연결 방법

1. **TTS 활성화**를 켜고 공급자에서 **Fish Audio**를 선택합니다.
2. [Fish Audio API 키 페이지](https://fish.audio/app/api-keys/)에서 발급받은 키를 **API 키** 칸에 입력합니다. 기본적으로 내용이 가려지며 표시 버튼으로 확인할 수 있습니다.
3. **API URL**은 기본값인 `https://api.fish.audio/v1`을 사용합니다.
4. **모델**을 선택합니다. 기본값은 `s2.1-pro`이며 `s2.1-pro-free`, `s2-pro`, `s1`도 선택할 수 있습니다. `s2.1-pro-free`는 무료 개발자용 모델입니다. 모델 이용 조건과 API 크레딧은 Fish Audio에서 확인하세요.
5. 원하는 목소리가 있다면 Fish Audio 음성 페이지에서 복사한 **음성 ID**를 입력합니다. 전체 페이지 주소가 아닌 ID를 넣습니다. 빈칸이면 서비스의 기본 음성을 사용합니다.
6. **속도**를 설정합니다. `1.00`이 기본값이며 `0.50`~`2.00` 범위를 지원합니다.
7. **읽기 언어**, 하단 **출력 장치·볼륨**을 확인하고 설정을 저장합니다. 한국어로 읽으려면 읽기 언어를 한국어 또는 응답 언어와 같게 설정합니다.

다시 설정 창을 열면 선택한 공급자, 키, 모델, 음성 ID와 속도를 불러옵니다. 공급자를 잠시 바꾸어도 Fish Audio 설정은 유지됩니다.

## 저장과 재생

- 일반 설정은 `tts_provider_configs.fish_audio`에 저장합니다.
- API 키는 기존 비밀 설정 파일의 `tts_api_keys.fish_audio`에 분리 저장하며 일반 설정 파일에는 넣지 않습니다. 화면 마스킹과 분리 저장은 파일 암호화를 의미하지 않습니다.
- 기존 비밀 설정 파일은 버전 관리에서 제외됩니다. 실제 API 키나 생성 음성, 합성 원문을 테스트·문서·커밋에 넣지 않습니다.
- Fish Audio의 PCM 응답을 44.1kHz·16비트·모노 WAV로 변환해 기존 오디오 플레이어와 립싱크 분석에 전달합니다.
- 이번 연결은 전체 음성 생성 후 재생하는 방식입니다. 기존 **GPT-SoVITS 스트리밍 TTS 사용** 옵션은 Fish Audio에 적용되지 않습니다.

## 오류 안내

아래 표는 Fish Audio 클라이언트의 오류 분류와 확인 사항입니다. 현재 앱은 기존 공통 음성 합성 실패 처리 경로를 사용하므로, 개별 오류 문구가 화면에 표시되지는 않습니다.

| 안내 | 확인할 사항 |
| --- | --- |
| API 키 누락 또는 401 | TTS 설정에 키를 입력했는지, 유효한 키인지 확인합니다. |
| 402 | API 크레딧과 선택한 모델의 이용 조건을 확인합니다. |
| 403 | API 키 또는 음성 모델의 접근 권한을 확인합니다. |
| 404·422 | API URL, 음성 ID와 모델 설정을 확인합니다. |
| 429 | 요청 한도에 도달했으므로 잠시 후 다시 시도합니다. |
| 연결 실패·시간 초과·서버 오류 | 네트워크와 Fish Audio 서비스 상태를 확인합니다. |

오류 안내에는 서버 응답 원문이나 API 키, 합성 텍스트를 포함하지 않습니다. 키 누락과 빈 텍스트는 외부 요청 전에 거부합니다.

## 개발 시 검증

새 테스트는 가상 키·문장·음성 ID, 모의 HTTP 응답과 임시 설정 경로를 사용합니다. 실제 계정에서의 인증, 음질과 지연 시간은 사용자 계정으로 별도 확인해야 합니다.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_fish_audio_tts.py tests/test_fish_audio_settings_ui.py tests/test_tts_client.py tests/test_settings.py tests/test_app_tts_bootstrap.py tests/test_ui_i18n_smoke.py tests/test_bridge_tts_streaming.py -q
```

필요할 때 후속 작업으로 음성 미리듣기와 Fish Audio 스트리밍 연결을 추가할 수 있습니다.

API 계약: [Fish Audio 음성 합성 공식 문서](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech), 2026-09-06 확인.
