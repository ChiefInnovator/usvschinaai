#!/usr/bin/env python3
"""Offline, read-only reproduction of the September 6 rank calibration; requires scipy."""
import json,numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
x=json.loads((ROOT/'docs/research/llm-stats-ranking-fit.json').read_text());X=np.array(x['scores']);n=len(X)
pairs=[(i,j) for i in range(n) for j in range(i+1,n)];N=12+len(pairs)+n
A=[];lo=[];hi=[]
a=np.zeros(N);a[:12]=1;A.append(a);lo.append(1000);hi.append(1000)
for k,(i,j) in enumerate(pairs):
 a=np.zeros(N);a[:12]=(X[i]-X[j])/1000;a[12+k]=101
 A.append(a);lo.append(.01);hi.append(100.99)
for i in range(n):
 a=np.zeros(N)
 for k,(u,v) in enumerate(pairs):
  if u==i:a[12+k]=1
  if v==i:a[12+k]=-1
 for sign in [1,-1]:
  b=sign*a;b[12+len(pairs)+i]=-1;A.append(b);lo.append(-np.inf);hi.append(0)
c=np.zeros(N);c[12+len(pairs):]=[1+5/(i+1) for i in range(n)]
r=milp(c,integrality=[1]*(12+len(pairs))+[0]*n,bounds=Bounds([1]*12+[0]*(len(pairs)+n),[989]*12+[1]*len(pairs)+[14]*n),constraints=LinearConstraint(A,lo,hi),options={'time_limit':50,'mip_rel_gap':0})
w=np.rint(r.x[:12]);s=X@w/1000;rank=np.argsort(-s)
print(r.message,r.mip_gap,w,'distance',sum(abs(i-int(np.where(rank==i)[0][0])) for i in range(n)))
print([(x['order'][i],round(s[i],2)) for i in rank])
print(json.dumps({'weightsPercent':(w/10).tolist(),'objective':float(r.fun),'solverGap':float(r.mip_gap)}))
