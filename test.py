import exiftool

files = ["photos/lumix-export/P1090567.jpg"]
with exiftool.ExifToolHelper() as et:
    metadata = et.get_metadata(files)
    for d in metadata:
        print("{:20.20} {:20.20}".format(d["SourceFile"],
                                         d["EXIF:DateTimeOriginal"]))
