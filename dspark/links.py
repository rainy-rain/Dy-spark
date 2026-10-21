"""Where to send someone for help.

One place, so the links inside error messages cannot drift away from the ones in
the README. Every message that tells a person to go and read something should
point here rather than pasting a URL inline.
"""

from __future__ import annotations

REPO = "https://github.com/rainy-rain/Dy-spark"
README = f"{REPO}/blob/main/README.md"

# Anchors in the Chinese README.
INSTALL = f"{README}#安装"
QUICK_START = f"{README}#快速开始"
CONFIG = f"{README}#配置"
TROUBLESHOOTING = f"{README}#常见问题"
EMOJI = f"{README}#步骤-6可选--改发表情"

TEMPLATE = f"{REPO}/blob/main/config.example.yaml"

PYTHON = "https://www.python.org/downloads/"
PLAYWRIGHT = "https://playwright.dev/python/docs/intro"
EDGE = "https://www.microsoft.com/edge"
CHROME = "https://www.google.com/chrome/"
DOUYIN = "https://www.douyin.com/"
