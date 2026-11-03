import asyncio
import base64
import os
import tempfile
import time
import unittest

import hermes_bridge as hb
from hermes_bridge import (
    is_visual_query, await_photo, build_provider_request, parse_provider_reply,
)


class TestIsVisualQuery(unittest.TestCase):
    def test_visual_phrases_match(self):
        for phrase in [
            "What am I looking at?",
            "can you see this",
            "READ THIS for me",
            "what is this thing in front of me",
            "take a picture",
            "use the camera",
        ]:
            self.assertTrue(is_visual_query(phrase), phrase)

    def test_non_visual_phrases_do_not_match(self):
        for phrase in [
            "what's the weather tomorrow",
            "tell me a joke",
            "who wrote hamlet",
            # bare 'picture'/'photo' must NOT trigger - meta-questions about
            # photos were re-photographing the room. (Note: a meta-question
            # containing the literal phrase 'take a picture' still triggers;
            # keyword matching cannot tell it from the command.)
            "why was a photo captured just now",
            "do you always talk this much",
        ]:
            self.assertFalse(is_visual_query(phrase), phrase)

    def test_deictic_covers_photo_reference(self):
        from hermes_bridge import should_capture_photo
        # "describe this photo" flows through the deictic path now
        self.assertTrue(should_capture_photo("describe this photo", 0.0, 1000.0))
        # ...but meta/degree deictics never capture
        self.assertFalse(should_capture_photo("do you always talk this much", 0.0, 1000.0))
        self.assertFalse(should_capture_photo("keep it short like this answer", 0.0, 1000.0))
        # auxiliary verbs after this/that must not trigger
        self.assertFalse(should_capture_photo("hi this is a test", 0.0, 1000.0))
        self.assertFalse(should_capture_photo("that was great", 0.0, 1000.0))
        self.assertFalse(should_capture_photo("this should work now", 0.0, 1000.0))


class FakeWebSocket:
    """Minimal stand-in exposing recv()/send() like websockets."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    async def recv(self):
        if not self._messages:
            await asyncio.sleep(30)  # simulate silence until timeout
        return self._messages.pop(0)

    async def send(self, message):
        self.sent.append(message)


class TestAwaitPhoto(unittest.TestCase):
    def test_photo_message_returns_decoded_bytes(self):
        jpeg = b"\xff\xd8\xff\xe0fakejpeg"
        ws = FakeWebSocket([
            b"\x00\x01binary-mic-audio-to-skip",
            '{"type":"debug","msg":"ignored"}',
            '{"type":"photo","data":"%s"}' % base64.b64encode(jpeg).decode(),
        ])
        result = asyncio.run(await_photo(ws, timeout=2.0))
        self.assertEqual(result, jpeg)

    def test_photo_error_returns_none(self):
        ws = FakeWebSocket(['{"type":"photo_error","message":"no camera"}'])
        result = asyncio.run(await_photo(ws, timeout=2.0))
        self.assertIsNone(result)

    def test_timeout_returns_none(self):
        ws = FakeWebSocket([])
        result = asyncio.run(await_photo(ws, timeout=0.2))
        self.assertIsNone(result)

    def test_malformed_json_frame_ignored_keeps_waiting(self):
        # A malformed text frame must not raise / abort the wait - it should
        # be logged and skipped, leaving the loop to pick up the next frame.
        jpeg = b"\xff\xd8\xff\xe0fakejpeg"
        ws = FakeWebSocket([
            "{not valid json",
            '{"type":"photo","data":"%s"}' % base64.b64encode(jpeg).decode(),
        ])
        result = asyncio.run(await_photo(ws, timeout=2.0))
        self.assertEqual(result, jpeg)

    def test_non_dict_json_frame_ignored_keeps_waiting(self):
        # Valid JSON that isn't an object (e.g. a bare array) must not raise
        # AttributeError from `.get` - it should be skipped like malformed
        # JSON.
        jpeg = b"\xff\xd8\xff\xe0fakejpeg"
        ws = FakeWebSocket([
            "[1]",
            '{"type":"photo","data":"%s"}' % base64.b64encode(jpeg).decode(),
        ])
        result = asyncio.run(await_photo(ws, timeout=2.0))
        self.assertEqual(result, jpeg)


class TestProcessQuery(unittest.TestCase):
    """process_query: text in → hermes → response + TTS out, incl. photo path."""

    def _run(self, text, ws, fake_reply="ok", fake_tts=b"\x00\x00",
             stored_session=None, bridge_tts=True, delay=0.0,
             ack_after=10.0, ack_enabled=True, api_fake=None):
        orig_ask, orig_tts = hb.ask_hermes, hb.synthesize_speech
        orig_log = hb.log_turn
        orig_bridge_tts = hb.BRIDGE_TTS
        hb.BRIDGE_TTS = bridge_tts
        orig_ack = (hb.ACK_ENABLED, hb.ACK_AFTER_S)
        hb.ACK_ENABLED, hb.ACK_AFTER_S = ack_enabled, ack_after
        orig_api_fn = hb.ask_hermes_api
        # Pin the brain so an exported HERMES_BRIDGE_BRAIN can't route this
        # around the fake ask_hermes (KeyError, or a real HTTP call).
        orig_brain = hb.BRAIN
        hb.BRAIN = "hermes"
        orig_api = hb.HERMES_API_ENABLED
        hb.HERMES_API_ENABLED = api_fake is not None
        if api_fake is not None:
            hb.ask_hermes_api = api_fake
        orig_models = (
            hb.HERMES_AGENT_MODEL, hb.HERMES_AGENT_PROVIDER,
            hb.HERMES_AGENT_FALLBACK_MODEL, hb.HERMES_AGENT_FALLBACK_PROVIDER,
        )
        hb.HERMES_AGENT_MODEL = "glm-5.3-flash"
        hb.HERMES_AGENT_PROVIDER = "zai"
        hb.HERMES_AGENT_FALLBACK_MODEL = "google/gemini-3.7-flash"
        hb.HERMES_AGENT_FALLBACK_PROVIDER = "openrouter"
        orig_session_file = hb.SESSION_FILE
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        os.unlink(tmp.name)  # start with no stored session
        hb.SESSION_FILE = tmp.name
        if stored_session:
            hb.store_session(stored_session)
        calls = {}

        def fake_ask(query, image_path=None, resume=None, model=None, provider=None, **kwargs):
            calls["query"] = query
            calls["image_path"] = image_path
            calls["resume"] = resume
            calls["model"] = model
            calls["provider"] = provider
            if delay:
                time.sleep(delay)  # runs in a worker thread (asyncio.to_thread)
            return fake_reply, "20260710_000000_test"

        hb.ask_hermes = fake_ask
        hb.synthesize_speech = (fake_tts if callable(fake_tts)
                                else (lambda t: fake_tts))
        hb.log_turn = lambda *a, **k: None
        try:
            asyncio.run(hb.process_query(ws, text))
        finally:
            hb.ask_hermes, hb.synthesize_speech = orig_ask, orig_tts
            hb.log_turn = orig_log
            hb.BRIDGE_TTS = orig_bridge_tts
            hb.ACK_ENABLED, hb.ACK_AFTER_S = orig_ack
            hb.ask_hermes_api = orig_api_fn
            hb.BRAIN = orig_brain
            hb.HERMES_API_ENABLED = orig_api
            (hb.HERMES_AGENT_MODEL, hb.HERMES_AGENT_PROVIDER,
             hb.HERMES_AGENT_FALLBACK_MODEL, hb.HERMES_AGENT_FALLBACK_PROVIDER) = orig_models
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            hb.SESSION_FILE = orig_session_file
        return calls

    def test_default_no_bridge_tts(self):
        ws = FakeWebSocket([])
        self._run("tell me a joke", ws, bridge_tts=False)
        sent = [m for m in ws.sent if isinstance(m, str)]
        self.assertTrue(any('"tts": false' in m for m in sent))
        self.assertFalse(any('"audio_start"' in m for m in sent))
        self.assertFalse(any('"audio_end"' in m for m in sent))

    def test_plain_query_answers_without_photo(self):
        ws = FakeWebSocket([])
        calls = self._run("tell me a joke", ws)
        # Fresh session → persona preamble prefixed
        self.assertTrue(calls["query"].endswith("tell me a joke"))
        self.assertIn("voice assistant", calls["query"])
        self.assertIsNone(calls["resume"])
        self.assertIsNone(calls["image_path"])
        self.assertEqual(calls["model"], "glm-5.3-flash")
        self.assertEqual(calls["provider"], "zai")
        sent_types = [m for m in ws.sent if isinstance(m, str)]
        self.assertFalse(any('"capture_photo"' in m for m in sent_types))
        self.assertTrue(any('"response"' in m for m in sent_types))
        self.assertTrue(any('"audio_end"' in m for m in sent_types))
        self.assertTrue(any('"streamed"' in m for m in sent_types))

    def test_multi_sentence_streams_deltas_and_tts_clips(self):
        ws = FakeWebSocket([])
        self._run("tell me a joke", ws, fake_reply="Hello there. How are you?")
        sent = [m for m in ws.sent if isinstance(m, str)]
        deltas = [m for m in sent if '"response_delta"' in m]
        self.assertGreaterEqual(len(deltas), 2)
        self.assertGreaterEqual(sum(1 for m in sent if '"audio_clip"' in m), 2)
        self.assertTrue(any('"streamed": true' in m for m in sent))

    def test_resumed_session_skips_persona(self):
        ws = FakeWebSocket([])
        calls = self._run("tell me a joke", ws, stored_session="sid123")
        self.assertEqual(calls["query"], "tell me a joke")
        self.assertEqual(calls["resume"], "sid123")

    def test_visual_query_requests_photo_and_passes_image(self):
        jpeg = b"\xff\xd8\xff\xe0fakejpeg"
        ws = FakeWebSocket([
            '{"type":"photo","data":"%s"}' % base64.b64encode(jpeg).decode(),
        ])
        calls = self._run("what am I looking at", ws)
        self.assertTrue(any('"capture_photo"' in m
                            for m in ws.sent if isinstance(m, str)))
        self.assertIsNotNone(calls["image_path"])
        self.assertTrue(calls["query"].endswith("what am I looking at"))

    def test_visual_query_photo_error_falls_back_to_text(self):
        ws = FakeWebSocket(['{"type":"photo_error","message":"no camera"}'])
        calls = self._run("what am I looking at", ws)
        self.assertIsNone(calls["image_path"])
        self.assertIn("No photo could be captured", calls["query"])


class TestAck(TestProcessQuery):
    """Spoken "one sec" filler for slow turns (ACK_ENABLED / ACK_AFTER_S)."""

    @staticmethod
    def _types(ws):
        import json as _json
        return [_json.loads(m)["type"] for m in ws.sent if isinstance(m, str)]

    @staticmethod
    def _acks(ws):
        import json as _json
        msgs = [_json.loads(m) for m in ws.sent if isinstance(m, str)]
        return [m["text"] for m in msgs if m["type"] == "ack"]

    def test_ack_phrase(self):
        self.assertEqual(hb.ack_phrase(None, visual=True), "Let me look.")
        self.assertEqual(hb.ack_phrase("web_search", visual=False), "Searching now.")
        self.assertEqual(hb.ack_phrase("browser_navigate", visual=False), "Searching now.")
        self.assertEqual(hb.ack_phrase("terminal", visual=False), "One sec.")
        self.assertTrue(hb.is_search_tool("web_search"))
        self.assertFalse(hb.is_search_tool("memory"))
        self.assertEqual(hb.ack_phrase(None, visual=False), "One sec.")

    def test_fast_reply_gets_no_ack(self):
        ws = FakeWebSocket([])
        self._run("tell me a joke", ws, ack_after=10.0)
        self.assertEqual(self._acks(ws), [])

    def test_slow_reply_acks_before_reply_and_still_speaks_reply(self):
        ws = FakeWebSocket([])
        self._run("tell me a joke", ws, fake_reply="Here it is.",
                  fake_tts=lambda t: t.encode(), delay=0.3, ack_after=0.05)
        self.assertEqual(self._acks(ws), ["One sec."])
        types = self._types(ws)
        self.assertLess(types.index("ack"), types.index("response_delta"))
        audio = [m for m in ws.sent if isinstance(m, bytes)]
        self.assertEqual(audio, [b"One sec.", b"Here it is."])
        self.assertEqual(types.count("audio_start"), 1)
        self.assertEqual(types[-1], "audio_end")

    def test_ack_disabled(self):
        ws = FakeWebSocket([])
        self._run("tell me a joke", ws, delay=0.2, ack_after=0.05,
                  ack_enabled=False)
        self.assertEqual(self._acks(ws), [])

    def test_visual_query_acks_let_me_look(self):
        jpeg = b"\xff\xd8\xff\xe0fakejpeg"
        ws = FakeWebSocket([
            '{"type":"photo","data":"%s"}' % base64.b64encode(jpeg).decode(),
        ])
        self._run("what am I looking at", ws, delay=0.1)
        self.assertEqual(self._acks(ws), ["Let me look."])
        types = self._types(ws)
        self.assertLess(types.index("capture_photo"), types.index("ack"))

    def test_tool_event_acks_searching_once(self):
        async def fake_api(text, photo, resume, on_text, model=None,
                           provider=None, on_tool=None):
            await on_tool({"tool": "web_search", "status": "running"})
            await on_tool({"tool": "web_extract", "status": "running"})
            await asyncio.sleep(0.2)
            await on_text("Found it.")
            return "Found it.", "sid-1"
        ws = FakeWebSocket([])
        self._run("latest tailscale version", ws, fake_tts=lambda t: t.encode(),
                  api_fake=fake_api)
        self.assertEqual(self._acks(ws), ["Searching now."])
        audio = [m for m in ws.sent if isinstance(m, bytes)]
        self.assertEqual(audio, [b"Searching now.", b"Found it."])

    def test_non_search_tool_does_not_ack_immediately(self):
        async def fake_api(text, photo, resume, on_text, model=None,
                           provider=None, on_tool=None):
            await on_tool({"tool": "memory", "status": "running"})
            await asyncio.sleep(0.1)
            await on_text("Done.")
            return "Done.", "sid-2"
        ws = FakeWebSocket([])
        self._run("remember my parking spot", ws, api_fake=fake_api)
        self.assertEqual(self._acks(ws), [])

    def test_ack_racing_first_token_is_dropped(self):
        # QA F4: tool event then a token with no await gap - the ack task
        # runs after reply text exists and must send nothing.
        async def fake_api(text, photo, resume, on_text, model=None,
                           provider=None, on_tool=None):
            await on_tool({"tool": "web_search", "status": "running"})
            await on_text("Found it.")
            return "Found it.", "sid-3"
        ws = FakeWebSocket([])
        self._run("latest tailscale version", ws,
                  fake_tts=lambda t: t.encode(), api_fake=fake_api)
        self.assertEqual(self._acks(ws), [])
        audio = [m for m in ws.sent if isinstance(m, bytes)]
        self.assertEqual(audio, [b"Found it."])

    def test_ack_clip_is_tagged(self):
        ws = FakeWebSocket([])
        self._run("tell me a joke", ws, fake_reply="Here it is.",
                  fake_tts=lambda t: t.encode(), delay=0.3, ack_after=0.05)
        clips = [m for m in ws.sent if isinstance(m, str) and '"audio_clip"' in m]
        self.assertEqual(clips[0], '{"type": "audio_clip", "ack": true}')
        self.assertNotIn('"ack"', clips[1])

    def test_ack_without_bridge_tts_is_text_only(self):
        ws = FakeWebSocket([])
        self._run("tell me a joke", ws, bridge_tts=False, delay=0.2,
                  ack_after=0.05)
        self.assertEqual(self._acks(ws), ["One sec."])
        self.assertNotIn("audio_start", self._types(ws))
        self.assertFalse(any(isinstance(m, bytes) for m in ws.sent))

    def test_empty_reply_after_ack_still_speaks_fallback(self):
        ws = FakeWebSocket([])
        self._run("tell me a joke", ws, fake_reply="",
                  fake_tts=lambda t: t.encode(), delay=0.3, ack_after=0.05)
        audio = b"".join(m for m in ws.sent if isinstance(m, bytes))
        self.assertTrue(audio.startswith(b"One sec."))
        self.assertIn(b"I'm not sure what to say.", audio)


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        self.hb = hb
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.orig = hb.SESSION_FILE
        hb.SESSION_FILE = self.tmp.name
        self.orig_models = (
            hb.HERMES_AGENT_MODEL, hb.HERMES_AGENT_PROVIDER,
            hb.HERMES_AGENT_FALLBACK_MODEL, hb.HERMES_AGENT_FALLBACK_PROVIDER,
        )
        hb.HERMES_AGENT_MODEL = "glm-5.3-flash"
        hb.HERMES_AGENT_PROVIDER = "zai"
        hb.HERMES_AGENT_FALLBACK_MODEL = "google/gemini-3.7-flash"
        hb.HERMES_AGENT_FALLBACK_PROVIDER = "openrouter"

    def tearDown(self):
        (hb.HERMES_AGENT_MODEL, hb.HERMES_AGENT_PROVIDER,
         hb.HERMES_AGENT_FALLBACK_MODEL, hb.HERMES_AGENT_FALLBACK_PROVIDER) = self.orig_models
        self.hb.SESSION_FILE = self.orig
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_store_and_load_same_day(self):
        self.hb.store_session("20260710_120000_abc123")
        self.assertEqual(self.hb.load_session(), "20260710_120000_abc123")
        self.assertEqual(self.hb.load_session_pair(), ("glm-5.3-flash", "zai"))

    def test_stale_session_not_loaded(self):
        import json as j
        with open(self.tmp.name, "w") as f:
            j.dump({"session_id": "old", "date": "2020-01-01"}, f)
        self.assertIsNone(self.hb.load_session())

    def test_clear(self):
        self.hb.store_session("x")
        self.hb.clear_session()
        self.assertIsNone(self.hb.load_session())

    def test_other_model_session_not_loaded(self):
        import json as j
        with open(self.tmp.name, "w") as f:
            j.dump({
                "session_id": "api-old-glm53",
                "date": self.hb._today(),
                "source": "api",
                "model": "glm-5.3",
                "provider": "zai",
            }, f)
        self.assertIsNone(self.hb.load_session())
        self.assertIsNone(self.hb.load_session_source())

    def test_legacy_session_without_model_not_loaded(self):
        import json as j
        with open(self.tmp.name, "w") as f:
            j.dump({
                "session_id": "api-legacy",
                "date": self.hb._today(),
                "source": "api",
            }, f)
        self.assertIsNone(self.hb.load_session())

    def test_fallback_session_is_loaded_as_its_own_pair(self):
        self.hb.store_session(
            "sid-gem",
            source="api",
            model="google/gemini-3.7-flash",
            provider="openrouter",
        )
        self.assertEqual(self.hb.load_session(), "sid-gem")
        self.assertEqual(self.hb.load_session_source(), "api")
        self.assertEqual(
            self.hb.load_session_pair(),
            ("google/gemini-3.7-flash", "openrouter"),
        )

    def test_store_without_pair_stamps_primary(self):
        self.hb.store_session("sid-default")
        self.assertEqual(self.hb.load_session_pair(), ("glm-5.3-flash", "zai"))


class TestSessionIdExtraction(unittest.TestCase):
    def test_extracts_from_stderr(self):
        from hermes_bridge import extract_session_id
        self.assertEqual(
            extract_session_id("\nsession_id: 20260710_162225_7c1fec\n"),
            "20260710_162225_7c1fec",
        )
        self.assertIsNone(extract_session_id("no id here"))


class TestShouldCapturePhoto(unittest.TestCase):
    def test_explicit_keyword_always_captures(self):
        from hermes_bridge import should_capture_photo
        self.assertTrue(should_capture_photo("take a picture", 100.0, 110.0))

    def test_deictic_triggers_capture(self):
        from hermes_bridge import should_capture_photo
        for phrase in ["how do I make this drink", "what's that building",
                       "is the one on the left better"]:
            self.assertTrue(should_capture_photo(phrase, 0.0, 1000.0), phrase)

    def test_deictic_suppressed_by_recent_photo(self):
        from hermes_bridge import should_capture_photo
        # photo 30s ago → deictic follow-up uses memory, no re-capture
        self.assertFalse(
            should_capture_photo("how do I make this drink", 970.0, 1000.0))

    def test_non_visual_never_captures(self):
        from hermes_bridge import should_capture_photo
        self.assertFalse(should_capture_photo("tell me a joke", 0.0, 1000.0))


# Tests for the retained legacy SDK helper (ask_claude / build_claude_user_content
# / trim_claude_history) - not on the live request path, which now goes through
# ask_provider()/build_provider_request(); kept for reference.
class TestClaudeBrain(unittest.TestCase):
    def test_user_content_text_only(self):
        from hermes_bridge import build_claude_user_content
        content = build_claude_user_content("hello there", None)
        self.assertEqual(content, [{"type": "text", "text": "hello there"}])

    def test_user_content_with_photo(self):
        from hermes_bridge import build_claude_user_content
        content = build_claude_user_content("what is this", b"\xff\xd8jpegbytes")
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[0]["source"]["type"], "base64")
        self.assertEqual(content[0]["source"]["media_type"], "image/jpeg")
        self.assertEqual(content[1], {"type": "text", "text": "what is this"})

    def test_history_trimmed_to_cap(self):
        from hermes_bridge import trim_claude_history
        history = [{"role": "user", "content": f"m{i}"} for i in range(100)]
        trimmed = trim_claude_history(history, max_messages=40)
        self.assertEqual(len(trimmed), 40)
        self.assertEqual(trimmed[-1]["content"], "m99")

    def test_claude_history_store_same_day(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        orig = hb.CLAUDE_HISTORY_FILE
        hb.CLAUDE_HISTORY_FILE = tmp.name
        try:
            hb.store_claude_history([{"role": "user", "content": "hi"}])
            self.assertEqual(len(hb.load_claude_history()), 1)
            hb.clear_claude_history()
            self.assertEqual(hb.load_claude_history(), [])
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            hb.CLAUDE_HISTORY_FILE = orig


class ProviderRequestTests(unittest.TestCase):
    def test_anthropic_request_shape(self):
        url, headers, body = build_provider_request(
            "anthropic", "claude-opus-4-8", "https://api.anthropic.com",
            "sk-ant", "hello", None)
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], "sk-ant")
        self.assertEqual(body["model"], "claude-opus-4-8")

    def test_anthropic_request_has_persona_system_prompt(self):
        from hermes_bridge import CLAUDE_SYSTEM
        _, _, body = build_provider_request(
            "anthropic", "claude-opus-4-8", "https://api.anthropic.com",
            "sk-ant", "hello", None)
        self.assertIsInstance(body["system"], str)
        self.assertTrue(body["system"])
        self.assertEqual(body["system"], CLAUDE_SYSTEM)

    def test_openai_request_shape_with_image(self):
        url, headers, body = build_provider_request(
            "openai", "gpt-4o", "https://api.openai.com", "sk-oai", "look", "QUJD")
        self.assertEqual(url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer sk-oai")
        content = body["messages"][-1]["content"]
        self.assertTrue(any(p.get("type") == "image_url" for p in content))

    def test_openai_request_has_persona_system_message_first(self):
        from hermes_bridge import CLAUDE_SYSTEM
        _, _, body = build_provider_request(
            "openai", "gpt-4o", "https://api.openai.com", "sk-oai", "look", None)
        self.assertEqual(body["messages"][0],
                          {"role": "system", "content": CLAUDE_SYSTEM})

    def test_gemini_request_shape(self):
        url, headers, body = build_provider_request(
            "gemini", "gemini-2.5-flash",
            "https://generativelanguage.googleapis.com", "g-key", "hi", None)
        self.assertTrue(url.endswith(":generateContent"))
        # The key belongs in a header, not the query string (proxy logs).
        self.assertNotIn("key=", url)
        self.assertEqual(headers["x-goog-api-key"], "g-key")

    def test_gemini_request_has_persona_system_instruction(self):
        _, _, body = build_provider_request(
            "gemini", "gemini-2.5-flash",
            "https://generativelanguage.googleapis.com", "g-key", "hi", None)
        text = body["systemInstruction"]["parts"][0]["text"]
        self.assertIsInstance(text, str)
        self.assertTrue(text)

    def test_parse_replies(self):
        self.assertEqual(
            parse_provider_reply("anthropic", 200,
                b'{"content":[{"type":"text","text":"a"}]}'), "a")
        self.assertEqual(
            parse_provider_reply("openai", 200,
                b'{"choices":[{"message":{"content":"b"}}]}'), "b")
        self.assertEqual(
            parse_provider_reply("gemini", 200,
                b'{"candidates":[{"content":{"parts":[{"text":"c"}]}}]}'), "c")

    def test_claude_is_alias_for_anthropic(self):
        url, _, _ = build_provider_request(
            "claude", "claude-opus-4-8", "https://api.anthropic.com", "k", "hi", None)
        self.assertTrue(url.endswith("/v1/messages"))


class TestStripCliWarnings(unittest.TestCase):
    def test_strips_unknown_toolsets_prefix(self):
        raw = (
            "Warning: Unknown toolsets: mcp-codegraph, messaging, moa\n"
            "Sounds like the name got cut off — this is... who?"
        )
        self.assertEqual(
            hb.strip_cli_warnings(raw),
            "Sounds like the name got cut off — this is... who?",
        )

    def test_strips_rich_markup_and_ansi(self):
        raw = (
            "\x1b[31m[bold red]Warning: Unknown toolsets: moa[/]\x1b[0m\n"
            "Got it — that's your wife."
        )
        self.assertEqual(
            hb.strip_cli_warnings(raw),
            "Got it — that's your wife.",
        )

    def test_leaves_normal_reply(self):
        self.assertEqual(
            hb.strip_cli_warnings("Got it — that's your wife."),
            "Got it — that's your wife.",
        )


class TestSpeakableSplit(unittest.TestCase):
    def test_holds_incomplete_sentence(self):
        chunk, rest = hb.split_speakable("Hey Andrew")
        self.assertEqual(chunk, "")
        self.assertEqual(rest, "Hey Andrew")

    def test_emits_first_sentence_only(self):
        chunk, rest = hb.split_speakable("Hey Andrew! I'm here — what do you need?")
        self.assertEqual(chunk, "Hey Andrew!")
        self.assertIn("I'm here", rest)

    def test_emits_complete_short_reply(self):
        chunk, rest = hb.split_speakable("ready.")
        self.assertEqual(chunk, "ready.")
        self.assertEqual(rest, "")

    def test_sse_delta_text(self):
        payload = {
            "choices": [{"delta": {"content": "Hey"}, "finish_reason": None}]
        }
        self.assertEqual(hb.sse_delta_text(payload), "Hey")
        self.assertEqual(hb.sse_delta_text({"choices": []}), "")
        self.assertEqual(hb.sse_delta_text({}), "")


class TestAgentModelChain(unittest.TestCase):
    def test_default_chain_is_flash_then_gemini(self):
        orig = (
            hb.HERMES_AGENT_MODEL, hb.HERMES_AGENT_PROVIDER,
            hb.HERMES_AGENT_FALLBACK_MODEL, hb.HERMES_AGENT_FALLBACK_PROVIDER,
        )
        hb.HERMES_AGENT_MODEL = "glm-5.3-flash"
        hb.HERMES_AGENT_PROVIDER = "zai"
        hb.HERMES_AGENT_FALLBACK_MODEL = "google/gemini-3.7-flash"
        hb.HERMES_AGENT_FALLBACK_PROVIDER = "openrouter"
        try:
            chain = hb.agent_model_chain()
            self.assertEqual(chain[0], ("glm-5.3-flash", "zai"))
            self.assertEqual(chain[1], ("google/gemini-3.7-flash", "openrouter"))
        finally:
            (hb.HERMES_AGENT_MODEL, hb.HERMES_AGENT_PROVIDER,
             hb.HERMES_AGENT_FALLBACK_MODEL, hb.HERMES_AGENT_FALLBACK_PROVIDER) = orig


class TestStreamHermesReplyModels(unittest.TestCase):
    def _pin_flash_chain(self):
        self.orig_api_fn = hb.ask_hermes_api
        self.orig_enabled = hb.HERMES_API_ENABLED
        self.orig_models = (
            hb.HERMES_AGENT_MODEL, hb.HERMES_AGENT_PROVIDER,
            hb.HERMES_AGENT_FALLBACK_MODEL, hb.HERMES_AGENT_FALLBACK_PROVIDER,
        )
        hb.HERMES_API_ENABLED = True
        hb.HERMES_AGENT_MODEL = "glm-5.3-flash"
        hb.HERMES_AGENT_PROVIDER = "zai"
        hb.HERMES_AGENT_FALLBACK_MODEL = "google/gemini-3.7-flash"
        hb.HERMES_AGENT_FALLBACK_PROVIDER = "openrouter"

    def _unpin(self):
        hb.ask_hermes_api = self.orig_api_fn
        hb.HERMES_API_ENABLED = self.orig_enabled
        (hb.HERMES_AGENT_MODEL, hb.HERMES_AGENT_PROVIDER,
         hb.HERMES_AGENT_FALLBACK_MODEL, hb.HERMES_AGENT_FALLBACK_PROVIDER) = self.orig_models

    def test_api_falls_through_chain_then_succeeds(self):
        self._pin_flash_chain()
        calls = []

        async def fake_api(text, photo, resume, on_text, model=None, provider=None, on_tool=None):
            calls.append((model, provider, resume))
            if model == "glm-5.3-flash":
                raise RuntimeError("primary down")
            await on_text("ok")
            return "ok", "sid-gem"

        hb.ask_hermes_api = fake_api
        try:
            async def collect(_piece):
                return None

            reply, session_id, path, used_model, used_provider = asyncio.run(
                hb.stream_hermes_reply("hi", None, None, None, None, collect)
            )
            self.assertEqual(
                [(m, p) for m, p, _r in calls],
                [("glm-5.3-flash", "zai"), ("google/gemini-3.7-flash", "openrouter")],
            )
            self.assertEqual(reply, "ok")
            self.assertEqual(session_id, "sid-gem")
            self.assertEqual(path, "api")
            self.assertEqual(used_model, "google/gemini-3.7-flash")
            self.assertEqual(used_provider, "openrouter")
        finally:
            self._unpin()

    def test_api_fallback_does_not_reuse_failed_session_id(self):
        self._pin_flash_chain()
        resumes = []

        async def fake_api(text, photo, resume, on_text, model=None, provider=None, on_tool=None):
            resumes.append((model, resume))
            if model == "glm-5.3-flash":
                raise RuntimeError("primary down")
            await on_text("ok")
            return "ok", "sid-gem"

        hb.ask_hermes_api = fake_api
        try:
            async def collect(_piece):
                return None

            asyncio.run(hb.stream_hermes_reply(
                "hi", None, None,
                "sid-flash", "api", collect,
                resume_model="glm-5.3-flash",
                resume_provider="zai",
            ))
            self.assertEqual(resumes, [
                ("glm-5.3-flash", "sid-flash"),
                ("google/gemini-3.7-flash", None),
            ])
        finally:
            self._unpin()

    def test_gemini_session_resumes_only_on_gemini(self):
        self._pin_flash_chain()
        resumes = []

        async def fake_api(text, photo, resume, on_text, model=None, provider=None, on_tool=None):
            resumes.append((model, resume))
            if model == "glm-5.3-flash":
                raise RuntimeError("primary down")
            await on_text("ok")
            return "ok", "sid-gem"

        hb.ask_hermes_api = fake_api
        try:
            async def collect(_piece):
                return None

            asyncio.run(hb.stream_hermes_reply(
                "hi", None, None,
                "sid-gem", "api", collect,
                resume_model="google/gemini-3.7-flash",
                resume_provider="openrouter",
            ))
            self.assertEqual(resumes, [
                ("glm-5.3-flash", None),
                ("google/gemini-3.7-flash", "sid-gem"),
            ])
        finally:
            self._unpin()

    def test_empty_flash_stream_falls_through_without_resume_leak(self):
        self._pin_flash_chain()
        resumes = []

        async def fake_api(text, photo, resume, on_text, model=None, provider=None, on_tool=None):
            resumes.append((model, resume))
            if model == "glm-5.3-flash":
                return None, "sid-flash-empty"
            await on_text("ok")
            return "ok", "sid-gem"

        hb.ask_hermes_api = fake_api
        try:
            async def collect(_piece):
                return None

            reply, session_id, path, used_model, _provider = asyncio.run(
                hb.stream_hermes_reply(
                    "hi", None, None,
                    "sid-flash", "api", collect,
                    resume_model="glm-5.3-flash",
                    resume_provider="zai",
                )
            )
            self.assertEqual(resumes, [
                ("glm-5.3-flash", "sid-flash"),
                ("google/gemini-3.7-flash", None),
            ])
            self.assertEqual(reply, "ok")
            self.assertEqual(session_id, "sid-gem")
            self.assertEqual(used_model, "google/gemini-3.7-flash")
        finally:
            self._unpin()

    def test_resume_for_pair_requires_exact_match(self):
        self.assertEqual(
            hb.resume_for_pair(
                "sid", "api", "glm-5.3-flash", "zai",
                "glm-5.3-flash", "zai", "api",
            ),
            "sid",
        )
        self.assertIsNone(hb.resume_for_pair(
            "sid", "api", "glm-5.3-flash", "zai",
            "google/gemini-3.7-flash", "openrouter", "api",
        ))
        self.assertIsNone(hb.resume_for_pair(
            "sid", "api", "glm-5.3-flash", "zai",
            "glm-5.3-flash", "zai", "cli",
        ))


if __name__ == "__main__":
    unittest.main()


class TestInheritedRoutingAndFailureSafety(unittest.TestCase):
    def test_empty_overrides_inherit_gateway_default(self):
        from unittest.mock import patch
        with patch.multiple(hb, HERMES_AGENT_MODEL='', HERMES_AGENT_PROVIDER='',
                            HERMES_AGENT_FALLBACK_MODEL='', HERMES_AGENT_FALLBACK_PROVIDER=''):
            self.assertEqual(hb.agent_model_chain(), [('', '')])

    def test_failed_cli_stdout_is_not_success(self):
        from unittest.mock import patch
        import subprocess
        result = subprocess.CompletedProcess([], 1, 'partial answer', 'failure')
        with patch.object(hb.subprocess, 'run', return_value=result):
            answer, sid = hb.ask_hermes('test')
        self.assertTrue(answer.startswith('Error:'))
        self.assertIsNone(sid)

    def test_tool_started_failure_never_retries(self):
        from unittest.mock import patch, AsyncMock, Mock
        async def run():
            async def fail(*args, **kwargs):
                await kwargs['on_tool']({'tool': 'write_file', 'status': 'running'})
                raise ConnectionError('stream lost')
            api = AsyncMock(side_effect=fail)
            cli = Mock()
            output = AsyncMock()
            with patch.object(hb, 'agent_model_chain', return_value=[('a','p'),('b','q')]), \
                 patch.object(hb, 'HERMES_API_ENABLED', True), \
                 patch.object(hb, 'ask_hermes_api', api), patch.object(hb, 'ask_hermes', cli):
                result = await hb.stream_hermes_reply('test', None, None, None, None, output)
            self.assertIn('check the action', result[0])
            self.assertEqual(api.await_count, 1)
            cli.assert_not_called()
        asyncio.run(run())
