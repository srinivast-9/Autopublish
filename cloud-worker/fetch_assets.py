"""Fetch the approved Chess.com Neo piece sprites at image-build time."""
from __future__ import annotations
import argparse
import io
from pathlib import Path
import requests
from PIL import Image

BASE = "https://assets-themes.chess.com/image/ejgfv/150/{}.png"
PIECE_IDS = ("bk", "bq", "br", "bb", "bn", "bp", "wk", "wq", "wr", "wb", "wn", "wp")


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--out-dir",default="assets")
    args=parser.parse_args()
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    session=requests.Session()
    for name in PIECE_IDS:
        url=BASE.format(name)
        response=session.get(url,timeout=(10,30),headers={"User-Agent":"ChessBitsCloudWorker/0.1"})
        response.raise_for_status()
        ctype=(response.headers.get("Content-Type") or "").split(";",1)[0].strip().lower()
        if ctype not in ("image/png","application/octet-stream"):
            raise RuntimeError(f"Unexpected content type for Neo piece {name}: {ctype}")
        image=Image.open(io.BytesIO(response.content)).convert("RGBA")
        if image.width < 64 or image.height < 64 or image.width > 1000 or image.height > 1000:
            raise RuntimeError(f"Unexpected dimensions for Neo piece {name}: {image.size}")
        image.save(out/f"{name}.png",format="PNG",optimize=True)
        print(f"Fetched Neo sprite {name}: {image.width}x{image.height}")

if __name__=="__main__":
    main()
