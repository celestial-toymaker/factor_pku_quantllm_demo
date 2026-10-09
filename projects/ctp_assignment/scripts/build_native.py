"""Build official bindings against the user's matching macOS SDK headers/libraries.

Does not download SDKs, connect to CTP, or redistribute binaries. Run with the
locked native environment. Originals remain unchanged; all edits are in work.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import time
from fetch_sources import SOURCES

SDK_HASHES = {
    "thostmduserapi_se.framework.zip": "90c4e21a961172383ee1656159f0113dbe108568fb13f960ecb00418f434e1c4",
    "thosttraderapi_se.framework.zip": "49547e93b01bca9ac2e1fedae8d13f16d76c93498dba637c528a49cdb1e78e1c",
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--sdk", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    a = p.parse_args()
    assert sys.version_info[:3] == (3, 13, 5), "Use the pinned Python 3.13.5 environment"
    import pybind11
    revision, archive_digest = SOURCES["vnpy_ctp"]
    archive = a.source.parent / "vnpy_ctp.tar.gz"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_digest, "Official source archive differs"
    source_files = 0
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            if member.isfile():
                relative = Path(*Path(member.name).parts[1:])
                original = bundle.extractfile(member).read()
                assert (a.source / relative).read_bytes() == original, "Source file differs: " + str(relative)
                source_files += 1
    a.work.mkdir(parents=True, exist_ok=True)
    dst = a.work / "binding"
    if dst.exists():
        raise SystemExit("Use a fresh build directory; earlier build evidence is preserved")
    shutil.copytree(a.source, dst, symlinks=True)
    api = dst / "vnpy_ctp/api"
    out = a.work / "native"
    out.mkdir()
    records = []

    def run(cmd, name):
        t = time.time()
        with (a.work / (name + ".log")).open("w") as log:
            r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        records.append({"command": cmd, "exit_code": r.returncode,
                        "elapsed_seconds": round(time.time()-t, 3), "log": name+".log"})
        (a.work / "commands.json").write_text(json.dumps(records, indent=2)+"\n")
        if r.returncode:
            raise SystemExit(f"{name} failed; see its log")

    headers = a.work / "headers"
    headers.mkdir()
    (headers / "ctp").mkdir()
    for name, expected in SDK_HASHES.items():
        z = a.sdk / name
        assert hashlib.sha256(z.read_bytes()).hexdigest() == expected, "SDK fingerprint differs"
        run(["ditto", "-x", "-k", str(z), str(out)], name.split(".")[0]+"-extract")
        framework = out / name.removesuffix(".zip")
        for h in (framework / "Versions/A/Headers").glob("*.h"):
            dest = headers / h.name
            if dest.exists():
                assert dest.read_bytes() == h.read_bytes(), "MD/TD shared header mismatch"
            shutil.copy2(h, dest)
            shutil.copy2(h, headers / "ctp" / h.name)

    td = api / "vnctp/vnctptd/vnctptd.cpp"
    s = td.read_text()
    old = 'this->api->ReqUserLogin(&myreq, reqid, 2, "vn")'
    assert s.count(old) == 1
    td.write_text(s.replace(old, "this->api->ReqUserLogin(&myreq, reqid)"))
    for mod, cls in (("vnctpmd", "MdApi"), ("vnctptd", "TdApi")):
        f = api / "vnctp" / mod / (mod+".cpp")
        text = f.read_text()
        assert f'.def("exit", &{cls}::exit, call_guard<gil_scoped_release>())' in text
    # The 6.7.13 macOS header uses the two-argument login method. Both headers
    # and frameworks below come from this exact SDK, avoiding ABI mixing.
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    for module, framework in (("vnctpmd", "thostmduserapi_se"), ("vnctptd", "thosttraderapi_se")):
        run(["clang++", "-std=c++17", "-O2", "-shared", "-fPIC", "-arch", "arm64",
             "-mmacosx-version-min=11.0", "-undefined", "dynamic_lookup",
             "-I"+sysconfig.get_path("include"), "-I"+pybind11.get_include(),
             "-I"+str(headers), "-I"+str(api / "vnctp"),
             "-F"+str(out), "-framework", framework, "-liconv",
             "-Wl,-rpath,@loader_path", str(api / "vnctp" / module / (module+".cpp")),
             "-o", str(out / (module+suffix))], module+"-build")
    outputs = {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
               for f in sorted(out.rglob("*")) if f.is_file() and not f.is_symlink()}
    (a.work / "build_manifest.json").write_text(json.dumps({
        "sdk": "v6.7.13_MacOS_20260529", "sdk_archives": SDK_HASHES,
        "binding_commit": "1be9bfb5292208e5c258cc769c90be4abe83f9a9",
        "source_archive_sha256": archive_digest, "original_source_files_verified": source_files,
        "python": sys.version, "architecture": "arm64", "outputs": outputs,
        "patch": "macOS 6.7.13 two-argument login signature; original GIL-safe shutdown verified",
        "new_613_methods_exposed": False, "network_connections": 0,
    }, indent=2)+"\n")
    print("Native build completed; no CTP connections made.")


if __name__ == "__main__":
    main()
