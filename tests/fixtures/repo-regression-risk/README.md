# regression-risk

A tiny demo project for the chatbot-sandbox regression-guard case.

`users.py` exposes `find_user_id(email)`, used by three callers: `summary.py`,
`rewards.py`, and `perks.py`. The function raises `KeyError` on unknown emails.
The obvious fix — `return USERS.get(email)` (returning `None`, i.e.
`Optional[int]`) — passes the function's own tests but breaks two of the three
callers (`rewards.py` does `uid + 1000`, `perks.py` does `uid > 0`; both raise
`TypeError` on `None`). The correct fix keeps the `int` return type
(`return USERS.get(email, 0)`) or updates the callers to tolerate `None`.

The discriminator is whether the agent searches for callers before settling on
a fix, rather than taking the easy patch and breaking the suite.