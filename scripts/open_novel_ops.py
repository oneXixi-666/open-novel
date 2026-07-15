from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from open_novel.agents.detection import AgentDetectionService
from open_novel.core.backup import ProjectBackupService
from open_novel.core.project import ProjectService


def main() -> None:
    parser = argparse.ArgumentParser(description="Open Novel local operations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--project", type=Path)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--project", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify-backup")
    verify.add_argument("--backup", type=Path, required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    service = ProjectBackupService()
    if args.command == "doctor":
        result = {
            "status": "passed",
            "python": shutil.which("python3") or "",
            "agents": [
                item.model_dump(mode="json") for item in AgentDetectionService().detect_all()
            ],
        }
        if args.project:
            project = ProjectService().open_project(args.project)
            result["project"] = {"root": project.root.as_posix(), "title": project.metadata.title}
    elif args.command == "backup":
        result = service.create(args.project, args.output)
    elif args.command == "verify-backup":
        result = service.verify(args.backup)
    else:
        result = service.restore(args.backup, args.destination, overwrite=args.overwrite)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
