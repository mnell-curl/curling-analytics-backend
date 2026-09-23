"""
One-off debug script: checks the RAW (untrimmed) score list length from
czapi's Boxscore for a given event, to test whether it reflects the
event's actual ends-format (8 vs 10) rather than being a fixed constant.

Usage:
    py check_raw_ends.py <cz_event_id>
"""

import sys
import czapi.api as api

event_id = int(sys.argv[1])
event = api.Event(cz_event_id=event_id)

if not event.is_valid:
    print(f"Event {event_id} is not valid")
    sys.exit(1)

boxscores = event.get_flat_boxscores()

lengths = set()
anomalies = []
for bs in boxscores:
    lengths.add(len(bs.score))
    if len(bs.score) != 10:
        anomalies.append(bs)

print(f"Total boxscore rows: {len(boxscores)}")
print(f"Distinct raw lengths seen across the WHOLE event: {sorted(lengths)}\n")

if anomalies:
    print(f"Rows with length != 10 ({len(anomalies)} found):")
    for bs in anomalies:
        print(f"  {bs.team_name:<20} draw {bs.draw_num:<3} length: {len(bs.score):>2}  score: {bs.score}")
else:
    print("No anomalies found — every row was exactly length 10.")
