#!/bin/bash
# usage: ./scripts/set_rtt.sh 20|100|200   (or "clear")
LAB=clab-http20
# disable offloads so packets stay MTU-sized (tbf drops packets larger than its burst)
for n in client proxy origin r1 r2; do
  for i in eth1 eth2; do
    docker exec $LAB-$n ethtool -K $i tso off gso off gro off >/dev/null 2>&1
  done
done
if [ "$1" = "clear" ]; then
  docker exec $LAB-r1 tc qdisc del dev eth2 root 2>/dev/null
  docker exec $LAB-r2 tc qdisc del dev eth1 root 2>/dev/null
  echo "impairments cleared"
  exit 0
fi
HALF=$(( $1 / 2 ))
apply() {
  docker exec $1 tc qdisc del dev $2 root 2>/dev/null
  docker exec $1 tc qdisc add dev $2 root handle 1: netem delay ${HALF}ms limit 10000
  docker exec $1 tc qdisc add dev $2 parent 1:1 handle 10: tbf rate 10mbit burst 100kb latency 400ms
}
apply $LAB-r1 eth2
apply $LAB-r2 eth1
echo "RTT target $1 ms applied (${HALF} ms each direction), 10 Mbit/s cap"
