#!/usr/bin/env python3
"""输出 cross-geometry smoke 的 shell-safe 启动表。"""

from __future__ import annotations

import json
from pathlib import Path
import sys


manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for trial in manifest["trials"]:
    geometry = manifest["geometries"][trial["geometry_id"]]
    starts = {int(key): value for key, value in geometry["reset_starts"].items()}
    poses = ";".join(
        f"{drone}={-position[1]},{position[0]},0.5"
        for drone, position in sorted(starts.items())
    )
    origins = {
        drone: f"{position[0]},{-position[1]},0"
        for drone, position in starts.items()
    }
    print(
        trial["trial_id"],
        trial["seed"],
        trial["geometry_id"],
        geometry["world"],
        poses,
        origins[2],
        origins[3],
        sep="\t",
    )
