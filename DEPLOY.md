# 분석 서버 배포 준비

이 디렉터리 전체를 Docker 지원 호스팅의 빌드 루트로 사용합니다. 배포하지 않은 로컬 준비물입니다.

필수 환경변수:

- `OPENAI_API_KEY`: 본인의 유효한 OpenAI API 키. 해당 계정의 잔액·한도 확인 필요.
- `PHONE_ACCESS_TOKEN`: 휴대폰만 사용할 임의의 긴 접속 코드(32자 이상). OpenAI 키와 다른 값입니다.
- `PORT`: 호스팅이 주입하거나 기본 8080.

`render.yaml`은 이 폴더가 Git 저장소의 루트일 때의 예입니다. Render Blueprint로 배포하면 OpenAI 키는 대시보드 비밀 환경변수로 입력하고 개인 접속 코드는 `generateValue: true`로 생성합니다. 생성된 코드와 HTTPS 서비스 주소를 본인 휴대폰 앱에 입력합니다. 요금제 선택과 계정·배포 승인은 사용자 계정에서 진행해야 합니다.

서비스는 HTTPS 프록시 뒤에 두어야 합니다. 앱은 HTTPS가 아닌 주소를 허용하지 않습니다. Dockerfile의 HTTP 포트는 프록시 내부용입니다.

엔드포인트:

- `GET /health`: 상태만 반환. 키·녹음·텍스트 없음.
- `GET /v1/status`: 개인 코드 인증 후 서버 키 설정 여부 반환. 키 값은 반환하지 않음.
- `POST /v1/transcribe?extension=.m4a`: 원시 오디오 바디. 24 MB 이하. 원래 파일명은 받지 않음.
- `POST /v1/appointments`: `text`, 시간대가 있는 ISO `call_at` JSON.

분석 경로에는 `Authorization: Bearer <개인 접속 코드>`가 필요합니다. 단일 인스턴스·단일 worker 개인 사용을 전제로 합니다. 인증 실패 시 유료 API를 호출하지 않고, 기본 요청 로그는 끕니다.

외부 API 없는 로컬 테스트 의존성은 본 requirements 외에 `httpx`가 필요합니다. `python -m unittest -v test_mobile_api`로 검사합니다.

서버에는 Google 로그인이나 캘린더 토큰이 없습니다. 캘린더 등록은 휴대폰의 캘린더 작성 화면에 넘겨 사용자가 저장합니다.
