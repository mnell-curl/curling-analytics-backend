import czapi.api as api

event = api.Event(cz_event_id=9478)
print(event.url)          # confirms it built the right CurlingZone URL
print(event.is_valid)     # True/False — sanity check that the event exists
print(event.draws)        # list of draw numbers available for this event

boxscores = event.get_flat_boxscores()
print(boxscores[0])       # one row: team, opponent, hammer, end-by-end score, etc.