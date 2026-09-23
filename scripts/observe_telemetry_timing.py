"""只读记录 MQTT 遥测到达时刻与上游时间戳，用于基础设施排查。"""
import argparse
import json
import signal
import time
import paho.mqtt.client as mqtt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    running=True
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    with open(args.out,'x',buffering=1) as stream:
        client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='aegisair-timing-observer')
        def connected(c,*_):
            c.subscribe('swarm/drone/+/telemetry',qos=0)
        def received(c,u,msg):
            arrival=time.time_ns()//1_000_000
            try:
                payload=json.loads(msg.payload)
                record={k:payload.get(k) for k in ('drone','timestamp_ms','source_timestamp_us')}
                record.update(arrival_ms=arrival,arrival_monotonic_ns=time.monotonic_ns())
                stream.write(json.dumps(record)+'\n')
            except (ValueError,TypeError):
                return
        client.on_connect=connected
        client.on_message=received
        client.connect('127.0.0.1',1883,keepalive=15)
        client.loop_start()
        try:
            while running:
                time.sleep(.2)
        finally:
            client.loop_stop()
            client.disconnect()


if __name__=='__main__':
    main()
