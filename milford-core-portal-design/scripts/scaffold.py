#!/usr/bin/env python3
import argparse
import shutil
from pathlib import Path

parser = argparse.ArgumentParser(description="Copy a self-contained Milford portal template.")
parser.add_argument("template", choices=("login", "portal"))
parser.add_argument("destination")
args = parser.parse_args()

skill = Path(__file__).resolve().parent.parent
dest = Path(args.destination).expanduser().resolve()
dest.mkdir(parents=True, exist_ok=True)
templates = dest / "templates"
templates.mkdir(parents=True, exist_ok=True)
shutil.copytree(skill / "assets" / "brand", dest / "brand", dirs_exist_ok=True)
shutil.copytree(skill / "assets" / "fonts", dest / "fonts", dirs_exist_ok=True)
shutil.copytree(skill / "assets" / "styles", dest / "styles", dirs_exist_ok=True)
shutil.copytree(skill / "assets" / "vendor", dest / "vendor", dirs_exist_ok=True)
shutil.copy2(skill / "assets" / "analytics.js", dest / "analytics.js")
for name in ("login", "portal"):
    shutil.copy2(skill / "assets" / "templates" / f"{name}.html", templates / f"{name}.html")
print(templates / f"{args.template}.html")
