#!/bin/bash
git push origin main
rclone sync .git/lfs/objects gdrive:photos-lfs -P
