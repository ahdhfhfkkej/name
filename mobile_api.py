"""개인용 휴대폰 앱의 분석 API. 녹음/텍스트를 파일이나 DB에 저장하지 않습니다."""
from collections import deque
from datetime import datetime
import json
import os
import secrets
import threading
import time

from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core import MAX_BYTES, FORMATS, UserError, validate_audio, transcribe
from appointments import extract_appointments

app = FastAPI(title="개인 통화 약속 분석", docs_url=None, redoc_url=None, openapi_url=None)
processing = threading.BoundedSemaphore(1)
request_times = deque()
rate_lock = threading.Lock()


def authorize(authorization: str | None = Header(default=None)):
    expected = os.environ.get("PHONE_ACCESS_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(503, "서버 접속 코드가 설정되지 않았습니다.")
    supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not secrets.compare_digest(expected.encode(), supplied.encode()):
        raise HTTPException(401, "앱의 서버 주소와 개인 접속 코드를 확인해 주세요.")


def claim_job():
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise HTTPException(503, "분석 서버의 OpenAI API 키가 설정되지 않았습니다.")
    with rate_lock:
        now = time.monotonic()
        while request_times and request_times[0] < now - 3600:
            request_times.popleft()
        if len(request_times) >= 30:
            raise HTTPException(429, "개인 서버의 시간당 30회 한도입니다. 잠시 뒤 시도해 주세요.")
        if not processing.acquire(blocking=False):
            raise HTTPException(409, "다른 분석을 진행하고 있습니다. 완료 후 다시 시도해 주세요.")
        request_times.append(now)


async def bounded_body(request: Request, limit: int):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise HTTPException(413, "요청이 너무 큽니다. 녹음은 24 MB 이하, 텍스트는 40,000자 이하로 나누어 주세요.")
        data.extend(chunk)
    return bytes(data)


@app.exception_handler(UserError)
async def user_error(request, error):
    return JSONResponse(status_code=400, content={"detail": str(error)})


@app.exception_handler(Exception)
async def unexpected_error(request, error):
    return JSONResponse(status_code=500, content={"detail": "분석 서버에 문제가 생겼습니다. 원본을 보관하고 잠시 뒤 다시 시도해 주세요."})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/status", dependencies=[Depends(authorize)])
def status():
    return {"ready": bool(os.environ.get("OPENAI_API_KEY", "").strip())}


@app.post("/v1/transcribe", dependencies=[Depends(authorize)])
async def audio_to_text(request: Request, extension: str = ".m4a"):
    extension = extension.lower()
    if extension not in FORMATS:
        raise HTTPException(415, "M4A, MP3, WAV, FLAC, OGG 녹음을 선택해 주세요.")
    data = await bounded_body(request, MAX_BYTES)
    seconds = await run_in_threadpool(validate_audio, "recording" + extension, data)
    claim_job()
    try:
        text = await run_in_threadpool(transcribe, data, extension, os.environ["OPENAI_API_KEY"])
        return {"text": text, "duration_seconds": seconds}
    finally:
        processing.release()


class AnalyzeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=40000)
    call_at: datetime


@app.post("/v1/appointments", dependencies=[Depends(authorize)])
async def analyze(request: Request):
    data = await bounded_body(request, 200000)
    try:
        payload = AnalyzeBody.model_validate_json(data)
    except (ValidationError, ValueError):
        raise HTTPException(422, "통화 텍스트와 날짜·시간을 확인해 주세요. 텍스트는 40,000자 이하입니다.") from None
    if payload.call_at.tzinfo is None or not payload.text.strip():
        raise HTTPException(422, "통화 시각의 시간대 또는 통화 텍스트가 비어 있습니다.")
    claim_job()
    try:
        return await run_in_threadpool(extract_appointments, payload.text, payload.call_at, os.environ["OPENAI_API_KEY"])
    finally:
        processing.release()
