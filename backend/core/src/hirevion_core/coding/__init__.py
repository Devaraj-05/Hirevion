"""Coding answers (SP-16; PRD §45, §47, §48; ADR-0033).

The candidate answers a coding question in a plain text console on the desktop: they type the
code, choose its language from the question's languages (a label only) and submit it. Nothing is
ever executed. `console` serves the question to the desktop, keeps the last saved text when a
question ends without a submission, and stores the console's integrity events; `signals` turns
those events into what a reviewer sees. The code is reviewed after the interview by the evaluator
(`hirevion_core.evaluation.coding`).
"""
