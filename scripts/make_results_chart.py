# Draws Figure 4 of the report. Values are the mean +/- sd from results/summary.csv
# (printed by scripts/summarize.py), copied in by hand.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
page={'A':([0.269,1.068,2.062],[0.014,0.007,0.004]),'B':([0.224,0.745,1.445],[0.011,0.002,0.004]),'C':([0.216,0.745,1.451],[0.005,0.002,0.005])}
rps={'A':([95.6,24.2,12.3],[0.3,0.1,0.0]),'B':([96.9,47.3,24.1],[0.1,0.1,0.0]),'C':([657.3,364.9,213.5],[22.0,14.9,10.4])}
col={'A':'#c0392b','B':'#2980b9','C':'#27ae60'}
lab={'A':'A: direct, close','B':'B: direct, persistent','C':'C: persistent via proxy'}
fig,ax=plt.subplots(1,2,figsize=(8,3),dpi=200)
x=np.arange(3);w=0.26
for i,m in enumerate('ABC'):
    ax[0].bar(x+(i-1)*w,page[m][0],w,yerr=page[m][1],color=col[m],label=lab[m],capsize=2)
    ax[1].bar(x+(i-1)*w,rps[m][0],w,yerr=rps[m][1],color=col[m],capsize=2)
for a,t,y in zip(ax,['(a) Page-bundle load time (21 objects)','(b) Load test, 300 requests, concurrency 5'],['Seconds (mean ± sd, n=3)','Requests per second']):
    a.set_xticks(x);a.set_xticklabels(['20 ms','100 ms','200 ms']);a.set_xlabel('Target RTT');a.set_ylabel(y);a.set_title(t,fontsize=9);a.grid(axis='y',alpha=.3)
ax[0].legend(fontsize=7,loc='upper left')
plt.tight_layout();plt.savefig('results/results_chart.png')
print('saved results/results_chart.png')
