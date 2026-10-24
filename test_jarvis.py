import os
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.client import HTTPConnection
from types import SimpleNamespace
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer

import jarvis_actions
import jarvis_brain
from jarvis_server import JarvisHandler


class JarvisPersonaTests(unittest.TestCase):
    def test_brain_uses_an_original_assistant_persona(self):
        self.assertIn("original", jarvis_brain.SYSTEM_PROMPT)
        self.assertIn("technically precise", jarvis_brain.SYSTEM_PROMPT)
        self.assertIn("imitating any existing fictional character", jarvis_brain.SYSTEM_PROMPT)

    def test_transcription_uses_groq_whisper_turbo(self):
        transcribe = Mock(return_value=SimpleNamespace(text="  Hello Jarvis  "))
        cloud_client = SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=transcribe)
            )
        )
        with (
            patch.object(jarvis_brain, "_get_api_key", return_value="gsk-test-secret"),
            patch.object(jarvis_brain, "_get_client", return_value=cloud_client),
        ):
            text = jarvis_brain.transcribe_audio(b"recording", "voice.webm", "audio/webm", "en")

        self.assertEqual(text, "Hello Jarvis")
        transcribe.assert_called_once_with(
            model="whisper-large-v3-turbo",
            file=("voice.webm", b"recording", "audio/webm"),
            language="en",
            response_format="json",
        )

    def test_saved_api_key_enables_cloud_conversation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keyfile = str(Path(temp_dir) / ".openjarvis" / "free.key")
            cloud_client = SimpleNamespace(
                models=SimpleNamespace(
                    list=lambda: SimpleNamespace(
                        data=[SimpleNamespace(id="openai/gpt-oss-20b")]
                    )
                ),
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        create=lambda **kwargs: SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content="Mock cloud reply"))]
                        )
                    )
                )
            )
            with (
                patch.object(jarvis_brain, "KEYFILE", keyfile),
                patch.dict(os.environ, {"GROQ_API_KEY": ""}),
                patch("jarvis_actions.try_action", return_value=None),
                patch.object(jarvis_brain, "OpenAI", return_value=cloud_client) as openai_client,
                patch.object(jarvis_brain, "_client", None),
                patch.object(jarvis_brain, "_client_key", None),
                patch.object(jarvis_brain, "_available_models", None),
                patch.object(jarvis_brain, "_preferred_model", None),
                patch.object(jarvis_brain, "_history", []),
            ):
                jarvis_brain.save_api_key("gsk-test-secret")
                reply = jarvis_brain.think("Hello Jarvis")

        self.assertEqual(reply, "Mock cloud reply")
        openai_client.assert_called_once_with(
            api_key="gsk-test-secret",
            base_url="https://api.groq.com/openai/v1",
        )

    def test_connection_selects_a_model_from_live_catalog(self):
        cloud_client = SimpleNamespace(
            models=SimpleNamespace(
                list=lambda: SimpleNamespace(
                    data=[
                        SimpleNamespace(id="whisper-large-v3"),
                        SimpleNamespace(id="active-chat-model"),
                    ]
                )
            ),
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]
                    )
                )
            ),
        )
        with (
            patch.dict(os.environ, {"GROQ_API_KEY": "gsk-test-secret"}),
            patch.object(jarvis_brain, "OpenAI", return_value=cloud_client),
            patch.object(jarvis_brain, "_client", None),
            patch.object(jarvis_brain, "_client_key", None),
            patch.object(jarvis_brain, "_available_models", None),
            patch.object(jarvis_brain, "_preferred_model", None),
        ):
            result = jarvis_brain.test_connection()
            self.assertTrue(jarvis_brain.ready())

        self.assertEqual(result, {"connected": True, "model": "active-chat-model"})

    def test_connection_turns_invalid_key_into_safe_message(self):
        unauthorized = Exception("Unauthorized")
        unauthorized.status_code = 401
        with (
            patch.dict(os.environ, {"GROQ_API_KEY": "gsk-test-secret"}),
            patch.object(jarvis_brain, "_get_client", return_value=SimpleNamespace(
                models=SimpleNamespace(
                    list=lambda: (_ for _ in ()).throw(unauthorized)
                )
            )),
            patch.object(jarvis_brain, "_available_models", None),
        ):
            with self.assertRaises(jarvis_brain.GroqConnectionError) as raised:
                jarvis_brain.test_connection()

        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn("Replace it with an active key", str(raised.exception))
        self.assertNotIn("gsk-test-secret", str(raised.exception))

    def test_rejected_key_is_not_retried_for_every_chat_message(self):
        message = "Groq rejected this API key (401). Replace it with an active key from the Groq console."
        with (
            patch("jarvis_actions.try_action", return_value=None),
            patch.object(jarvis_brain, "_get_api_key", return_value="gsk-test-secret"),
            patch.object(jarvis_brain, "_authentication_error", message),
            patch.object(jarvis_brain, "_client") as client,
        ):
            self.assertEqual(jarvis_brain.think("hello"), message)

        client.chat.completions.create.assert_not_called()


class JarvisActionTests(unittest.TestCase):
    def test_time_command_is_handled_locally(self):
        response = jarvis_actions.try_action("what time is it")
        self.assertIn("It is currently", response)

    @patch("jarvis_actions._open_url", return_value=True)
    def test_youtube_search_opens_encoded_query(self, open_url):
        response = jarvis_actions.try_action("play lofi beats on youtube")
        self.assertEqual(response, "Searching YouTube for lofi beats.")
        self.assertIn("lofi%20beats", open_url.call_args.args[0])

    @patch("jarvis_actions._launch_app", return_value=True)
    def test_open_app_uses_cross_platform_launcher(self, launch_app):
        response = jarvis_actions.try_action("open VS Code")
        self.assertEqual(response, "Opening vs code.")
        launch_app.assert_called_once_with("vs code")

    def test_email_command_does_not_invent_inbox_contents(self):
        response = jarvis_actions.try_action("check my unread emails")
        self.assertIn("not connected", response)
        self.assertNotIn("3 unread", response)

    @patch("jarvis_actions._open_url", return_value=True)
    def test_whatsapp_message_requires_manual_review(self, open_url):
        response = jarvis_actions.try_action("send WhatsApp message to Alex saying hello")
        self.assertIn("review it before sending", response)
        self.assertNotIn("sent", response.lower())
        open_url.assert_called_once()


class JarvisApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), JarvisHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.keyfile = str(Path(self.temp_dir.name) / ".openjarvis" / "free.key")

    def tearDown(self):
        self.temp_dir.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, origin=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        if origin:
            headers["Origin"] = origin
        connection.request(method, path, payload, headers)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        connection.close()
        return status, data

    def request_audio(
        self,
        body=b"recorded audio",
        content_type="audio/webm",
        origin=None,
        language="en",
        content_length=None,
    ):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": content_type, "X-Speech-Language": language}
        if origin:
            headers["Origin"] = origin
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
        connection.request("POST", "/api/transcribe", body, headers)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        connection.close()
        return status, data

    def test_dashboard_is_served(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"command-form", body)
        self.assertIn(b"ai-key-form", body)
        self.assertIn(b"test-ai-connection", body)
        self.assertIn(b"replace-ai-key", body)
        self.assertIn(b"send it to Groq for transcription", body)

    def test_audio_transcription_endpoint_accepts_local_recording(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        with patch.object(jarvis_brain, "transcribe_audio", return_value="What time is it?") as transcribe:
            status, body = self.request_audio(origin=origin)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"text": "What time is it?"})
        transcribe.assert_called_once_with(b"recorded audio", "jarvis-microphone.webm", "audio/webm", "en")

    def test_audio_transcription_rejects_untrusted_origin(self):
        status, body = self.request_audio(origin="https://example.invalid")
        self.assertEqual(status, 403)
        self.assertIn("local Jarvis dashboard", json.loads(body)["error"])

    def test_audio_transcription_requires_dashboard_origin(self):
        status, body = self.request_audio()
        self.assertEqual(status, 403)
        self.assertIn("local Jarvis dashboard", json.loads(body)["error"])

    def test_audio_transcription_reports_missing_groq_key(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        with patch.object(jarvis_brain, "_get_api_key", return_value=None):
            status, body = self.request_audio(origin=origin)
        self.assertEqual(status, 503)
        self.assertIn("Add and verify a Groq API key", json.loads(body)["error"])

    def test_audio_transcription_rejects_unsupported_format(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, body = self.request_audio(content_type="application/octet-stream", origin=origin)
        self.assertEqual(status, 415)
        self.assertIn("recording format is not supported", json.loads(body)["error"])

    def test_audio_transcription_rejects_oversized_recording(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, body = self.request_audio(
            body=b"",
            origin=origin,
            content_length=10 * 1024 * 1024 + 1,
        )
        self.assertEqual(status, 413)
        self.assertIn("10 MB", json.loads(body)["error"])

    def test_audio_transcription_rejects_invalid_language(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, body = self.request_audio(origin=origin, language="invalid!")
        self.assertEqual(status, 400)
        self.assertIn("Invalid speech language", json.loads(body)["error"])

    def test_command_endpoint_accepts_local_dashboard_origin(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, body = self.request("POST", "/api/command", {"query": "what time is it"}, origin)
        self.assertEqual(status, 200)
        self.assertIn("It is currently", json.loads(body)["reply"])

    def test_command_endpoint_rejects_external_origin(self):
        status, body = self.request(
            "POST",
            "/api/command",
            {"query": "what time is it"},
            "https://example.invalid",
        )
        self.assertEqual(status, 403)
        self.assertIn("local Jarvis dashboard", json.loads(body)["error"])

    def test_command_endpoint_rejects_empty_commands(self):
        status, body = self.request("POST", "/api/command", {"query": " "})
        self.assertEqual(status, 400)
        self.assertIn("Enter a command", json.loads(body)["error"])

    def test_ai_status_does_not_disclose_api_key(self):
        message = "Groq rejected this API key (401). Replace it with an active key."
        with (
            patch.object(jarvis_brain, "KEYFILE", self.keyfile),
            patch.dict(os.environ, {"GROQ_API_KEY": ""}),
            patch.object(jarvis_brain, "connection_error", return_value=message),
        ):
            jarvis_brain.save_api_key("gsk-test-secret")
            status, body = self.request("GET", "/api/settings/ai")
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["source"], "local_file")
        self.assertTrue(result["configured"])
        self.assertNotIn("api_key", result)
        self.assertNotIn(b"gsk-test-secret", body)
        self.assertEqual(result["connection_error"], message)

    def test_ai_key_save_and_remove_require_local_dashboard_origin(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        with patch.object(jarvis_brain, "KEYFILE", self.keyfile), patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            status, body = self.request("POST", "/api/settings/ai", {"api_key": "gsk-test-secret"})
            self.assertEqual(status, 403)
            status, body = self.request(
                "POST",
                "/api/settings/ai",
                {"api_key": "gsk-test-secret"},
                "https://example.invalid",
            )
            self.assertEqual(status, 403)
            self.assertFalse(Path(self.keyfile).exists())
            status, body = self.request(
                "POST",
                "/api/settings/ai",
                {"api_key": "gsk-test-secret"},
                origin,
            )
            self.assertEqual(status, 200)
            self.assertNotIn(b"gsk-test-secret", body)
            self.assertEqual(Path(self.keyfile).read_text(encoding="utf-8"), "gsk-test-secret")
            status, body = self.request("DELETE", "/api/settings/ai", origin=origin)
            self.assertEqual(status, 200)
            self.assertFalse(Path(self.keyfile).exists())
            self.assertFalse(json.loads(body)["configured"])

    def test_ai_key_save_rejects_empty_key(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, body = self.request("POST", "/api/settings/ai", {"api_key": "  "}, origin)
        self.assertEqual(status, 400)
        self.assertIn("valid Groq API key", json.loads(body)["error"])

    def test_environment_key_takes_precedence_over_dashboard_key(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        with patch.object(jarvis_brain, "KEYFILE", self.keyfile), patch.dict(
            os.environ,
            {"GROQ_API_KEY": "gsk-environment-secret"},
        ):
            status, body = self.request("POST", "/api/settings/ai", {"api_key": "gsk-test-secret"}, origin)
        self.assertEqual(status, 409)
        self.assertNotIn(b"gsk-environment-secret", body)
        self.assertFalse(Path(self.keyfile).exists())

    def test_connection_test_endpoint_requires_local_origin(self):
        status, body = self.request("POST", "/api/settings/ai/test")
        self.assertEqual(status, 403)
        self.assertIn("local Jarvis dashboard", json.loads(body)["error"])

    def test_connection_test_endpoint_reports_working_model(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        with patch.object(
            jarvis_brain,
            "test_connection",
            return_value={"connected": True, "model": "active-chat-model"},
        ):
            status, body = self.request("POST", "/api/settings/ai/test", {}, origin)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["model"], "active-chat-model")

    def test_connection_test_endpoint_sanitizes_authentication_failure(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        with patch.object(
            jarvis_brain,
            "test_connection",
            side_effect=jarvis_brain.GroqConnectionError(
                "Groq rejected this API key (401). Replace it with an active key from the Groq console.",
                401,
            ),
        ):
            status, body = self.request("POST", "/api/settings/ai/test", {}, origin)
        self.assertEqual(status, 401)
        self.assertFalse(json.loads(body)["connected"])
        self.assertNotIn("api_key", json.loads(body))


if __name__ == "__main__":
    unittest.main()
