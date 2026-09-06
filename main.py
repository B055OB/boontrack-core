import sys
import os
import asyncio

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from app.main import app, start_application

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_application())
        loop.run_forever()
    except KeyboardInterrupt:
        print("[SHUTDOWN] Server stopped by user.", flush=True)
    finally:
        loop.stop()
        loop.close()
