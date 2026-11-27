# One-shot. The job reads the master list, then data/high_prob_next.json,
# and scans the next 300 contracts at or above $5,000 that are not already
# on the board. Fork and fuzz run only when the new heat is above 0.
# This file does not start an under-$5k queue.
high-prob
