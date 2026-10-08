"""Start both local services; Ctrl+C stops them. Logs stay in .runtime/logs."""
from pathlib import Path
import os, socket, subprocess, sys, time
ROOT = Path(__file__).resolve().parents[1]
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
ports = [int(os.getenv('BACKEND_PORT', '8000')), int(os.getenv('UI_PORT', '8501'))]
for port in ports:
    with socket.socket() as connection:
        if connection.connect_ex(('127.0.0.1', port)) == 0:
            raise SystemExit(f'Port {port} is already in use. Stop the existing service first.')
logs = ROOT / '.runtime/logs'; logs.mkdir(parents=True, exist_ok=True)
flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
commands = [
    [sys.executable, '-m', 'uvicorn', 'main:app', '--app-dir', str(ROOT/'backend'), '--host', '127.0.0.1', '--port', str(ports[0])],
    [sys.executable, '-m', 'streamlit', 'run', str(ROOT/'ui/app.py'), '--server.address', '127.0.0.1', '--server.port', str(ports[1]), '--server.headless', 'true'],
]
processes=[];handles=[]
try:
    for name,command in zip(['backend','streamlit'],commands):
        handle=(logs/f'{name}.log').open('a',encoding='utf-8');handles.append(handle)
        processes.append(subprocess.Popen(command,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT,creationflags=flags))
    print(f'UI: http://localhost:{ports[1]} | API: http://localhost:{ports[0]}/docs', flush=True)
    print('Keep this terminal open. Ctrl+C stops both services.', flush=True)
    while all(process.poll() is None for process in processes):time.sleep(1)
    raise SystemExit('A service stopped. Inspect .runtime/logs for the cause.')
except KeyboardInterrupt:
    print('Stopping services.')
finally:
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    for handle in handles:handle.close()
