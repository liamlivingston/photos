#!/bin/bash
git pull origin main
rclone sync gdrive:photos-lfs .git/lfs/objects -P
