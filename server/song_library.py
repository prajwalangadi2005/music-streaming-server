import os, json, sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, BASE_DIR)

from config import SONGS_DIR

SONGS_PATH = os.path.join(ROOT_DIR, SONGS_DIR)

def get_song_catalog():
    catalog = []
    song_id = 1
    if not os.path.exists(SONGS_PATH):
        os.makedirs(SONGS_PATH)
        return catalog
    for filename in sorted(os.listdir(SONGS_PATH)):
        if filename.lower().endswith((".mp3", ".wav")):
            filepath = os.path.join(SONGS_PATH, filename)
            size     = os.path.getsize(filepath)
            catalog.append({
                "id"      : song_id,
                "title"   : os.path.splitext(filename)[0],
                "filename": filename,
                "size"    : size,
                "size_kb" : round(size / 1024, 1)
            })
            song_id += 1
    return catalog

def get_song_by_id(song_id):
    for song in get_song_catalog():
        if song["id"] == song_id:
            return song
    return None

def get_song_path(song_id):
    song = get_song_by_id(song_id)
    if song:
        return os.path.join(SONGS_PATH, song["filename"])
    return None