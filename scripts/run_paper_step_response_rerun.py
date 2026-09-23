"""按论文冻结顺序重跑九条阶跃；仅管理自身进程，保留所有外置日志。"""
from pathlib import Path
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import argparse

ROOT = Path(__file__).resolve().parents[1]
OUT = Path('/Volumes/Expansion/Aegis/paper_full_rerun_20260921_441c8f1/01_step_response')
GATE = Path('/Users/lijiajun/Documents/ChatGPT/无人机论文尝试/safety_margin_scheduler_gate0')
DOCKER = '/Applications/Docker.app/Contents/Resources/bin/docker'
IMAGE = 'aegisair-px4-bridge:paper-rerun-441c8f1'
PY = sys.executable

def run(cmd, log, timeout=180):
    with log.open('w') as stream:
        result = subprocess.run(cmd, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'命令退出 {result.returncode}: {cmd}; 日志 {log}')

def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--spawn-pose', default='0,0,0.5', help='Gazebo 起点 x,y,z；单机自由阶跃必须避开 S1 的柱体')
    args = parser.parse_args()
    OUT = args.out
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT/'setup.json').write_text(json.dumps({'gazebo_spawn_pose': args.spawn_pose,
        'world': 'S1', 'settle_run_stop_s': [3,6,6], 'speeds_mps': [.5,1.,1.5]}))
    processes = []
    streams = []
    broker_name = 'aegisair-paper-rerun-broker'
    adapter_name = 'aegisair-paper-rerun-step'
    broker_created = False
    adapter_created = False
    try:
        if subprocess.run(['pgrep', '-x', 'px4'], stdout=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('已有 PX4 进程，拒绝端口混用')
        # 固定镜像内容和源码标识，保留实验时的依赖记录。
        run([DOCKER, 'image', 'inspect', IMAGE], OUT/'image.json')
        run([PY, '-m', 'pip', 'freeze'], OUT/'pip-freeze.txt')
        run(['git', 'rev-parse', 'HEAD'], OUT/'source_commit.txt')
        hashes = {}
        for base in (ROOT/'swarm', ROOT/'marllib', ROOT/'px4_adapter', ROOT/'scripts'):
            for path in base.rglob('*'):
                if path.is_file() and path.suffix in ('.py', '.sh', '.yaml'):
                    hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        (OUT/'source_hashes.json').write_text(json.dumps(hashes, indent=2))
        run([DOCKER, 'run', '-d', '--name', broker_name, '-p', '127.0.0.1:1883:1883',
             'eclipse-mosquitto:2', 'mosquitto', '-c', '/mosquitto-no-auth.conf'], OUT/'broker_start.log')
        broker_created = True
        for vx in (0.5, 1.0, 1.5):
            for rep in (1, 2, 3):
                label = f'step_v{vx}_r{rep}'
                print(f'START {label}', flush=True)
                processes = []
                for cmd, filename in (
                    ([PY, str(GATE/'scripts/gcs_heartbeat.py'), '--port', '18572', '--duration-s', '300'], 'heartbeat'),
                    (['bash', str(GATE/'scripts/launch_isolated_sitl.sh'), 'S1'], 'launch'),
                ):
                    stream = (OUT/f'{label}_{filename}.log').open('w'); streams.append(stream)
                    processes.append(subprocess.Popen(cmd, cwd=ROOT, env={**os.environ, 'PX4_GZ_MODEL_POSE': args.spawn_pose}, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True))
                launcher = processes[-1]
                launch_log = OUT/f'{label}_launch.log'
                deadline = time.monotonic()+100
                while time.monotonic() < deadline:
                    if launcher.poll() is not None:
                        raise RuntimeError(f'SITL 启动退出: {launch_log}')
                    if 'state_dir=' in launch_log.read_text():
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError(f'SITL 启动超时: {launch_log}')
                run([DOCKER, 'run', '-d', '--name', adapter_name, '--link', broker_name+':mqtt',
                     '-p', '127.0.0.1:8889:8889/udp', '-e', 'XRCE_UDP_PORT=8889',
                     '-e', 'ADAPTER_INSTANCES=2', '-e',
                     'ADAPTER_ARGS=--no-read-only --mqtt-host mqtt --mqtt-port 1883 --control-rate-hz 20 --telemetry-rate-hz 20',
                     IMAGE], OUT/f'{label}_adapter_start.log')
                adapter_created = True
                run([PY, str(ROOT/'scripts/wait_for_px4_telemetry.py'), '--drone-ids', '2', '--timeout-s', '90'], OUT/f'{label}_telemetry.log')
                run([PY, str(ROOT/'marllib/phase5_step_response.py'), '--vx', str(vx), '--settle-s', '3', '--run-s', '6', '--stop-s', '6', '--out', str(OUT/f'{label}.jsonl')], OUT/f'{label}_runner.log')
                run([DOCKER, 'logs', adapter_name], OUT/f'{label}_adapter.log')
                subprocess.run([DOCKER, 'rm', '-f', adapter_name], check=True, stdout=subprocess.DEVNULL)
                adapter_created = False
                for process in reversed(processes):
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=20)
                processes = []
                print(f'DONE {label}', flush=True)
        run([PY, str(ROOT/'scripts/analyze_px4_tau_identification.py'), '--input-dir', str(OUT), '--output', str(OUT/'tau_reanalysis.json')], OUT/'analysis.log')
        (OUT/'COMPLETE').touch()
    except Exception as exc:
        (OUT/'BLOCKED.txt').write_text(str(exc)+'\n')
        raise
    finally:
        if adapter_created:
            run([DOCKER, 'logs', adapter_name], OUT/'blocked_adapter.log')
            subprocess.run([DOCKER, 'rm', '-f', adapter_name], stdout=subprocess.DEVNULL)
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
        if broker_created:
            subprocess.run([DOCKER, 'logs', broker_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([DOCKER, 'rm', '-f', broker_name], stdout=subprocess.DEVNULL)
        for stream in streams:
            stream.close()

if __name__ == '__main__':
    main()
