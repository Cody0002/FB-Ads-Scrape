from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServiceConfig:
    service_name: str = "fb-ads-bot"
    app_user: str = "ubuntu"
    app_group: str = "ubuntu"
    working_dir: str = "/home/ubuntu/KZG_FB_Scraper"
    venv_python: str = "/home/ubuntu/KZG_FB_Scraper/.venv/bin/python"
    bind: str = "0.0.0.0:5000"
    workers: int = 1
    timeout: int = 120
    log_level: str = "info"
    env_file: str | None = "/home/ubuntu/KZG_FB_Scraper/.env"


def build_systemd_unit(cfg: ServiceConfig) -> str:
    """
    Build systemd unit content for main_app:app (Gunicorn).
    """
    env_line = f"EnvironmentFile={cfg.env_file}\n" if cfg.env_file else ""
    return (
        "[Unit]\n"
        "Description=FB Ads Scraper Bot (Gunicorn)\n"
        "After=network.target\n\n"
        "[Service]\n"
        f"User={cfg.app_user}\n"
        f"Group={cfg.app_group}\n"
        f"WorkingDirectory={cfg.working_dir}\n"
        f"{env_line}"
        "Environment=PYTHONUNBUFFERED=1\n"
        f"ExecStart={cfg.venv_python} -m gunicorn -w {cfg.workers} -b {cfg.bind} "
        f"--timeout {cfg.timeout} --log-level {cfg.log_level} main_app:app\n"
        "Restart=always\n"
        "RestartSec=5\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def write_unit_file(cfg: ServiceConfig, output_path: str | os.PathLike[str] | None = None) -> Path:
    """
    Write unit text to a local file and return the path.
    You can then copy it to /etc/systemd/system/<service_name>.service.
    """
    if output_path is None:
        output_path = Path.cwd() / f"{cfg.service_name}.service"
    out = Path(output_path)
    out.write_text(build_systemd_unit(cfg), encoding="utf-8")
    return out


def print_systemctl_steps(cfg: ServiceConfig, local_unit_path: Path) -> None:
    service_file = f"/etc/systemd/system/{cfg.service_name}.service"
    print("\nRun these commands on your server:")
    print(f"sudo cp {local_unit_path} {service_file}")
    print("sudo systemctl daemon-reload")
    print(f"sudo systemctl enable --now {cfg.service_name}")
    print(f"sudo systemctl status {cfg.service_name}")
    print(f"sudo journalctl -u {cfg.service_name} -f")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate systemd service for main_app.py")
    parser.add_argument("--service-name", default="fb-ads-bot")
    parser.add_argument("--user", default="ubuntu")
    parser.add_argument("--group", default="ubuntu")
    parser.add_argument("--working-dir", default="/home/ubuntu/KZG_FB_Scraper")
    parser.add_argument("--venv-python", default="/home/ubuntu/KZG_FB_Scraper/.venv/bin/python")
    parser.add_argument("--bind", default="0.0.0.0:5000")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--env-file", default="/home/ubuntu/KZG_FB_Scraper/.env")
    parser.add_argument("--out", default=None, help="Optional output path for generated unit file")
    args = parser.parse_args()

    cfg = ServiceConfig(
        service_name=args.service_name,
        app_user=args.user,
        app_group=args.group,
        working_dir=args.working_dir,
        venv_python=args.venv_python,
        bind=args.bind,
        workers=args.workers,
        timeout=args.timeout,
        log_level=args.log_level,
        env_file=args.env_file or None,
    )

    unit_path = write_unit_file(cfg, args.out)
    print(f"Generated: {unit_path}")
    print_systemctl_steps(cfg, unit_path)


if __name__ == "__main__":
    main()
