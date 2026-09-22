import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_api import FakeWorkers, completed

from app.main import create_app
from app.modules.stt.engines.base import DiarizationResult
from app.modules.stt.engines.pyannote_engine import select_device
from app.modules.stt.progress import DiarizationProgress, write_progress
from app.modules.stt.repository import Repository
from app.modules.stt.schemas import Options
from app.modules.stt.settings import Settings
from app.modules.stt.workers import Workers


def test_device_prefers_available_gpu_and_honors_cpu_override():
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False),
                            backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)))
    assert select_device(torch) == 'mps'
    assert select_device(torch, 'cpu') == 'cpu'
    torch.cuda.is_available = lambda: True
    assert select_device(torch) == 'cuda'
    torch.cuda.is_available = lambda: False
    torch.backends.mps.is_available = lambda: False
    assert select_device(torch) == 'cpu'


def test_hook_clamps_padded_batches_and_never_fakes_clustering_percentage():
    messages = []
    hook = DiarizationProgress(messages.append, 'mps')
    hook.start()
    hook.hook('segmentation', None, completed=np.int64(24), total=np.int64(21))
    assert messages[-1]['diar_stage_percent'] == 100
    assert messages[-1]['diar_completed'] == 21
    hook.hook('embeddings', None, completed=8, total=8)
    assert messages[-1]['diar_stage'] == 2
    hook.hook('embeddings', object())
    assert messages[-1]['diar_stage'] == 3
    assert messages[-1]['diar_total'] == 0
    json.dumps(messages)  # no NumPy scalars or model tensors in IPC
    hook.finish()
    assert messages[-1]['diar_stage'] == 5


@pytest.mark.asyncio
async def test_worker_delivers_progress_before_completion_and_cleans_temp(tmp_path, monkeypatch):
    def infer(audio, options, progress_path):
        write_progress(progress_path, {'diar_stage': 2, 'diar_completed': 1})
        time.sleep(0.7)
        write_progress(progress_path, {'diar_stage': 5, 'diar_completed': 2})
        return DiarizationResult([], diagnostics={'device': 'mps'})

    monkeypatch.setattr('app.modules.stt.workers.infer', infer)
    worker = Workers.__new__(Workers)
    worker.progress_dir = tmp_path
    worker.pools = {'diar': ThreadPoolExecutor(max_workers=1)}
    worker.health = {'diar': {'models': {'diarization': {}}}}
    messages = []
    try:
        await worker.run('diar', np.zeros(1), {}, on_progress=messages.append)
        assert [m['diar_stage'] for m in messages] == [2, 5]
        assert not list(tmp_path.iterdir())
        assert worker.health['diar']['models']['diarization']['device'] == 'mps'
    finally:
        worker.close()


def test_restart_resumes_diarization_without_retranscribing(tmp_path):
    settings = Settings(engine='fake', data_dir=tmp_path)
    settings.prepare()
    repo = Repository(tmp_path / 'stt.sqlite3')
    s = repo.create('file', Options().model_dump(), {})
    sid = s['id']
    repo.state(sid, 'DIARIZING')
    repo.job('job_resume', sid, 'DIARIZING')
    repo.db.close()
    pcm = tmp_path / 'tmp' / (sid + '.f32')
    np.full(16000, 0.1, dtype='<f4').tofile(pcm)
    pcm.with_suffix('.diar.json').write_text(json.dumps({
        'generation': 1, 'jid': 'job_resume', 'words': [{'start': 0, 'end': 1, 'text': '보존된 대본'}],
        'diagnostics': {'duration_seconds': 1}, 'timings': {'asr_seconds': 3}, 'elapsed_seconds': 3,
    }))

    class ResumeWorkers(FakeWorkers):
        async def run(self, kind, audio, options, on_progress=None):
            assert kind == 'diar', 'Completed ASR must not run again'
            on_progress({'diar_stage': 2, 'diar_completed': 1, 'diar_total': 2, 'diar_device': 1})
            return await super().run(kind, audio, options, on_progress)

    with TestClient(create_app(settings, ResumeWorkers)) as client:
        client.headers['Authorization'] = 'Bearer ' + client.app.state.token
        client.app.state.access.owner(sid, 'superadmin')
        result = completed(client, sid)
        assert result['state'] == 'COMPLETED'
        assert result['utterances'][0]['text'] == '보존된 대본'
        assert result['metrics']['asr_seconds'] == 3
        assert result['metrics']['diar_device'] == 1
        assert not result['warnings']
        assert not list((tmp_path / 'tmp').iterdir())
