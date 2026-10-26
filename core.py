"""음성 검사, OpenAI 전송, UTF-8 저장. 원본 파일 경로는 열지 않습니다."""
from datetime import datetime
from io import BytesIO
import math
from pathlib import Path
from uuid import uuid4

import mutagen
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError

MODEL = "gpt-transcribe"
MAX_BYTES = 24_000_000  # API 25 MB 제한보다 여유 있게 설정
MAX_SECONDS = 20 * 60  # 1차 버전 자체 제한
FORMATS = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
           ".flac": "audio/flac", ".ogg": "audio/ogg"}


class UserError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 오류만 담습니다."""


def validate_audio(name: str, data: bytes) -> float:
    suffix = Path(name).suffix.lower()
    if suffix not in FORMATS:
        raise UserError("지원하지 않는 파일 형식입니다. M4A, MP3, WAV, FLAC, OGG 중 하나로 복사본을 변환해 주세요. 파일 이름의 확장자만 바꾸면 안 됩니다.")
    if not data:
        raise UserError("파일이 비어 있습니다. 휴대폰에서 녹음 파일을 다시 복사해 주세요.")
    if len(data) > MAX_BYTES:
        raise UserError("파일이 24 MB를 초과합니다. 이 버전은 한 번에 24 MB 이하만 처리합니다. 원본을 보관하고 복사본을 20분 이하로 나누거나 MP3로 압축해 주세요.")
    try:
        audio = mutagen.File(BytesIO(data))
        seconds = float(audio.info.length) if audio is not None else 0
    except Exception:
        raise UserError("오디오 정보를 읽을 수 없습니다. 파일이 손상되었거나 지원하지 않는 인코딩일 수 있습니다. PC에서 재생되는지 확인하고, 복사본을 MP3 또는 WAV로 변환해 주세요.") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise UserError("녹음 길이를 확인할 수 없습니다. PC에서 재생되는지 확인하고 복사본을 MP3 또는 WAV로 변환해 주세요.")
    if seconds > MAX_SECONDS:
        raise UserError("녹음이 20분을 초과합니다. 누락과 긴 대기를 줄이기 위한 1차 버전 제한입니다. 원본을 보관하고 복사본을 문장 사이에서 20분 이하로 나눈 뒤 하나씩 올려 주세요.")
    return seconds


def friendly_api_error(error: Exception) -> str:
    if isinstance(error, APITimeoutError):
        return "응답 대기 시간이 지났습니다. 인터넷을 확인하고 짧게 나눈 복사본으로 시도해 주세요. 서버에서 이미 처리했을 수 있어 재시도 시 비용이 추가될 수 있습니다."
    if isinstance(error, APIConnectionError):
        return "OpenAI에 연결하지 못했습니다. 인터넷 연결, VPN, 방화벽을 확인한 뒤 다시 시도해 주세요."
    if isinstance(error, APIStatusError):
        status = error.status_code
        if status == 401:
            return "API 키를 확인할 수 없습니다. 1_set_api_key.cmd에서 유효한 키를 다시 등록한 뒤 프로그램을 다시 실행해 주세요."
        if status == 403:
            return "이 API 키에 사용 권한이 없습니다. OpenAI 프로젝트의 키 권한과 모델 사용 권한을 확인해 주세요."
        if status == 404:
            return "음성 인식 모델을 사용할 수 없습니다. OpenAI 프로젝트의 gpt-transcribe 사용 가능 여부를 확인해 주세요."
        if status == 429:
            return "API 사용 한도 또는 잔액 문제입니다. OpenAI API 결제·잔액·프로젝트 한도를 확인해 주세요. 요청이 너무 많았다면 잠시 뒤 다시 시도해 주세요."
        if status == 413:
            return "서버가 파일이 너무 크다고 응답했습니다. 복사본을 더 짧게 나누거나 MP3로 압축해 주세요."
        if status in (400, 415, 422):
            return "서버가 오디오를 처리하지 못했습니다. 지원하지 않는 인코딩, 손상, 긴 녹음이 원인일 수 있습니다. 재생을 확인한 뒤 짧은 MP3 또는 WAV 복사본으로 시도해 주세요."
        if status >= 500:
            return "OpenAI 서버에 일시적인 문제가 있습니다. 잠시 뒤 다시 시도해 주세요. 재시도 시 비용이 추가될 수 있습니다."
    return "예상하지 못한 오류로 변환을 마치지 못했습니다. 프로그램을 다시 실행하고 짧은 MP3 또는 WAV 복사본으로 시도해 주세요. 키나 녹음 내용이 포함된 오류 로그를 공유하지 마세요."


def transcribe(data: bytes, suffix: str, api_key: str) -> str:
    if not api_key.strip():
        raise UserError("API 키가 없습니다. 1_set_api_key.cmd로 등록한 뒤 프로그램을 다시 실행해 주세요.")
    try:
        # 파일명에 포함된 전화번호·이름은 전송하지 않습니다. 자동 재시도도 끕니다.
        with OpenAI(api_key=api_key.strip(), base_url="https://api.openai.com/v1",
                    timeout=300.0, max_retries=0) as client:
            result = client.audio.transcriptions.create(
                model=MODEL, file=("recording" + suffix, data, FORMATS[suffix]),
                extra_body={"languages": ["ko"]},
            )
        text = result.text.strip()
    except Exception as error:
        raise UserError(friendly_api_error(error)) from None
    if not text:
        raise UserError("인식된 텍스트가 없습니다. 말소리가 들리는지 확인하고 음성이 있는 짧은 복사본으로 시도해 주세요.")
    return text


def make_document(name: str, call_at: datetime, text: str) -> str:
    safe_name = name.replace("\r", " ").replace("\n", " ")
    return (f"통화 녹음 텍스트\n원본 파일명: {safe_name}\n"
            f"통화 일시: {call_at:%Y-%m-%d %H:%M} (한국 시간, UTC+09:00)\n"
            f"음성 인식 모델: {MODEL}\n\n{text}\n")


def save_document(document: str, call_at: datetime, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"통화_{call_at:%Y%m%d_%H%M}_{uuid4().hex}.txt"
    # 기존 결과를 덮어쓰지 않습니다.
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(document)
    return path
