#!/usr/bin/env bash
set -euo pipefail

NS="dionysus"

echo "🔌 Starting port-forwards in namespace \"$NS\"..."

# Start both port-forwards in the background and record PIDs
kubectl port-forward pods/dionysus-postgresql-0 5432:5432 -n "$NS" &
P1=$!
kubectl port-forward pods/dionysus-neo4j-0 7474:7474 7687:7687 -n "$NS" &
P2=$!

PIDS=($P1 $P2)
echo "Started port-forwards (PIDs: ${PIDS[*]})"

cleanup() {
  echo "🛑 Stopping port-forwards..."
  kill "${PIDS[@]}" 2>/dev/null || true
  wait "${PIDS[@]}" 2>/dev/null || true
  echo "✅ Port-forwards stopped."
}

trap cleanup INT TERM

# Wait for background processes (this keeps the script running while port-forwards are active)
wait
