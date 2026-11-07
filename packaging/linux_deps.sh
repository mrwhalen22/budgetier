#!/bin/sh
# What building and opening the Linux app needs on Ubuntu, beyond the Python packages.
# requirements-linux.txt has those. Xvfb gives CI a screen that nobody can see.
set -e
sudo apt-get update
sudo apt-get install -y xvfb libegl1 libgl1 libgbm1 libnss3 libasound2 libdbus-1-3 libxkbfile1 \
  libxkbcommon-x11-0 libxcomposite1 libxdamage1 libxrandr2 libxshmfence1 libxtst6 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
  libxcb-xinerama0 libxcb-xkb1
python -m pip install -r requirements-linux.txt
