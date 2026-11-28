#!/bin/bash
# Supplementary ApacheBench runs (HTTP/1.0): with and without -k, 3 RTTs, 3 runs each
cd "$(dirname "$0")/.."
OUT=results/ab_raw.csv
echo "rtt_ms,mode,run,req_per_s,time_per_req_ms,failed,keepalive_reqs" > $OUT
for rtt in 20 100 200; do
  ./scripts/set_rtt.sh $rtt > /dev/null
  sleep 2
  for mode in nokeepalive keepalive; do
    k=""; [ "$mode" = "keepalive" ] && k="-k"
    for run in 1 2 3; do
      out=$(docker exec clab-http20-client ab $k -n 300 -c 5 http://10.10.3.10:8080/index.html 2>&1)
      rps=$(echo "$out" | awk '/Requests per second/{print $4}')
      tpr=$(echo "$out" | awk '/Time per request/ && /\(mean\)$/{print $4}')
      fail=$(echo "$out" | awk '/Failed requests/{print $3}')
      ka=$(echo "$out" | awk '/Keep-Alive requests/{print $3}')
      echo "$rtt,$mode,$run,$rps,$tpr,$fail,${ka:-0}" | tee -a $OUT
    done
  done
done
./scripts/set_rtt.sh 20 > /dev/null
echo DONE
