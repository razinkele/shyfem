#!/usr/bin/env python3
"""wd.py DUMP... : per dump: dry elements (iwegv>0), elements with iwetv<0 (dry counter),
elements that re-wetted since the previous dump, and max|dtw|, windcd range"""
import sys, struct
import numpy as np
def load(p):
    d={}; buf=open(p,'rb').read(); i=0
    while i<len(buf):
        name=buf[i:i+16].decode().strip(); (n,)=struct.unpack_from('<i',buf,i+16); i+=20
        d[name]=np.frombuffer(buf,'<f8',n,i); i+=8*n
    return d
prev=None
for p in sys.argv[1:]:
    d=load(p); w=d['iwegv']; c=d['iwetv']
    rew = int(np.count_nonzero((prev>0)&(w==0))) if prev is not None else -1
    dry2wet = int(np.count_nonzero((prev==0)&(w>0))) if prev is not None else -1
    print(f"{p.split('/')[-1]:24s} dt={d['dt'][0]:6.1f} dry={np.count_nonzero(w>0):5d} iwetv<0={np.count_nonzero(c<0):5d} "
          f"min(iwetv)={c.min():6.0f} rewet={rew:4d} newdry={dry2wet:4d} max|dtw|={np.abs(d['dtw_heat']).max():.3e} "
          f"windcd=[{d['windcd'].min():.3e},{d['windcd'].max():.3e}]")
    prev=w
