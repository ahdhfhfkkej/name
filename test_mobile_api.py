import os
from datetime import datetime
from io import BytesIO
import time
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient
import mobile_api

TOKEN="offline-test-personal-access-code-123456789"
AUTH={"Authorization":"Bearer "+TOKEN}


def wav():
    out=BytesIO()
    with wave.open(out,"wb") as handle:
        handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(8000)
        handle.writeframes(b"\0\0"*8000)
    return out.getvalue()


class MobileApiTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"PHONE_ACCESS_TOKEN":TOKEN,"OPENAI_API_KEY":"offline-not-a-real-key"})
        self.env.start();mobile_api.request_times.clear()
        self.client=TestClient(mobile_api.app)

    def tearDown(self):
        self.client.close();self.env.stop()

    def test_health_and_private_status(self):
        self.assertEqual(self.client.get("/health").json(),{"status":"ok"})
        self.assertEqual(self.client.get("/v1/status").status_code,401)
        self.assertEqual(self.client.get("/v1/status",headers=AUTH).json(),{"ready":True})
        self.assertEqual(self.client.get("/docs").status_code,404)

    def test_authentication_rejects_before_api(self):
        with patch("mobile_api.extract_appointments") as extract:
            for headers in ({},{"Authorization":TOKEN},{"Authorization":"Bearer wrong-code"}):
                response=self.client.post("/v1/appointments",headers=headers,json={"text":"내일 만나자","call_at":"2026-10-27T12:00:00+09:00"})
                self.assertEqual(response.status_code,401)
            extract.assert_not_called()

    def test_missing_configuration_closed(self):
        with patch.dict(os.environ,{"PHONE_ACCESS_TOKEN":""}):
            self.assertEqual(self.client.get("/v1/status",headers=AUTH).status_code,503)

    def test_transcription_uses_uploaded_copy(self):
        data=wav()
        with patch("mobile_api.transcribe",return_value="내일 오후 세 시에 만나자.") as recognize:
            response=self.client.post("/v1/transcribe?extension=.wav",headers=AUTH,content=data)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["duration_seconds"],1)
            self.assertEqual(recognize.call_args.args[:2],(data,".wav"))

    def test_bad_audio_rejected_without_api(self):
        with patch("mobile_api.transcribe") as recognize:
            self.assertEqual(self.client.post("/v1/transcribe?extension=.amr",headers=AUTH,content=b"bad").status_code,415)
            self.assertEqual(self.client.post("/v1/transcribe?extension=.wav",headers=AUTH,content=b"bad").status_code,400)
            self.assertEqual(self.client.post("/v1/transcribe",headers=AUTH,content=b"x"*24000001).status_code,413)
            recognize.assert_not_called()

    def test_extraction_round_trip_and_timezone(self):
        result={"appointments":[],"timezone":"Asia/Seoul","summary":"약속 없음"}
        with patch("mobile_api.extract_appointments",return_value=result) as extract:
            response=self.client.post("/v1/appointments",headers=AUTH,json={"text":"건강 잘 챙겨.","call_at":"2026-10-26T15:30:00+00:00"})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json(),result)
            self.assertIsNotNone(extract.call_args.args[1].tzinfo)

    def test_invalid_text_and_naive_time(self):
        with patch("mobile_api.extract_appointments") as extract:
            for body in ({"text":"x","call_at":"2026-10-27T12:00:00"},
                         {"text":"x"*40001,"call_at":"2026-10-27T12:00:00+09:00"},
                         {"text":"","call_at":"2026-10-27T12:00:00+09:00"}):
                self.assertEqual(self.client.post("/v1/appointments",headers=AUTH,json=body).status_code,422)
            extract.assert_not_called()

    def test_rate_and_concurrency_limits(self):
        body={"text":"대화","call_at":"2026-10-27T12:00:00+09:00"}
        with patch("mobile_api.extract_appointments") as extract:
            mobile_api.request_times.extend([time.monotonic()]*30)
            self.assertEqual(self.client.post("/v1/appointments",headers=AUTH,json=body).status_code,429)
            mobile_api.request_times.clear()
            mobile_api.processing.acquire()
            try:self.assertEqual(self.client.post("/v1/appointments",headers=AUTH,json=body).status_code,409)
            finally:mobile_api.processing.release()
            extract.assert_not_called()


if __name__=="__main__":unittest.main(verbosity=2)
