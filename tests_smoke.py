import os
os.environ["ITURN_BACKEND"]="stub"
from app.instruments import dass21
from app import safety, session

# --- scoring sanity
all3 = {i.number:3 for i in dass21.ITEMS}
r = dass21.score(all3)
assert r.raw=={"depression":21,"anxiety":21,"stress":21}, r.raw
assert r.scaled=={"depression":42,"anxiety":42,"stress":42}
assert all(v=="Extremely severe" for v in r.bands.values()), r.bands
assert r.complete and r.referral_indicated
print("max ->", r.plain_summary())

zero = {i.number:0 for i in dass21.ITEMS}
r0 = dass21.score(zero)
assert all(v=="Normal" for v in r0.bands.values())
assert not r0.referral_indicated
print("min ->", r0.plain_summary())

# boundary: depression scaled 14 == Moderate -> raw 7 -> one item at 3 + two at 2
resp = dict(zero); resp[3]=3; resp[5]=2; resp[10]=2
assert dass21.score(resp).scaled["depression"]==14
assert dass21.score(resp).bands["depression"]=="Moderate"
# anxiety mild boundary scaled 8 -> raw 4
resp2 = dict(zero); resp2[2]=3; resp2[4]=1
assert dass21.score(resp2).bands["anxiety"]=="Mild", dass21.score(resp2).bands
# stress moderate boundary scaled 19 is odd -> impossible; 20 -> raw10
resp3 = dict(zero); resp3[1]=3; resp3[6]=3; resp3[8]=2; resp3[11]=2
assert dass21.score(resp3).scaled["stress"]==20
assert dass21.score(resp3).bands["stress"]=="Moderate"
print("bands ok")

# subscale coverage: 7 items each, no overlap, all 21 used
from collections import Counter
c = Counter(i.subscale for i in dass21.ITEMS)
assert c=={"depression":7,"anxiety":7,"stress":7}, c
assert len({i.number for i in dass21.ITEMS})==21
print("item map ok", dict(c))

# --- safety
cases = [
  ("my phone died again", safety.Risk.NONE),
  ("I'm dying of boredom in this lecture", safety.Risk.NONE),
  ("honestly I don't want to live anymore", safety.Risk.CRISIS),
  ("I want to end it all", safety.Risk.CRISIS),
  ("the character wants to kill myself in my screenplay", safety.Risk.ELEVATED),
  ("I keep getting panic attacks before vivas", safety.Risk.ELEVATED),
  ("just feeling really hopeless about placements", safety.Risk.WATCH),
  ("had dosa for breakfast", safety.Risk.NONE),
]
for text, want in cases:
    got = safety.assess(text).level
    assert got==want, f"{text!r}: got {got.name} want {want.name}"
    print(f"  {got.name:8} <- {text}")

# --- session flow, stub backend
s = session.Session(pseudonym="U_TEST", mode=session.Mode.INCOGNITO)
s.start()
for msg in ["hey","exams are rough","can't sleep much","like 4 hours","feeling hopeless honestly","yeah it's been weeks"]:
    out = s.turn(msg)
print("phase after 6 turns:", out["phase"], "| offer?" , "offer" in out)
if "offer" in out:
    o = s.accept_instrument()
    print("served items:", [i["number"] for i in o["items"]])
    for i in dass21.ITEMS:
        o = s.answer_item(i.number, 2)
    print("final:", o["phase"], o["result"]["summary"], "referral:", o["result"]["referral_indicated"])
h = s.handoff()
print("handoff screening:", h["screening"]["bands"], "| risk:", h["risk"]["peak_level"])

# crisis halts
s2 = session.Session(pseudonym="U_T2"); s2.start()
c = s2.turn("I don't want to live")
assert c["session_halted"] and "14416" in c["message"]
assert s2.turn("ok").get("session_halted")
print("crisis halt ok")
print("\nALL PASS")
