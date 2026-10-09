"""Fetch immutable official upstream archives; never executes downloaded code."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

SOURCES = {
    "vnpy": ("c6e231caf32b7fc97e6459817fff66458cf7e7c4", "1f123301bfc04170894c78e2df93cb20bb6c53bf1cc17dbef94340627f0812cc"),
    "vnpy_ctp": ("1be9bfb5292208e5c258cc769c90be4abe83f9a9", "0225d2523f0b57529bf3b26df1b7dce8d79235096ceb2dd509a465241d41fad6"),
    "vnpy_ctastrategy": ("7a8768de9784dda35a7b261a7ade1dbfbff50919", "b3aca4f20a33abe3be34c3041044d2da0b9343c27bb18f092cd41df22b11c563"),
}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("destination",type=Path)
    a=parser.parse_args();a.destination.mkdir(parents=True,exist_ok=True)
    for repo,(sha,digest) in SOURCES.items():
        url=f"https://codeload.github.com/vnpy/{repo}/tar.gz/{sha}"
        archive=a.destination/(repo+".tar.gz")
        if not archive.exists():
            with urllib.request.urlopen(url,timeout=60) as r:
                archive.write_bytes(r.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=digest:
            raise SystemExit("Archive fingerprint differs; no extraction: "+repo)
        target=a.destination/(repo+"-"+sha)
        if not target.exists():
            with tarfile.open(archive) as t:t.extractall(a.destination,filter="data")
        print(json.dumps({"repository":"vnpy/"+repo,"commit":sha,"archive_sha256":digest}))

if __name__=="__main__":main()
