"""Synthetic, paced websocket smoke; never opens the user's microphone."""
import asyncio
import json
import struct
import sys
from pathlib import Path
import httpx
import numpy as np
import soxr
import websockets
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.modules.stt.audio import decode

async def main():
    token=(ROOT/'.runtime/local-token').read_text().strip()
    audio,_=decode(ROOT/'.runtime/smoke/korean.wav',600)
    audio=soxr.resample(audio,16000,44100).astype('<f4')
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token}) as client:
        r=await client.post('http://127.0.0.1:8765/api/stt/sessions',json={});r.raise_for_status();sid=r.json()['id']
    async with websockets.connect(f'ws://127.0.0.1:8765/api/stt/sessions/{sid}/stream',origin='http://127.0.0.1:5173',subprotocols=['stt','stt.'+token]) as ws:
        await ws.send(json.dumps({'type':'start','stream_id':'synthetic-smoke','sample_rate':44100}))
        while True:
            message=json.loads(await ws.recv())
            if message['type']=='ack' and message.get('action')=='start':break
            if message['type']=='error':raise RuntimeError(message)
        async def send():
            sequence=-1
            for sequence,start in enumerate(range(0,len(audio),6615)):
                chunk=audio[start:start+6615]
                await ws.send(struct.pack('<IQI',sequence,start,len(chunk))+chunk.tobytes())
                await asyncio.sleep(len(chunk)/44100)
            await ws.send(json.dumps({'type':'stop','last_sequence':sequence}))
        task=asyncio.create_task(send())
        snapshots=[]
        async with asyncio.timeout(60):
            while True:
                message=json.loads(await ws.recv())
                if message['type']=='snapshot':snapshots.append(message['session'])
                if message['type']=='error':raise RuntimeError(message)
                if message['type']=='completed':break
        await task
    final=snapshots[-1]
    result={'fixture':'Paced 44.1kHz PCM from synthetic Korean audio; no hardware microphone',
            'session_id':sid,'state':final['state'],'metrics':final['metrics'],
            'had_partial_caption':any(any(u['status']=='partial' for u in s['utterances']) for s in snapshots),
            'final_text':' '.join(u['text'] for u in final['utterances']),
            'utterances':final['utterances'],'warnings':final['warnings']}
    (ROOT/'docs/real-stream-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='utterances'},ensure_ascii=False,indent=2))

asyncio.run(main())
