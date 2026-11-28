#!/bin/bash
# usage: ./scripts/run_experiments.sh
LAB=clab-http20
OUT=results/raw.jsonl
: > $OUT
for RTT in 20 100 200; do
  ./scripts/set_rtt.sh $RTT
  sleep 2
  for RUN in 1 2 3; do
    for MODE in A B C; do
      echo "RTT=$RTT run=$RUN mode=$MODE ..."
      docker exec $LAB-client timeout 300 python3 /app/client.py --mode $MODE \
        | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); d['rtt']=$RTT; d['run']=$RUN; print(json.dumps(d))" >> $OUT
    done
  done
done
./scripts/set_rtt.sh clear
echo "done: $(wc -l < $OUT) runs saved to $OUT"
