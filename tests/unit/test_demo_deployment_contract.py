"""Keep the process-local demo store inside its supported deployment topology."""

import json
import shlex
from pathlib import Path


def test_demo_deployment_pins_one_instance_and_one_worker():
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text()
    command_line = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))
    command = json.loads(command_line.removeprefix("CMD "))
    if command[:2] == ["sh", "-c"]:
        command = shlex.split(command[2])
    assert command[command.index("--workers") + 1] == "1"
    blueprint = (root / "render.yaml").read_text().splitlines()
    assert [line.strip() for line in blueprint if "numInstances:" in line] == ["numInstances: 1"]
    assert not any("scaling:" in line for line in blueprint)
