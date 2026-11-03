"""Local-only transport fixture; no provider, tool or private data required."""
import asyncio, json
import websockets
from urllib.parse import urlsplit

async def handle(ws):
    path = urlsplit(ws.request.path).path
    if path == '/bad':
        await ws.send(json.dumps({'type': 'error', 'message': 'not a welcome'}))
        return
    if path == '/slowwelcome':
        await asyncio.sleep(1)
        if ws.state.name != 'OPEN':
            return
    await ws.send(json.dumps({'type': 'welcome'}))
    async for raw in ws:
        data = json.loads(raw)
        if data.get('type') != 'query':
            continue
        print('query:' + path, flush=True)
        if path == '/drop':
            await ws.close(code=1011, reason='fixture disconnect')
            return
        await asyncio.sleep(65)
        await ws.send(json.dumps({'type': 'response_delta', 'text': 'Delayed reply.'}))
        await ws.send(json.dumps({'type': 'response', 'text': 'Delayed reply.', 'tts': False, 'streamed': True}))

async def main():
    async with websockets.serve(handle, '127.0.0.1', 19876):
        print('fixture ready', flush=True)
        await asyncio.Future()

asyncio.run(main())
