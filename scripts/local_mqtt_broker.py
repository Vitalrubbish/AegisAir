"""实验期间使用的本地匿名 MQTT broker 启动器。"""

from __future__ import annotations

import asyncio

from amqtt.broker import Broker


async def main() -> None:
    broker = Broker(
        {
            "listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:1883"}},
            "sys_interval": 10,
            "auth": {"allow-anonymous": True},
        }
    )
    await broker.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
