import asyncio
import websockets
import json

clients = set()

async def handler(websocket):
    clients.add(websocket)
    try:
        async for message in websocket:
            # ожидаем JSON: {"user": "...", "text": "..."}
            data = json.loads(message)
            # ретрансляция всем кроме отправителя
            for client in list(clients):
                if client != websocket:
                    await client.send(json.dumps(data))
    finally:
        clients.discard(websocket)

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8000):
        print("✅ Lite server listening at ws://0.0.0.0:8000")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
