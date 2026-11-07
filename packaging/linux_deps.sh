#!/bin/sh
# What building the Linux app needs on Ubuntu, beyond the Python packages: the libraries Qt's
# window uses, which the build bundles alongside it.
set -e
sudo apt-get update
sudo apt-get install -y --no-install-recommends libegl1 libgl1 libfontconfig1 libdbus-1-3 libxkbcommon0 \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1
