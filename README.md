# Git + Google Drive Large File Storage (via rclone)

This repository uses **rclone** and **Google Drive** to store large files externally, avoiding Git LFS or GitHub storage limits.

---

## 📦 Overview

This setup allows you to:
* Keep source code and metadata tracked by Git.
* Store large binary assets (e.g., photos, videos, datasets) in Google Drive.
* Sync those large files between your local environment and Drive using `rclone`.
* Avoid uploading large files to GitHub or Git LFS.

---

## ⚙️ Setup Instructions

### 1. Clone the repository

```
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```

### 2. Install rclone
Follow the installation guide for your OS:
👉 https://rclone.org/install/

To verify installation:
```
rclone version
```

### 3. Configure Google Drive remote
Run:
```
rclone config
```

When prompted:
* Choose `n` for New remote.
* Name it: `gdrive`
* Select `drive` as the storage backend.
* Follow the OAuth link to authorize rclone with your Google account.
* Accept defaults for the rest unless you need specific options.

Test your connection:
```
rclone ls photos-lfs:
```

### 4. Ignore large files in Git
Add file patterns for large assets to `.gitignore`.

Example:
```
# Ignore large local files
photos/
videos/
data/
```
This prevents Git from uploading them to GitHub.

### 5. Upload large files to Google Drive
To sync large files to your Drive folder:
```
rclone sync photos/ photos-lfs:photos -P
```
* The first path (`photos/`) is your local folder.
* The second path (`photos-lfs:photos`) is the Google Drive destination.
* `-P` shows progress.

### 6. Download large files from Google Drive
If you need to restore them on another system:
```
rclone sync photos-lfs:photos photos/ -P
```
This pulls everything from Google Drive into your local folder.

### 7. (Optional) Automate syncing
You can create a small script `sync_photos.sh`:
```
#!/bin/bash
rclone sync photos/ photos-lfs:photos -P
```

Then run:
```
chmod +x sync_photos.sh
./sync_photos.sh
```

---

## ✅ Summary

| Task | Command |
| :--- | :--- |
| Upload to Drive | `rclone sync photos/ photos-lfs:photos -P` |
| Download from Drive | `rclone sync photos-lfs:photos photos/ -P` |
| List remote files | `rclone ls photos-lfs:` |

---

## 🧠 Notes
* The `.gitignore` ensures large files are never committed to Git or GitHub.
* `.git/lfs/objects` is **not** used — this setup replaces Git LFS entirely.
* You can reuse the same `photos-lfs` remote for multiple repos if desired.

---

## 🛠 Example Directory Structure

```
myproject/
├── src/
├── docs/
├── photos/        # ignored by git
├── .gitignore
├── rclone.conf    # (optional) if using custom config
└── README.md
```

* **Author:** \[Your Name]
* **Remote name:** `photos-lfs`
* **Storage:** Google Drive
