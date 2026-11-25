"""Start the local services; Ctrl+C stops them. Logs stay in .runtime/logs.

Two processes are started: the FastAPI backend (for the programmatic routes and
`/docs`) and the Streamlit UI. The UI no longer *depends* on the backend -- since
Phase 6 it calls the services in process -- but the API stays available because
ADR 0009 keeps it and `/docs` is genuinely useful for inspecting a run.

    start.py            start both services (foreground; Ctrl+C stops them)
    start.py --status   report whether the services this launcher started are running
    start.py --stop     stop only the processes this launcher started

The launcher records the PIDs it started in ``.runtime/services.json``. ``--stop``
verifies each PID still belongs to this project (its command line names uvicorn or
streamlit and the repository path) before terminating it, and never touches an
unrelated listener on the same port.
"""
from pathlib import Path
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PID_FILE_NAME = 'services.json'
_MARKERS = ('uvicorn', 'streamlit')


def pid_file(root: Path = ROOT) -> Path:
    return root / '.runtime' / PID_FILE_NAME


def write_pids(root: Path, services: dict) -> None:
    path = pid_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(services, indent=2), encoding='utf-8')


def read_pids(root: Path = ROOT) -> dict:
    try:
        data = json.loads(pid_file(root).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: pid for name, pid in data.items() if isinstance(pid, int) and pid > 0}


def command_line(pid: int) -> str:
    """The command line of ``pid`` as text, or '' if the process is gone or unreadable."""
    try:
        if sys.platform == 'win32':
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command',
                 f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine'],
                capture_output=True, text=True, encoding='utf-8', timeout=20,
            )
        else:
            proc_cmdline = Path(f'/proc/{int(pid)}/cmdline')
            if proc_cmdline.exists():
                return proc_cmdline.read_bytes().replace(b'\0', b' ').decode('utf-8', 'replace').strip()
            result = subprocess.run(
                ['ps', '-p', str(int(pid)), '-o', 'command='],
                capture_output=True, text=True, encoding='utf-8', timeout=20,
            )
    except (OSError, subprocess.SubprocessError):
        return ''
    return result.stdout.strip() if result.returncode == 0 else ''


def is_ours(pid: int, root: Path = ROOT, get_command_line=command_line) -> bool:
    """True only if ``pid`` is a uvicorn/streamlit process started from this repository."""
    text = get_command_line(pid).lower()
    if not text:
        return False
    repo = str(root).lower()
    repo_alt = repo.replace('\\', '/')
    return any(m in text for m in _MARKERS) and (repo in text or repo_alt in text.replace('\\', '/'))


def terminate(pid: int, run=subprocess.run, kill=os.kill) -> None:
    if sys.platform == 'win32':
        run(['taskkill', '/PID', str(int(pid)), '/T', '/F'], capture_output=True, check=False)
    else:
        kill(int(pid), signal.SIGTERM)


def status(root: Path = ROOT, get_command_line=command_line, out=print) -> int:
    services = read_pids(root)
    if not services:
        out('No services recorded by this launcher.')
        return 1
    running = 0
    for name, pid in services.items():
        if is_ours(pid, root, get_command_line):
            running += 1
            out(f'{name}: running (pid {pid})')
        else:
            out(f'{name}: not running (recorded pid {pid} is gone or is not ours)')
    return 0 if running else 1


def stop(root: Path = ROOT, get_command_line=command_line, terminator=terminate, out=print) -> int:
    services = read_pids(root)
    if not services:
        out('No services recorded by this launcher; nothing to stop.')
        return 0
    for name, pid in services.items():
        if is_ours(pid, root, get_command_line):
            terminator(pid)
            out(f'{name}: stopped (pid {pid})')
        else:
            out(f'{name}: pid {pid} is not a process this launcher started; left alone')
    try:
        pid_file(root).unlink()
    except OSError:
        pass
    return 0


def load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise SystemExit(
            'The python-dotenv package is missing: this is not the project environment.\n'
            'Run scripts/setup.py once, then start with the virtual-environment interpreter:\n'
            '  macOS / Linux:  .venv/bin/python scripts/start.py\n'
            '  Windows:        .venv\\Scripts\\python.exe scripts\\start.py'
        )
    load_dotenv(ROOT / '.env')


def start() -> None:
    load_environment()
    ports = [int(os.getenv('BACKEND_PORT', '8000')), int(os.getenv('UI_PORT', '8501'))]
    for port in ports:
        with socket.socket() as connection:
            if connection.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(
                    f'Port {port} is already in use. Stop the existing service first '
                    f'(`{Path(sys.executable).name} scripts/start.py --stop` stops one this launcher started).'
                )
    logs = ROOT / '.runtime/logs'
    logs.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    commands = [
        [sys.executable, '-m', 'uvicorn', 'main:app', '--app-dir', str(ROOT / 'backend'), '--host', '127.0.0.1', '--port', str(ports[0])],
        [sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'ui/app.py'), '--server.address', '127.0.0.1', '--server.port', str(ports[1]), '--server.headless', 'true'],
    ]
    processes = []
    handles = []
    try:
        for name, command in zip(['backend', 'streamlit'], commands):
            handle = (logs / f'{name}.log').open('a', encoding='utf-8')
            handles.append(handle)
            processes.append(subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, creationflags=flags))
        write_pids(ROOT, {'backend': processes[0].pid, 'streamlit': processes[1].pid})
        print(f'UI:  http://localhost:{ports[1]}', flush=True)
        print(f'API: http://localhost:{ports[0]}/docs', flush=True)
        print('Keep this terminal open. Ctrl+C stops both services.', flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise SystemExit('A service stopped. Inspect .runtime/logs for the cause.')
    except KeyboardInterrupt:
        print('Stopping services.')
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for handle in handles:
            handle.close()
        try:
            pid_file(ROOT).unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Start, inspect or stop the local services.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--status', action='store_true', help='show whether the services this launcher started are running')
    group.add_argument('--stop', action='store_true', help='stop the services this launcher started')
    args = parser.parse_args(argv)
    if args.status:
        return status()
    if args.stop:
        return stop()
    start()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
