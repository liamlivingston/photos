#!/bin/bash
git push origin main
rclone sync photos/ gdrive:photos-lfs -P
