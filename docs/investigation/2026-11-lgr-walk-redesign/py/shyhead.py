# read the geometry of a SHY file header (io_shy.f90 shy_write_header):
# returns dict with nkn, nel, nlv, hm3v (nel x 3), hlv (nlv), ilhv (nel),
# hev (nel, = mean of hm3v as makehev computes it, stored as float32)
import struct
import numpy as np

def _records(data, nmax):
    pos = 0; out = []
    while pos < len(data) and len(out) < nmax:
        (n,) = struct.unpack_from("<i", data, pos)
        out.append(data[pos + 4:pos + 4 + n])
        pos += 8 + n
    return out

def read_geom(path):
    with open(path, "rb") as fh:
        data = fh.read(64 * 1024 * 1024)
    r = _records(data, 24)
    nkn, nel, npr, nlv, nvar = struct.unpack("<5i", r[2])
    # r[0] idshy,nvers r[1] ftype r[2] dims r[3] nfix r[4] date r[5] nsimpar
    # r[6] simpar r[7] title r[8] femver r[9] empty; then nen3v ipev ipv
    # iarv iarnv xgv ygv hm3v hlv ilhv ilhkv
    assert len(r[9]) == 0, "unexpected header layout"
    nen3v = np.frombuffer(r[10], "<i4").reshape(nel, 3)
    hm3v = np.frombuffer(r[17], "<f4").reshape(nel, 3)
    hlv = np.frombuffer(r[18], "<f4")
    ilhv = np.frombuffer(r[19], "<i4")
    assert hlv.size == nlv and ilhv.size == nel
    hev = (hm3v.astype(np.float64).sum(axis=1) / 3.0).astype(np.float32)
    return dict(nkn=nkn, nel=nel, nlv=nlv, hm3v=hm3v, hlv=hlv, ilhv=ilhv,
                hev=hev, nen3v=nen3v)

if __name__ == "__main__":
    import sys
    g = read_geom(sys.argv[1])
    print("nkn %d nel %d nlv %d" % (g["nkn"], g["nel"], g["nlv"]))
    print("hlv", g["hlv"])
    print("hev min %.3f max %.3f; ilhv min %d max %d" % (g["hev"].min(), g["hev"].max(), g["ilhv"].min(), g["ilhv"].max()))
    print("elements with hev > 16: %d, > 51: %d, > 30: %d" % ((g["hev"] > 16).sum(), (g["hev"] > 51).sum(), (g["hev"] > 30).sum()))
