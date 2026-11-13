"""Luvakule AI Brain: one coordinator with specialised agents.

The agents share one structured production plan (a JSON document stored in
``brain_plans.plan``) instead of passing free-form messages to each other, and
they reuse the same project context, so a plan costs a handful of AI calls
rather than one set per agent.

* llm.py       - the connected AI writer (Gemini, Ollama or Hugging Face) with JSON output
* timing.py    - chapter and scene durations that add up exactly to the requested length
* prompts.py   - turns structured scene data into picture prompts and video-model prompts
* catalog.py   - which picture/video routes are really connected, recommendations, estimates
* agents.py    - Film Director, Scriptwriter, Storyboard Artist (with camera, movement and
                 sound), Character Director, Continuity checker, Audio Director, Video
                 Specialist, Editor
* director.py  - Director Mode: runs the agents in order and records what each one did
"""
