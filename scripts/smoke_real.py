"""Run after model preparation. Output never implies diarization was verified."""
import json
import os
import platform
import sys
import time
from pathlib import Path
import importlib.metadata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
os.environ['PYANNOTE_METRICS_ENABLED']='0'
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
from app.modules.stt.audio import decode
from app.modules.stt.engines.mlx_whisper_engine import MLXWhisperEngine
from app.modules.stt.engines.silero_vad import SileroVAD

manifest=json.loads((ROOT/'.runtime/models/manifest.json').read_text())
audio,info=decode(ROOT/'.runtime/smoke/korean.wav',600)
t=time.perf_counter();engine=MLXWhisperEngine(manifest['small']['path']);load=time.perf_counter()-t
runs=[]
for _ in range(2):
    t=time.perf_counter();r=engine.transcribe(audio,{'language':'ko'});elapsed=time.perf_counter()-t
    runs.append({'seconds':elapsed,'rtf':elapsed/info['duration_seconds'],'words':len(r.words),'text':''.join(w.text for w in r.words)})
vad=SileroVAD();last=vad.feed(audio)
report={'fixture':'macOS Yuna Korean synthetic speech; not a real meeting or diarization accuracy benchmark',
        'platform':platform.platform(),'machine':platform.machine(),'model':manifest['small'],
        'packages':{n:importlib.metadata.version(n) for n in ['mlx-whisper','mlx','silero-vad','onnxruntime','pyannote.audio','torch','torchaudio']},
        'audio':info,'load_seconds':load,'runs':runs,'vad_last_speech_sample':last,
        'word_timestamps_valid':all(0<=w.start<=w.end<=len(audio)/16000+.1 for w in r.words),
        'diarization':'NOT RUN: Community-1 access and HF_TOKEN unavailable'}
(ROOT/'docs/real-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
