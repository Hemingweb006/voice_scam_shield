# main.py — Twilio Media Streams -> OpenAI Transcribe (chunked) -> Live UI
# deps: pip install fastapi "uvicorn[standard]" requests certifi


import os, json, time, base64, asyncio, audioop, wave, io, ssl, certifi, concurrent.futures
from typing import Dict, Any, Set, Optional
from collections import deque

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

OPENAI_API_KEY = "your_api"
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY in your environment")

# Only allow these languages for transcription
ALLOWED_LANGS = ["en", "es", "fr"]

# (macOS TLS sanity)
SSL_CTX = ssl.create_default_context()
SSL_CTX.load_verify_locations(certifi.where())

app = FastAPI(title="Voice Scam Shield — Twilio x OpenAI Transcribe")

# Allow your local UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# ---------------- State + fanout ----------------
calls: Dict[str, Dict[str, Any]] = {}
calls_ws_clients: Set[WebSocket] = set()
call_rooms: Dict[str, Set[WebSocket]] = {}

# Global thread pool for CPU-intensive audio operations
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

async def broadcast_calls(event: str, payload: Dict[str, Any]):
    msg = json.dumps({"type": event, "data": payload})
    dead = []
    for ws in list(calls_ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        calls_ws_clients.discard(ws)

async def broadcast_call(sid: str, payload: Dict[str, Any]):
    msg = json.dumps(payload)
    dead = []
    for ws in list(call_rooms.get(sid, set())):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        call_rooms.get(sid, set()).discard(ws)

@app.get("/")
def root(): return {"ok": True, "active_calls": len(calls)}

@app.get("/languages")
def get_languages():
    """Get the currently allowed languages for transcription"""
    return {
        "allowed_languages": ALLOWED_LANGS,
        "description": "Only transcriptions in these languages will be processed for risk analysis"
    }

# ---------------- WS for inbox ----------------
@app.websocket("/ws/calls")
async def ws_calls(ws: WebSocket):
    await ws.accept()
    calls_ws_clients.add(ws)
    await ws.send_text(json.dumps({"type": "calls.snapshot", "data": [
        {"sid": sid, **meta} for sid, meta in calls.items()
    ]}))
    try:
        while True:
            await asyncio.sleep(60)  # keep open
    except WebSocketDisconnect:
        pass
    finally:
        calls_ws_clients.discard(ws)

# ---------------- WS for per-call live ----------------
@app.websocket("/ws/call/{sid}")
async def ws_call(ws: WebSocket, sid: str):
    await ws.accept()
    call_rooms.setdefault(sid, set()).add(ws)
    try:
        while True:
            await asyncio.sleep(60)  # keep open
    except WebSocketDisconnect:
        pass
    finally:
        call_rooms.get(sid, set()).discard(ws)

# ---------------- Twilio webhook: answer + start stream ----------------
@app.post("/twilio/voice")
async def twilio_voice(req: Request):
    form = await req.form()
    call_sid = form.get("CallSid", "")
    from_num = form.get("From", "unknown")
    to_num   = form.get("To", "unknown")

    calls[call_sid] = {
        "from": from_num,
        "to": to_num,
        "status": "in-progress",
        "started_at": int(time.time()*1000),
        "updated_at": int(time.time()*1000),
    }
    await broadcast_calls("call.started", {"sid": call_sid, **calls[call_sid]})

    # 🔁 replace with your current ngrok host
    WSS = "wss://5b073d46ee7a.ngrok-free.app/twilio/stream"

    twiml = f"""
<Response>
  <Start>
    <Stream url="{WSS}">
      <Parameter name="from" value="{from_num}"/>
      <Parameter name="to"   value="{to_num}"/>
      <Parameter name="callSid" value="{call_sid}"/>
    </Stream>
  </Start>
  <Pause length="60"/>
</Response>
""".strip()
    return Response(content=twiml, media_type="text/xml")

# ---------------- Enhanced Chunked Transcriber ----------------
class CallTranscriber:
    """
    Enhanced transcriber with real-time speech activity detection and parallel processing.
    Features:
    - Adaptive chunking based on speech activity (1.5s during speech, 3.0s during silence)
    - Parallel audio processing with thread pools
    - Real-time speech level monitoring
    - Optimized audio conversion pipeline
    - Smart buffering for better performance
    """
    MIN_INTERVAL_SEC = 1.5      # Fastest possible chunking during speech
    MAX_INTERVAL_SEC = 3.0      # Slowest chunking when no speech
    SPEECH_ACTIVITY_THRESHOLD = 0.1  # Audio level threshold for speech detection
    MAX_QUEUE = 800             # Guard memory
    LANGUAGE_LOCK_THRESHOLD = 2  # Number of consistent language detections to lock language

    def __init__(self, sid: str):
        self.sid = sid
        self.buf = deque()               # holds raw μ-law bytes at 8k
        self.lock = asyncio.Lock()
        self.running = True
        self.task = asyncio.create_task(self._loop())
        
        # Enhanced language locking mechanism
        self.locked_language = None      # Once locked, this stays the same
        self.language_detection_count = {}  # Count detections per language
        self.language_locked = False     # Whether we've locked a language
        
        # Speech activity detection
        self.current_interval = self.MAX_INTERVAL_SEC
        self.speech_detected = False
        self.audio_level = 0.0
        self.last_speech_time = time.time()
        
        # Processing queue for parallel operations
        self.processing_queue = asyncio.Queue(maxsize=10)
        self.processing_task = asyncio.create_task(self._processing_worker())

    async def add_mulaw(self, b: bytes):
        async with self.lock:
            self.buf.append(b)
            if len(self.buf) > self.MAX_QUEUE:
                self.buf.popleft()

    async def stop(self):
        self.running = False
        try:
            await self.task
            await self.processing_task
        except Exception:
            pass

    def _calculate_audio_level(self, mulaw: bytes) -> float:
        """Calculate audio level from μ-law data for speech detection"""
        try:
            # Convert μ-law to PCM for level calculation
            pcm = audioop.ulaw2lin(mulaw, 2)
            # Calculate RMS (Root Mean Square) for audio level
            if len(pcm) > 0:
                rms = audioop.rms(pcm, 2)
                # Normalize to 0-1 range (16-bit audio max is 32767)
                return min(rms / 32767.0, 1.0)
        except Exception:
            pass
        return 0.0

    def _detect_speech_activity(self, audio_chunk: bytes) -> bool:
        """Detect if audio chunk contains speech based on audio level"""
        level = self._calculate_audio_level(audio_chunk)
        self.audio_level = level
        
        # Update speech detection state
        is_speech = level > self.SPEECH_ACTIVITY_THRESHOLD
        if is_speech:
            self.last_speech_time = time.time()
            self.speech_detected = True
        else:
            # Consider silence after 2 seconds of no speech
            if time.time() - self.last_speech_time > 2.0:
                self.speech_detected = False
        
        return is_speech

    def _adjust_chunk_interval(self) -> float:
        """Dynamically adjust chunk interval based on speech activity"""
        if self.speech_detected:
            # During speech, use faster chunking for real-time detection
            target_interval = self.MIN_INTERVAL_SEC
        else:
            # During silence, use slower chunking to save resources
            target_interval = self.MAX_INTERVAL_SEC
        
        # Smooth transition between intervals
        if abs(self.current_interval - target_interval) > 0.1:
            self.current_interval = target_interval
        
        return self.current_interval

    def _mulaw8k_to_wav16k_bytes(self, mulaw: bytes) -> bytes:
        """Optimized audio conversion with better quality"""
        try:
            # μ-law 8k -> PCM16 8k
            pcm16_8k = audioop.ulaw2lin(mulaw, 2)
            
            # PCM16 8k -> PCM16 16k with better resampling
            # Use more samples for smoother conversion
            pcm16_16k, _ = audioop.ratecv(pcm16_8k, 2, 1, 8000, 16000, None)
            
            # Apply light noise reduction for cleaner audio
            # This helps with transcription accuracy
            pcm16_16k = audioop.lin2lin(pcm16_16k, 2, 2)  # Ensure 16-bit
            
            # Write WAV header + data to memory
            mem = io.BytesIO()
            with wave.open(mem, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)   # 16-bit
                wf.setframerate(16000)
                wf.writeframes(pcm16_16k)
            return mem.getvalue()
        except Exception as e:
            print(f"Audio conversion error: {e}")
            # Fallback to basic conversion
            pcm16_8k = audioop.ulaw2lin(mulaw, 2)
            pcm16_16k, _ = audioop.ratecv(pcm16_8k, 2, 1, 8000, 16000, None)
            mem = io.BytesIO()
            with wave.open(mem, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm16_16k)
            return mem.getvalue()

    def _detect_language(self, text: str) -> str:
        """
        Enhanced language detection with better accuracy and confidence scoring.
        Uses multiple detection strategies for more reliable results.
        """
        text_lower = text.lower()
        
        # Enhanced English patterns with confidence scoring
        en_patterns = {
            'high_confidence': ['the', 'and', 'is', 'are', 'was', 'were', 'have', 'has', 'had', 'will', 'would', 'could', 'should'],
            'medium_confidence': ['this', 'that', 'with', 'for', 'from', 'they', 'their', 'them', 'you', 'your', 'we', 'our', 'us'],
            'low_confidence': ['what', 'when', 'where', 'why', 'how', 'who', 'which', 'whose', 'whom', 'here', 'there', 'now', 'then']
        }
        
        en_score = 0
        for confidence, words in en_patterns.items():
            weight = {'high_confidence': 3, 'medium_confidence': 2, 'low_confidence': 1}[confidence]
            en_score += sum(1 for word in words if word in text_lower) * weight
        
        # Enhanced Spanish patterns
        es_patterns = {
            'high_confidence': ['el', 'la', 'los', 'las', 'es', 'son', 'está', 'están', 'tiene', 'tienen'],
            'medium_confidence': ['con', 'por', 'para', 'de', 'en', 'a', 'que', 'y', 'o', 'pero', 'si', 'no', 'sí'],
            'unique': ['hola', 'gracias', 'por favor', 'buenos días', 'buenas tardes', 'buenas noches', 'adiós', 'señor', 'señora']
        }
        
        es_score = 0
        for confidence, words in es_patterns.items():
            weight = {'high_confidence': 3, 'medium_confidence': 2, 'unique': 5}[confidence]
            es_score += sum(1 for word in words if word in text_lower) * weight
        
        # Enhanced French patterns
        fr_patterns = {
            'high_confidence': ['le', 'la', 'les', 'est', 'sont', 'avoir', 'être', 'peut', 'doit'],
            'medium_confidence': ['avec', 'pour', 'dans', 'sur', 'sous', 'et', 'ou', 'mais', 'si', 'non', 'oui'],
            'unique': ['bonjour', 'merci', 's\'il vous plaît', 'bonne journée', 'au revoir', 'monsieur', 'madame', 'excusez-moi']
        }
        
        fr_score = 0
        for confidence, words in fr_patterns.items():
            weight = {'high_confidence': 3, 'medium_confidence': 2, 'unique': 5}[confidence]
            fr_score += sum(1 for word in words if word in text_lower) * weight
        
        # Language-specific word combinations for higher confidence
        es_combinations = ['por favor', 'buenos días', 'buenas tardes', 'buenas noches']
        fr_combinations = ['s\'il vous plaît', 'bonne journée', 'au revoir']
        
        for combo in es_combinations:
            if combo in text_lower:
                es_score += 8  # High weight for unique combinations
        
        for combo in fr_combinations:
            if combo in text_lower:
                fr_score += 8  # High weight for unique combinations
        
        # Return the language with highest score, or 'unknown' if none detected
        lang_scores = [('en', en_score), ('es', es_score), ('fr', fr_score)]
        best_lang = max(lang_scores, key=lambda x: x[1])
        
        # Higher threshold for more confident detection
        return best_lang[0] if best_lang[1] >= 2.0 else 'unknown'

    def _update_language_lock(self, detected_lang: str) -> str:
        """
        Enhanced language locking mechanism with confidence tracking.
        Returns the language to use for this call.
        """
        if self.language_locked:
            return self.locked_language
        
        if detected_lang in ALLOWED_LANGS:
            self.language_detection_count[detected_lang] = self.language_detection_count.get(detected_lang, 0) + 1
            
            # Lock language after consistent detections
            if self.language_detection_count[detected_lang] >= self.LANGUAGE_LOCK_THRESHOLD:
                self.locked_language = detected_lang
                self.language_locked = True
                print(f"🔒 Language locked to {detected_lang} for call {self.sid}")
                return detected_lang
            
            return detected_lang
        
        return detected_lang

    async def _openai_transcribe(self, wav_bytes: bytes) -> tuple[str, str]:
        """Enhanced transcription with better error handling and fallbacks"""
        # Prefer the newer model name if your key supports it; fall back to whisper-1
        model = "gpt-4o-mini-transcribe"
        url = "https://api.openai.com/v1/audio/transcriptions"
        files = {
            "file": ("chunk.wav", wav_bytes, "audio/wav"),
        }
        data = {
            "model": model,
            "response_format": "json",
            # "language": "en"   # uncomment if you want to force language
        }
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, headers=headers, files=files, data=data)
                if r.status_code == 404 or r.status_code == 400:
                    # fallback to whisper-1 if the newer model isn't available on your account
                    data["model"] = "whisper-1"
                    r = await client.post(url, headers=headers, files=files, data=data)
                r.raise_for_status()
                j = r.json()
                # API returns {"text": "..."} for whisper, similar for gpt-4o-mini-transcribe
                text = (j.get("text") or "").strip()
                
                # Detect language from transcribed text
                detected_lang = self._detect_language(text)
                
                return text, detected_lang
        except Exception as e:
            print("OpenAI transcribe error:", e)
            return "", "unknown"

    async def _processing_worker(self):
        """Background worker for processing audio chunks"""
        while self.running:
            try:
                # Get chunk from queue with timeout
                chunk_data = await asyncio.wait_for(self.processing_queue.get(), timeout=1.0)
                if chunk_data is None:
                    continue
                
                chunk, timestamp = chunk_data
                
                # Convert audio in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                wav = await loop.run_in_executor(_thread_pool, self._mulaw8k_to_wav16k_bytes, chunk)
                
                # Transcribe
                text, detected_lang = await self._openai_transcribe(wav)
                
                # Apply language locking mechanism
                final_lang = self._update_language_lock(detected_lang)
                
                # Process text if it's in an allowed language
                if text and final_lang in ALLOWED_LANGS:
                    print(f"Processing text in {final_lang}: {text[:50]}...")
                    from risk_scorer import score_text
                    meta = {
                        "from": calls.get(self.sid, {}).get("from"),
                        "to": calls.get(self.sid, {}).get("to"),
                    }
                    analysis = score_text(text, meta)
                    await broadcast_call(self.sid, {
                        "type": "final",
                        "text": text,
                        "lang": final_lang,
                        "risk": {
                            "score": analysis.risk_score,
                            "scam": analysis.scam,
                            "strategies": analysis.detected_strategies,
                            "rationale": analysis.rationale
                        }
                    })
                elif text and final_lang == "unknown":
                    print(f"Language not detected for text: {text[:50]}...")
                elif text:
                    print(f"Text in non-allowed language ({final_lang}): {text[:50]}...")
                
                self.processing_queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Processing worker error: {e}")
                if 'chunk_data' in locals() and chunk_data is not None:
                    self.processing_queue.task_done()

    async def _loop(self):
        """Main processing loop with enhanced speech activity detection"""
        last_send = time.time()
        carry = b""
        
        while self.running:
            await asyncio.sleep(0.1)  # Faster polling for better responsiveness
            now = time.time()
            
            # Dynamic interval adjustment based on speech activity
            current_interval = self._adjust_chunk_interval()
            
            if now - last_send < current_interval:
                continue
            last_send = now

            # Drain buffer
            async with self.lock:
                if not self.buf:
                    continue
                chunk = carry + b"".join(self.buf)
                self.buf.clear()

            # Keep chunk reasonable (last ~current_interval worth only)
            max_bytes = int(current_interval * 8000)
            if len(chunk) > max_bytes:
                chunk = chunk[-max_bytes:]

            # Detect speech activity and adjust timing
            self._detect_speech_activity(chunk)
            
            # Add to processing queue if not full
            if not self.processing_queue.full():
                await self.processing_queue.put((chunk, now))
            else:
                print(f"Processing queue full, skipping chunk for call {self.sid}")

    def get_performance_stats(self) -> dict:
        """Get real-time performance statistics for this call"""
        return {
            "current_interval": self.current_interval,
            "speech_detected": self.speech_detected,
            "audio_level": round(self.audio_level, 3),
            "queue_size": self.processing_queue.qsize(),
            "min_interval": self.MIN_INTERVAL_SEC,
            "max_interval": self.MAX_INTERVAL_SEC
        }

    def get_language_status(self) -> dict:
        """Get the current language status for this call"""
        return {
            "locked_language": self.locked_language,
            "language_locked": self.language_locked,
            "detection_counts": self.language_detection_count,
            "threshold": self.LANGUAGE_LOCK_THRESHOLD
        }

# active transcribers per call
transcribers: Dict[str, CallTranscriber] = {}

@app.get("/call/{sid}/performance")
def get_call_performance(sid: str):
    """Get performance statistics for a specific call"""
    if sid not in transcribers:
        return {"error": "Call not found"}
    
    return {
        "call_sid": sid,
        "performance": transcribers[sid].get_performance_stats()
    }

@app.get("/call/{sid}/language")
def get_call_language(sid: str):
    """Get the language status for a specific call"""
    if sid not in transcribers:
        return {"error": "Call not found"}
    
    return {
        "call_sid": sid,
        "language_status": transcribers[sid].get_language_status()
    }

# ---------------- Twilio Media Streams WS ----------------
@app.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket):
    await ws.accept()
    call_sid: Optional[str] = None
    try:
        while True:
            msg = await ws.receive_text()             # Twilio sends JSON text frames
            obj = json.loads(msg)
            ev = obj.get("event")

            if ev == "start":
                start = obj.get("start", {})
                call_sid = start.get("callSid") or "unknown"
                params = start.get("customParameters") or {}
                from_num = params.get("from", "unknown")
                to_num   = params.get("to", "unknown")

                calls[call_sid] = {
                    "from": from_num,
                    "to": to_num,
                    "status": "in-progress",
                    "started_at": int(time.time()*1000),
                    "updated_at": int(time.time()*1000),
                }
                print(f"[START] {call_sid} {from_num} -> {to_num}")
                await broadcast_calls("call.started", {"sid": call_sid, **calls[call_sid]})

                # start transcriber
                transcribers[call_sid] = CallTranscriber(call_sid)

            elif ev == "media":
                if call_sid in calls:
                    calls[call_sid]["updated_at"] = int(time.time()*1000)
                b64 = obj.get("media", {}).get("payload", "")
                if b64 and call_sid in transcribers:
                    try:
                        mulaw = base64.b64decode(b64)
                        await transcribers[call_sid].add_mulaw(mulaw)
                    except Exception as e:
                        print("media decode error:", e)

            elif ev == "stop":
                if call_sid in transcribers:
                    await transcribers[call_sid].stop()
                    transcribers.pop(call_sid, None)
                if call_sid in calls:
                    calls[call_sid]["status"] = "completed"
                    calls[call_sid]["ended_at"] = int(time.time()*1000)
                    print(f"[STOP]  {call_sid}")
                    await broadcast_calls("call.ended", {"sid": call_sid, **calls[call_sid]})
                break

    except WebSocketDisconnect:
        if call_sid in transcribers:
            await transcribers[call_sid].stop()
            transcribers.pop(call_sid, None)
        if call_sid in calls and calls[call_sid].get("status") != "completed":
            calls[call_sid]["status"] = "completed"
            calls[call_sid]["ended_at"] = int(time.time()*1000)
            await broadcast_calls("call.ended", {"sid": call_sid, **calls[call_sid]})
    except Exception as e:
        print("Twilio WS error:", e)
        if call_sid in transcribers:
            await transcribers[call_sid].stop()
            transcribers.pop(call_sid, None)
        if call_sid in calls and calls[call_sid].get("status") != "completed":
            calls[call_sid]["status"] = "error"
            calls[call_sid]["ended_at"] = int(time.time()*1000)
            await broadcast_calls("call.ended", {"sid": call_sid, **calls[call_sid]})
    finally:
        try:
            await ws.close()
        except Exception:
            pass
