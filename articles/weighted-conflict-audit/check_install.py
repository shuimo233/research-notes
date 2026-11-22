"""Install a supplied 0.4.0 wheel offline and exercise the public interfaces outside the repo."""

import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import venv


def main(wheel):
    if not wheel.is_file():
        raise FileNotFoundError(wheel)
    readme = Path(__file__).resolve().parents[2] / "packages/stateful-identification/README.md"
    fence = chr(96)*3
    examples = re.findall(fence + r"python\n(.*?)" + fence, readme.read_text(encoding="utf-8"), re.S)
    if len(examples) != 3:
        raise ValueError("expected three executable Python examples")
    with TemporaryDirectory(prefix="audit-install-") as scratch:
        base = Path(scratch)
        env_dir = base / "env"
        venv.create(env_dir, with_pip=True)
        scripts = env_dir / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")

        def run(args, expected=0):
            result = subprocess.run(args, cwd=base, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if result.returncode != expected:
                raise RuntimeError((result.returncode, result.stdout, result.stderr))
            return result.stdout

        run([python, "-m", "pip", "--disable-pip-version-check", "install", "--no-index", "--no-deps", wheel])
        run([python, "-I", "-c", "\n".join(examples)])
        cli = scripts / ("stateful-audit.exe" if os.name == "nt" else "stateful-audit")
        inputs = ["problem.json", "claim.json"]
        assert json.loads(run([cli, *inputs]))["status"] == "verified"
        assert json.loads(run([cli, *inputs, "--max-nodes", "0"], 2))["status"] == "inconclusive"
        claim = json.loads((base/"claim.json").read_text(encoding="utf-8"))
        claim["cores"] = []
        (base/"claim.json").write_text(json.dumps(claim), encoding="utf-8")
        assert json.loads(run([cli, *inputs], 1))["status"] == "rejected"
        legacy = scripts / ("stateful-identify.exe" if os.name == "nt" else "stateful-identify")
        assert json.loads(run([legacy, "demo", "sqlite", "--truth", "FAIL"]))["candidates"] == ["FAIL"]
        print(platform.python_version(), wheel.name, "offline installation, 3 examples, both CLIs and 3 verdicts OK")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
